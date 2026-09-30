"""Living study notes: session linkage, synthesis proposals, section provenance.

A study note is an ordinary workspace note with ``study_note: True``,
``session_ids`` and ``tutor_updates`` (ask|auto|never) in frontmatter. The tutor
only ever appends new sections or updates tutor-owned sections; user paragraphs
are protected by the provenance sidecar (stable section IDs, tombstones) and by
optimistic note revisions on every write.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import text

from .journey_service import JourneyService
from .learner_graph import LearnerGraphRepository
from .material_service import MaterialService, problem
from .model_provider import ModelProviderError
from .models import utc_now
from .session_models import short_title
from .study_note_models import NoteProposal, ProposalCreate
from .workflow_store import WorkflowStore, uid
from .workspace_note_models import WorkspaceNoteCreate, WorkspaceNoteRecord, WorkspaceNoteUpdate
from .workspace_note_service import WorkspaceNoteError, WorkspaceNoteService

PROPOSAL_KIND = "note_proposal"
TURN_BUDGET = 6000


def _content_hash(text_value: str) -> str:
    return hashlib.sha256(text_value.encode("utf-8")).hexdigest()


def _section_markdown(heading: str, body: str) -> str:
    return f"\n\n## {heading.strip()}\n\n{body.strip()}\n"


def _section_record_hash(heading: str, body: str) -> str:
    """Hash the canonical tutor section form used in the note body."""
    return _content_hash(f"## {heading.strip()}\n\n{body.strip()}\n")


def _section_body_from_slice(section_slice: str) -> str:
    """Extract the markdown body beneath a ``## heading`` slice."""
    if section_slice.startswith("## "):
        newline = section_slice.find("\n")
        if newline < 0:
            return ""
        return section_slice[newline + 1:].strip()
    return section_slice.strip()


def _hashes_match(stored: str, section_slice: str, body: str) -> bool:
    """True when stored hash matches the live section or legacy body-only hashes."""
    if stored == _content_hash(section_slice):
        return True
    extracted = _section_body_from_slice(section_slice)
    return stored in {_content_hash(extracted), _content_hash(body.strip()), _content_hash(f"{extracted}\n")}


def _find_section(body: str, heading: str) -> tuple[int, int] | None:
    """Locate (start, end) offsets of a ``## heading`` section, or None."""
    lines = body.splitlines(keepends=True)
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line)
    target = heading.strip().lower()
    start = None
    for index, line in enumerate(lines):
        if line.startswith("## ") and line[3:].strip().lower() == target:
            start = index
            break
    if start is None:
        return None
    end = len(body)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            end = offsets[index]
            break
    return (offsets[start], end)


class StudyNoteService:
    def __init__(self, store, provider):
        self.store, self.provider = store, provider
        self.records = WorkflowStore(store)
        self.notes = WorkspaceNoteService(store)

    # -- study-note linkage -------------------------------------------------

    def _session(self, owner, sid):
        return MaterialService(self.store).session(owner, sid)

    def find_note(self, owner, sid) -> WorkspaceNoteRecord | None:
        for summary in self.notes.list(owner):
            sessions = (summary.frontmatter or {}).get("session_ids") or []
            if sid in sessions and (summary.frontmatter or {}).get("study_note") is True:
                return self.notes.get(owner, summary.id)
        return None

    def get_or_create_note(self, owner, sid) -> WorkspaceNoteRecord:
        existing = self.find_note(owner, sid)
        if existing is not None:
            return existing
        session = self._session(owner, sid)
        title = (session.title or "").strip() or short_title(session.goal)
        if title == "Untitled conversation":
            title = "Study notes"
        # Auto-apply by default so Learn writes the Lesson into Notes while
        # chat stays for teaching, quizzes, and follow-ups.
        frontmatter = {"study_note": True, "session_ids": [sid], "tutor_updates": "auto", "title_source": "auto"}
        if session.course_id:
            frontmatter["course_id"] = session.course_id
        return self.notes.create(
            owner,
            WorkspaceNoteCreate(
                title=title,
                body=(
                    f"# {title}\n\n"
                    "This Lesson was created when you started Learn. "
                    "Keep learning in chat—quizzes, follow-ups, and the next steps—"
                    "and durable ideas are added here as you go. "
                    "Your own writing is never rewritten.\n"
                ),
                frontmatter=frontmatter,
            ),
        )

    def sync_session_title(self, owner: str, sid: str, previous_title: str, title: str) -> None:
        """Rename an untouched automatic lesson title when its chat gets a better name."""
        note = self.find_note(owner, sid)
        if note is None or note.title == title:
            return
        source = note.frontmatter.get("title_source")
        if source == "user" or (source is None and note.title != previous_title):
            return
        old_heading = f"# {note.title}\n"
        body = f"# {title}\n{note.body[len(old_heading):]}" if note.body.startswith(old_heading) else note.body
        self.notes.update(owner, note.id, WorkspaceNoteUpdate(
            expected_revision=note.revision, title=title, body=body,
            frontmatter={"title_source": "auto"},
        ))

    def ensure_learn_lesson(self, owner, sid) -> WorkspaceNoteRecord:
        """Open the Notes Lesson for Learn: create if needed, auto-apply, flush backlog."""
        note = self.get_or_create_note(owner, sid)
        if self.tutor_updates_mode(note) == "ask":
            note = self.set_tutor_updates(owner, note.id, "auto", note.revision)
            self._flush_proposed(owner, sid)
            note = self.notes.get(owner, note.id)
        return note

    def _flush_proposed(self, owner, sid) -> None:
        """Apply any leftover chat proposals into the Lesson once auto is on."""
        for record in self.list_proposals(owner, sid, status="proposed"):
            try:
                self.accept(owner, record["id"])
            except Exception:
                continue

    def tutor_updates_mode(self, note: WorkspaceNoteRecord) -> str:
        mode = (note.frontmatter or {}).get("tutor_updates", "auto")
        return mode if mode in {"ask", "auto", "never"} else "auto"

    def set_tutor_updates(self, owner, note_id, mode: str, expected_revision: int) -> WorkspaceNoteRecord:
        if mode not in {"ask", "auto", "never"}:
            problem("invalid_mode", "Tutor updates must be ask, auto, or never.", 422)
        note = self.notes.get(owner, note_id)
        return self.notes.update(
            owner, note_id,
            WorkspaceNoteUpdate(expected_revision=expected_revision, frontmatter={"tutor_updates": mode}),
        )

    # -- provenance sidecar ---------------------------------------------------

    def _provenance_rows(self, owner, note_id, conn=None):
        query = text("SELECT * FROM note_section_provenance WHERE owner_id=:owner AND note_id=:note")
        if conn is None:
            with self.store.engine.connect() as connection:
                return connection.execute(query, {"owner": owner, "note": note_id}).mappings().all()
        return conn.execute(query, {"owner": owner, "note": note_id}).mappings().all()

    def list_sections(self, owner, note_id) -> list[dict]:
        return [dict(row) for row in self._provenance_rows(owner, note_id)]

    def _record_section(self, conn, owner, note_id, section_id, heading, owner_kind,
                        created_from, revision, content_hash, concept_title=None,
                        graph_concept_id=None, learner_concept_id=None, tombstoned=False) -> None:
        now = utc_now()
        existing = conn.execute(
            text("SELECT id FROM note_section_provenance WHERE owner_id=:owner AND note_id=:note AND section_id=:section"),
            {"owner": owner, "note": note_id, "section": section_id},
        ).first()
        if existing:
            conn.execute(
                text("UPDATE note_section_provenance SET heading=:heading, owner_kind=:kind, revision=:revision, "
                     "content_hash=:hash, concept_title=:ctitle, graph_concept_id=:gcid, learner_concept_id=:lcid, "
                     "tombstoned=:tomb, updated_at=:now WHERE owner_id=:owner AND note_id=:note AND section_id=:section"),
                {"heading": heading, "kind": owner_kind, "revision": revision, "hash": content_hash,
                 "ctitle": concept_title, "gcid": graph_concept_id, "lcid": learner_concept_id,
                 "tomb": tombstoned, "now": now, "owner": owner, "note": note_id, "section": section_id},
            )
            return
        conn.execute(
            text("INSERT INTO note_section_provenance(id, owner_id, note_id, section_id, heading, owner_kind, created_from, "
                 "revision, content_hash, concept_title, graph_concept_id, learner_concept_id, tombstoned, created_at, updated_at) "
                 "VALUES(:id, :owner, :note, :section, :heading, :kind, :created, :revision, :hash, :ctitle, :gcid, :lcid, :tomb, :now, :now)"),
            {"id": uid("secprov"), "owner": owner, "note": note_id, "section": section_id, "heading": heading,
             "kind": owner_kind, "created": created_from, "revision": revision, "hash": content_hash,
             "ctitle": concept_title, "gcid": graph_concept_id, "lcid": learner_concept_id, "tomb": tombstoned, "now": now},
        )

    def _tombstoned(self, owner, note_id, created_from) -> bool:
        return any(row["tombstoned"] for row in self._provenance_rows(owner, note_id)
                   if row["created_from"] == created_from)

    # -- concept linkage ---------------------------------------------------------

    def resolve_learner_concept(self, owner, graph_concept_id: str | None) -> str | None:
        if not graph_concept_id:
            return None
        try:
            graph = LearnerGraphRepository(self.store).get_graph(owner)
        except Exception:
            return None
        for concept in graph.concepts:
            if graph_concept_id in (concept.source_concept_ids or []):
                return concept.id
        return None

    # -- manual insight (explicit, user-owned) --------------------------------------

    def save_insight(self, owner, sid, heading: str | None, body: str) -> dict:
        # NOTE: note-file writes use their own transactions; the provenance
        # write below runs afterwards so two connections never overlap.
        note = self.get_or_create_note(owner, sid)
        title = (heading or "Insight").strip() or "Insight"
        fresh = self.notes.get(owner, note.id)
        updated = self.notes.update(
            owner, note.id,
            WorkspaceNoteUpdate(expected_revision=fresh.revision, body=fresh.body + _section_markdown(title, body)),
        )
        section_id = uid("sec")
        with self.store.transaction() as conn:
            self._record_section(conn, owner, note.id, section_id, title, "user", f"manual:{section_id}",
                                 updated.revision, _content_hash(body))
        return {"noteId": updated.id, "revision": updated.revision, "sectionId": section_id}

    # -- synthesis (background job) ----------------------------------------------------

    def _require_provider(self):
        if not self.provider:
            raise ModelProviderError("Connect a model provider to synthesize study notes. Your chat is saved.")
        return self.provider

    def _turn_text(self, turn: dict) -> tuple[str, str, str | None, str]:
        lesson = turn.get("lesson") or {}
        blocks = lesson.get("blocks") or []
        parts = []
        for block in blocks:
            heading = (block.get("heading") or "").strip()
            text_value = (block.get("body") or "").strip()
            if text_value:
                parts.append(f"{heading}\n{text_value}" if heading else text_value)
        joined = "\n\n".join(parts)
        if len(joined) > TURN_BUDGET:
            joined = joined[:TURN_BUDGET] + "\n…"
        return turn.get("question", ""), joined, lesson.get("conceptId"), lesson.get("id", "")

    def _concept_title(self, owner, session, graph_concept_id: str | None) -> str | None:
        if not graph_concept_id:
            return None
        graph = self.store.get_graph(session.graph_id)
        if graph is None:
            return None
        for concept in graph.concepts:
            if concept.id == graph_concept_id:
                return concept.title
        return None

    def _match_tutor_section(self, rows: list, heading: str) -> str | None:
        """Return a tutor-owned section_id whose heading matches, else None."""
        target = heading.strip().lower()
        if not target:
            return None
        for row in rows:
            if row.get("tombstoned") or row.get("owner_kind") != "tutor":
                continue
            if str(row.get("heading") or "").strip().lower() == target:
                return row["section_id"]
        return None

    def prepare(self, owner, sid, command: ProposalCreate):
        session = self._session(owner, sid)
        provider = self._require_provider()
        note = self.get_or_create_note(owner, sid)
        created_from = ""
        lesson_id: str | None = None
        context: dict = {}
        if command.origin == "quiz":
            if not command.attempt_ids:
                problem("attempts_required", "Choose at least one quiz attempt to review.", 422)
            weak: list[dict] = []
            for attempt_id in command.attempt_ids:
                try:
                    attempt = self.records.read(owner, attempt_id, "attempt")
                except Exception:
                    problem("attempt_not_found", "A quiz attempt is no longer available.", 404)
                score = attempt.get("score")
                if score is None or score < 0.7:
                    concept_id = attempt.get("conceptId")
                    weak.append({
                        "concept": self._concept_title(owner, session, concept_id) or "this concept",
                        "conceptId": concept_id,
                        "feedback": (attempt.get("feedback") or "")[:800],
                    })
            if not weak:
                problem("nothing_to_review", "Those attempts show no gaps to review.", 422)
            created_from = f"quiz:{sid}:{hashlib.sha256(json.dumps(sorted(a['conceptId'] or '' for a in weak)).encode()).hexdigest()[:12]}"
            context = {"weak": weak}
        elif command.origin == "insight":
            text_value = (command.source_text or "").strip()
            if not text_value:
                problem("source_required", "Choose the insight to save first.", 422)
            created_from = "insight:" + hashlib.sha256(text_value.encode("utf-8")).hexdigest()[:12]
            concept_title = None
            context = {"insight": text_value[:4000],
                       "label": (command.source_label or "Side exploration").strip() or "Side exploration"}
        else:
            journey = JourneyService(self.store, provider).get(owner, sid)
            turns = [t for t in journey.get("turns", []) if t.get("lesson")]
            if not turns:
                problem("turn_required", "Chat first, then synthesize a note section.", 422)
            index = command.turn_index if command.turn_index is not None and command.turn_index < len(turns) else len(turns) - 1
            turn = turns[index]
            question, lesson_text, concept_id, lesson_id = self._turn_text(turn)
            created_from = f"turn:{lesson_id or index}"
            concept_title = self._concept_title(owner, session, concept_id)
            visual_refs = [
                {"lessonId": lesson_id, "visualizationId": visual.get("id"), "title": visual.get("title")}
                for block in turn.get("lesson", {}).get("blocks", [])
                for visual in block.get("visualizations", [])
                if isinstance(visual, dict) and visual.get("id")
            ][:3]
            context = {"question": question, "lesson": lesson_text, "conceptId": concept_id,
                       "conceptTitle": concept_title, "visualRefs": visual_refs}
        if self._tombstoned(owner, note.id, created_from):
            return {"skipped": "tombstoned", "sessionId": sid, "noteId": note.id}
        mode = self.tutor_updates_mode(note)
        if mode == "never":
            return {"skipped": "tutor_updates_never", "sessionId": sid, "noteId": note.id}
        # Tutoring turns always write into the Notes Lesson. "ask" is only for
        # optional insight prompts — not the primary Learn pipeline.
        if command.origin == "turn" and mode == "ask":
            mode = "auto"
        existing_rows = [row for row in self._provenance_rows(owner, note.id) if not row["tombstoned"]]
        existing_sections = []
        for row in existing_rows:
            located = _find_section(note.body, row["heading"])
            excerpt = ""
            if located is not None:
                excerpt = note.body[located[0]:located[1]].strip()[:500]
            existing_sections.append({
                "sectionId": row["section_id"],
                "heading": row["heading"],
                "ownerKind": row["owner_kind"],
                "excerpt": excerpt,
            })
        existing_headings = [row["heading"] for row in existing_rows]
        if command.origin == "quiz":
            lines = "\n".join(f"- {item['concept']}: {(item['feedback'] or 'review the underlying idea')}" for item in context["weak"])
            prompt = (
                "Write a short review checklist for a learner's study note. Return JSON only: "
                '{"action": "add", "heading": "To review", "body": "markdown checklist"}. Keep the body under 400 words, '
                "one line per gap, no scores, no chat transcript.\n"
                + json.dumps({"gaps": context["weak"], "checklistDraft": lines}, ensure_ascii=False)
            )
        elif command.origin == "insight":
            prompt = (
                "Distill one useful insight from this side exploration into a study-note section. Return JSON only: "
                '{"action": "add"|"refine"|"skip", "heading": "short section title", '
                '"match_heading": "existing heading when refining or null", '
                '"body": "concise markdown (under 250 words)"}. '
                "Prefer refine when an existing section covers the same idea. "
                "Skip chatter with no durable knowledge. Never include chat transcript or questions asked. "
                "Write timeless reference prose.\n"
                + json.dumps({"exploration": context["label"], "content": context["insight"],
                              "existingSections": existing_sections}, ensure_ascii=False)
            )
        else:
            prompt = (
                "You maintain a living Lesson study document for one Learn session. "
                "Decide whether this tutoring turn adds durable knowledge worth keeping. Return JSON only: "
                '{"action": "add"|"refine"|"skip", "heading": "short section title", '
                '"match_heading": "exact existing heading when refining, else null", '
                '"body": "concise markdown (under 350 words)", "concept_title": "concept name or null"}. '
                "Rules: never copy the chat transcript or learner questions; write timeless reference prose; "
                "skip greetings, logistics, and shallow restatements; "
                "when the turn deepens an existing section, set action=refine and match_heading to that section; "
                "when refining, rewrite the full section body so it absorbs the new depth without duplication; "
                "only use action=add for a genuinely new topic; avoid redundant near-duplicate headings.\n"
                + json.dumps({"question": context["question"], "lesson": context["lesson"],
                              "existingSections": existing_sections,
                              "existingHeadings": existing_headings}, ensure_ascii=False)
            )
        from .json_context_prompt import bounded_json_prompt
        instructions, serialized_context = prompt.rsplit("\n", 1)
        context_payload = json.loads(serialized_context)
        required = {"gaps", "checklistDraft"} if command.origin == "quiz" else (
            {"exploration", "content"} if command.origin == "insight" else {"question", "lesson"})
        prompt = bounded_json_prompt(provider, instructions, context_payload, required=required)
        raw = provider.complete_json(prompt, 1500)
        action = str(raw.get("action", "add")).strip().lower()
        if action not in {"add", "refine", "skip"}:
            action = "add"
        if action == "skip":
            return {"skipped": "no_durable_content", "sessionId": sid, "noteId": note.id}
        heading = str(raw.get("heading", "")).strip()[:300]
        body = str(raw.get("body", "")).strip()[:12000]
        if not heading or not body:
            raise ModelProviderError("The synthesis did not produce a usable note section.")
        if command.origin == "turn" and context.get("visualRefs"):
            for visual_ref in context["visualRefs"]:
                body += "\n\n```visualization-ref\n" + json.dumps(visual_ref, ensure_ascii=False) + "\n```"
        concept_title = context.get("conceptTitle") or (str(raw.get("concept_title", "")).strip() or None)
        graph_concept_id = context.get("conceptId")
        learner_concept_id = self.resolve_learner_concept(owner, graph_concept_id)
        section_id = command.section_id
        match_heading = str(raw.get("match_heading") or "").strip()
        if section_id is None and (action == "refine" or match_heading or heading):
            section_id = self._match_tutor_section(existing_rows, match_heading or heading)
            if section_id is not None and match_heading:
                # Keep the learner-facing heading stable when refining.
                for row in existing_rows:
                    if row["section_id"] == section_id:
                        heading = row["heading"]
                        break
            elif action == "refine" and section_id is None:
                # Model asked to refine but nothing matched — fall back to add.
                action = "add"
        proposal = NoteProposal(
            id=uid("noteprop"), session_id=sid, note_id=note.id, origin=command.origin,
            heading=heading, body=body, section_id=section_id,
            concept_title=concept_title, graph_concept_id=graph_concept_id,
            learner_concept_id=learner_concept_id,
            source={"createdFrom": created_from, "question": context.get("question"),
                    "lessonId": lesson_id or None, "label": context.get("label"),
                    "attemptIds": command.attempt_ids, "turnIndex": command.turn_index,
                    "expectedNoteRevision": command.expected_note_revision,
                    "applyKind": "refined" if section_id else "added"},
        )
        return {"proposal": proposal, "sessionId": sid, "noteId": note.id,
                "mode": mode, "createdFrom": created_from}

    def commit(self, conn, owner, prepared):
        if prepared.get("skipped"):
            return {"sessionId": prepared["sessionId"], "noteId": prepared.get("noteId"),
                    "skipped": prepared["skipped"], "status": "skipped"}
        proposal: NoteProposal = prepared["proposal"]
        created_from = proposal.source.get("createdFrom", "")
        apply_kind = "refined" if proposal.section_id else "added"
        # Collapse only open duplicates (e.g. job retries): an applied record
        # must not block refresh proposals, or tombstone/shared flows break.
        # Body duplication on retry is prevented by the idempotency guard in
        # _apply_in instead.
        for record in self.list_proposals(owner, proposal.session_id):
            if record.get("source", {}).get("createdFrom") == created_from and record.get("status") == "proposed":
                return {"proposalId": record["id"], "status": record["status"],
                        "noteId": record.get("note_id") or proposal.note_id,
                        "heading": record.get("heading") or proposal.heading,
                        "applyKind": apply_kind}
        if prepared.get("mode") == "auto":
            # Revision gate: the client saw this note revision when requesting
            # synthesis. If the learner edited since, stay proposed instead of
            # auto-applying over fresh writing. Server revision conflicts remain
            # the ultimate safety net inside _apply_in.
            try:
                applied = self._apply_in(owner, proposal,
                                         expected_note_revision=proposal.source.get("expectedNoteRevision"))
            except (HTTPException, WorkspaceNoteError) as exc:
                if exc.status_code != 409:
                    raise
                applied = None
            if applied is not None:
                self.records.put(conn, owner, PROPOSAL_KIND,
                                 proposal.model_copy(update={"status": "applied"}).model_dump(mode="json"),
                                 proposal.session_id)
                try:
                    from .review.concept_sync import ConceptSyncService
                    session = MaterialService(self.store).session(owner, proposal.session_id)
                    ConceptSyncService(self.store, self.provider).sync_from_text(
                        owner,
                        source_key=f"note_section:{applied['noteId']}:{applied['sectionId']}",
                        text_value=f"{proposal.heading}\n\n{proposal.body}"[:8000],
                        graph_id=session.graph_id,
                        graph_version=session.graph_revision or 1,
                        source_session_id=proposal.session_id,
                        source_section_id=applied.get("sectionId"),
                        parent_concept_id=proposal.graph_concept_id,
                    )
                except Exception:
                    pass
                return {"proposalId": proposal.id, "status": "applied", "noteId": proposal.note_id,
                        "heading": proposal.heading, "applyKind": applied.get("applyKind", apply_kind),
                        "sectionId": applied.get("sectionId")}
        self.records.put(conn, owner, PROPOSAL_KIND, proposal.model_dump(mode="json"), proposal.session_id)
        return {"proposalId": proposal.id, "status": "proposed", "noteId": proposal.note_id,
                "heading": proposal.heading, "applyKind": apply_kind}

    # -- application ---------------------------------------------------------------

    def _apply_in(self, owner, proposal: NoteProposal, body_override: str | None = None,
                  heading_override: str | None = None, expected_note_revision: int | None = None) -> dict | None:
        """Append (or refresh a tutor-owned section). Returns None when blocked.

        Blocked cases stay as proposals: tombstoned content, or a section the
        learner has edited since (hash mismatch flips it to shared).

        NOTE: every store access here runs in its own short transaction.
        WorkspaceNoteService manages its own transactions internally, so sharing
        one outer transaction across note-file and provenance writes deadlocks
        SQLite's pooled connections. Callers keep proposal-status writes atomic
        in their own transaction instead.
        """
        note = self.notes.get(owner, proposal.note_id)
        created_from = proposal.source.get("createdFrom", "")
        if self._tombstoned(owner, note.id, created_from):
            return None
        body = (body_override or proposal.body).strip()
        heading = (heading_override or proposal.heading).strip()
        if not body or not heading:
            return None
        prior = [row for row in self._provenance_rows(owner, note.id)
                 if row["created_from"] == created_from and not row["tombstoned"]]
        with self.store.transaction() as conn:
            if prior and _find_section(note.body, prior[0]["heading"]) is None and proposal.section_id is None:
                self._record_section(conn, owner, note.id, uid("sec"), prior[0]["heading"], "tutor",
                                     created_from, note.revision,
                                     prior[0]["content_hash"], tombstoned=True)
                return None
            if proposal.section_id:
                rows = [row for row in self._provenance_rows(owner, note.id, conn)
                        if row["section_id"] == proposal.section_id and not row["tombstoned"]]
                if not rows:
                    return None
                current = rows[0]
                if current["owner_kind"] != "tutor":
                    return None
                located = _find_section(note.body, current["heading"])
                if located is None:
                    self._record_section(conn, owner, note.id, current["section_id"], current["heading"], "tutor",
                                         current["created_from"], note.revision, current["content_hash"], tombstoned=True)
                    return None
                start, end = located
                live_slice = note.body[start:end]
                if not _hashes_match(current["content_hash"], live_slice, _section_body_from_slice(live_slice)):
                    self._record_section(conn, owner, note.id, current["section_id"], current["heading"], "shared",
                                         current["created_from"], note.revision, _content_hash(live_slice),
                                         current["concept_title"], current["graph_concept_id"], current["learner_concept_id"])
                    return None
                new_body = note.body[:start] + f"## {heading}\n\n{body}\n" + note.body[end:]
                section_id = current["section_id"]
                owner_kind = "tutor"
                apply_kind = "refined"
            else:
                # Idempotent retry: the exact block is already present.
                if f"## {heading}\n\n{body}" in note.body and prior:
                    current = prior[0]
                    self._record_section(conn, owner, note.id, current["section_id"], current["heading"], "tutor",
                                         created_from, note.revision, _section_record_hash(heading, body),
                                         proposal.concept_title, proposal.graph_concept_id, proposal.learner_concept_id)
                    return {"noteId": note.id, "revision": note.revision, "sectionId": current["section_id"],
                            "applyKind": "added"}
                new_body = note.body + _section_markdown(heading, body)
                section_id = uid("sec")
                owner_kind = "tutor"
                apply_kind = "added"
        update_revision = expected_note_revision if expected_note_revision is not None else note.revision
        updated = self.notes.update(
            owner, note.id,
            WorkspaceNoteUpdate(expected_revision=update_revision, body=new_body),
        )
        with self.store.transaction() as conn:
            self._record_section(conn, owner, note.id, section_id, heading, owner_kind,
                                 created_from, updated.revision, _section_record_hash(heading, body),
                                 proposal.concept_title, proposal.graph_concept_id, proposal.learner_concept_id)
        return {"noteId": updated.id, "revision": updated.revision, "sectionId": section_id, "applyKind": apply_kind}

    # -- proposal lifecycle (synchronous routes) --------------------------------------

    def list_proposals(self, owner, sid, status: str | None = None) -> list[dict]:
        items = []
        for record in self.records.listing(owner, PROPOSAL_KIND):
            if record.get("session_id") != sid:
                continue
            if status and record.get("status") != status:
                continue
            items.append(record)
        return items

    def get_proposal(self, owner, proposal_id) -> dict:
        return self.records.read(owner, proposal_id, PROPOSAL_KIND)

    def accept(self, owner, proposal_id, body=None, heading=None, expected_revision=None) -> dict:
        record = self.records.read(owner, proposal_id, PROPOSAL_KIND)
        if record.get("status") != "proposed":
            problem("proposal_closed", "This proposal was already handled.", 409)
        proposal = NoteProposal.model_validate({**record, "id": record["id"], "revision": record["revision"]})
        with self.store.transaction() as conn:
            applied = self._apply_in(owner, proposal, body, heading, expected_revision)
            if applied is None:
                problem("section_blocked", "The note changed or this content was removed. The proposal stays open.", 409)
            self.records.put(conn, owner, PROPOSAL_KIND,
                             proposal.model_copy(update={"status": "applied"}).model_dump(mode="json"),
                             proposal.session_id, expected=proposal.revision)
        return {"proposalId": proposal.id, "status": "applied", **applied}

    def reject(self, owner, proposal_id) -> dict:
        record = self.records.read(owner, proposal_id, PROPOSAL_KIND)
        if record.get("status") != "proposed":
            problem("proposal_closed", "This proposal was already handled.", 409)
        proposal = NoteProposal.model_validate({**record, "id": record["id"], "revision": record["revision"]})
        with self.store.transaction() as conn:
            self.records.put(conn, owner, PROPOSAL_KIND,
                             proposal.model_copy(update={"status": "rejected"}).model_dump(mode="json"),
                             proposal.session_id, expected=proposal.revision)
        return {"proposalId": proposal.id, "status": "rejected"}
