"""Bounded keyset pages for current user-visible class outputs."""
from __future__ import annotations

import json

from fastapi import HTTPException
from sqlalchemy import bindparam, text

PAGE_SIZE = 100
CANDIDATE_PAGE_SIZE = 250
MAX_CANDIDATE_PAGES = 8
VISIBLE_KINDS = {"notes", "materials", "practice", "flashcards", "summary", "recall", "revision_quiz"}


def page_active_outputs(conn, *, owner, class_id, active_window_set_ids, package_window=None, generation, cursor=None):
    """Read at most 100 current outputs, scanning at most 2,000 candidate rows.

    Output rows are immutable in identity and ordered by creation time plus ID.
    Retired-window and internal synthesis rows are skipped. A generation fence
    makes a page cursor stale after transcript rebuilds replace active windows.
    """
    active_window_set_ids = list(dict.fromkeys(set_id for set_id in active_window_set_ids if set_id))
    position = None
    if cursor:
        try:
            cursor_generation, created_at, output_id = cursor.split(":", 2)
            if int(cursor_generation) != generation or not output_id:
                raise ValueError()
            position = (float(created_at), output_id)
        except (TypeError, ValueError):
            raise HTTPException(409, {
                "code": "output_cursor_stale",
                "message": "Class results changed. Refresh the class results and try again.",
            }) from None

    items = []
    scanned = None
    has_more = False
    for _ in range(MAX_CANDIDATE_PAGES):
        params = {"owner": owner, "class": class_id, "limit": CANDIDATE_PAGE_SIZE + 1}
        where_cursor = ""
        if position:
            where_cursor = " AND (created_at<:created OR (created_at=:created AND id<:output_id))"
            params.update(created=position[0], output_id=position[1])
        rows = conn.execute(text("""SELECT id,revision,payload,created_at
            FROM class_output_versions
            WHERE owner_id=:owner AND class_id=:class""" + where_cursor + " ORDER BY created_at DESC,id DESC LIMIT :limit"), params).mappings().all()
        if not rows:
            has_more = False
            break
        batch = rows[:CANDIDATE_PAGE_SIZE]
        more_in_database = len(rows) > CANDIDATE_PAGE_SIZE
        window_ids=list(dict.fromkeys(json.loads(row['payload']).get('windowId') for row in batch if json.loads(row['payload']).get('windowId')))
        active_windows=set()
        if active_window_set_ids and window_ids:
            active_windows=set(conn.execute(text('''SELECT DISTINCT window_id FROM class_session_window_membership
                WHERE owner_id=:owner AND class_id=:class AND set_id IN :sets AND window_id IN :windows''').bindparams(
                    bindparam('sets',expanding=True),bindparam('windows',expanding=True)),{
                'owner':owner,'class':class_id,'sets':active_window_set_ids,'windows':window_ids,
            }).scalars())
        for index, row in enumerate(batch):
            scanned = (float(row["created_at"]), row["id"])
            output = json.loads(row["payload"])
            if (output.get("windowId") not in active_windows and output.get("windowId")!=package_window) or output.get("kind") not in VISIBLE_KINDS:
                continue
            # Synthesis leaves and merge nodes are implementation details. Only
            # the completed root package belongs in the learner's results.
            if output.get("kind") in {"summary", "recall"} and output.get("windowId") != package_window:
                continue
            items.append({**output, "revision": row["revision"]})
            if len(items) == PAGE_SIZE:
                has_more = index < len(batch) - 1 or more_in_database
                break
        if len(items) == PAGE_SIZE:
            break
        if not more_in_database:
            has_more = False
            break
        position = scanned
        has_more = True

    if not scanned:
        return {"items": [], "hasMore": False, "nextCursor": None, "generation": generation}
    next_cursor = f"{generation}:{scanned[0]}:{scanned[1]}" if has_more else None
    return {"items": items, "hasMore": has_more, "nextCursor": next_cursor, "generation": generation}
