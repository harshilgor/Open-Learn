"""Typed, bounded adapters to existing domain services. No arbitrary execution."""
from typing import Literal
from pydantic import Field
from .contracts import Contract
from ..identity import fail
from ..material_service import MaterialService
from ..workflow_store import WorkflowStore
from ..calendar.contracts import Availability as CalendarAvailability, Proposal as CalendarProposal


class CalendarRange(Contract):
    start: str
    end: str
    calendarIds: list[str] = Field(default_factory=list, max_length=30)


class CalendarApply(Contract):
    proposalId: str = Field(min_length=1, max_length=160)


class Explain(Contract):
    request: str = Field(min_length=1, max_length=4000)


class Quiz(Contract):
    topic: str = Field(min_length=1, max_length=500)
    count: int = Field(default=5, ge=1, le=10)

class ReviseQuestion(Contract):
    question_number:int=Field(ge=1,le=10)
    difficulty:Literal['foundational','standard','stretch']


class Answer(Contract):
    response: str = Field(min_length=1, max_length=4000)
    selected_ids: list[str] = Field(default_factory=list, max_length=8)


class Empty(Contract):
    pass

class WorkspaceFocus(Contract):
    focused: bool = True


class Reminder(Contract):
    when: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=2000)


class ReminderTarget(Contract):
    reminder_id: str = Field(min_length=1, max_length=160)


class ReminderMove(ReminderTarget):
    minutes: int = Field(ge=1, le=10080)


class ReminderReschedule(ReminderTarget):
    when: str = Field(min_length=1, max_length=200)


class Search(Contract):
    query: str = Field(min_length=1, max_length=200)


class Open(Contract):
    kind: Literal['note', 'quiz', 'source']
    target_id: str = Field(min_length=1, max_length=160)


class VisualUpdate(Contract):
    parameter_id: str = Field(min_length=1, max_length=64)
    value: float = Field(ge=-10000, le=10000, allow_inf_nan=False)


REGISTRY = {
    'calendar_read': (CalendarRange, 'Read a bounded schedule only from calendars the learner allowed Buddy to read. Busy-only content is redacted.'),
    'calendar_availability': (CalendarAvailability, 'Find available study time; incomplete calendars cannot establish availability. This never creates events.'),
    'calendar_propose': (CalendarProposal, 'Propose exact calendar changes for a visible approval card. The model cannot grant permission. Ask if scope or dates are unclear.'),
    'calendar_apply': (CalendarApply, 'Apply a known proposal only using saved calendar edit permission; otherwise the learner must approve on screen.'),
    'note_propose_edit': (Explain, 'Propose a reviewable edit to the selected saved note passage; never overwrite it automatically.'),
    'quiz_revise_question': (ReviseQuestion, 'Change the difficulty of a specific upcoming or unanswered question in the focused quiz; preserve answered questions.'),
    'workspace_focus': (WorkspaceFocus, 'Expand the current study workspace for focus, or restore the split view.'),
    'side_chat_open': (Empty, 'Open a separate side conversation about the selected note passage. Do not answer until the learner asks.'),
    'tutor_explain': (Explain, 'Teach or explain using the existing grounded tutor. Use for factual answers.'),
    'quiz_create': (Quiz, 'Create a quiz on the stated topic and show it.'),
    'quiz_answer': (Answer, 'Submit the final answer to the current quiz question; only when a quiz is focused.'),
    'quiz_hint': (Empty, 'Request a hint on the current quiz question.'),
    'quiz_next': (Empty, 'Advance the focused quiz to its next question.'),
    'visual_create': (Explain, 'Create an educational diagram through the existing lesson planner.'),
    'visual_update': (VisualUpdate, 'Change a supported numeric parameter on the focused visualization.'),
    'note_create': (Empty, 'Create a note draft from the focused lesson.'),
    'flashcards_create': (Empty, 'Create flashcards from the focused saved note.'),
    'reminder_create': (Reminder, 'Schedule a reminder. Clarify ambiguous times; never guess AM/PM.'),
    'reminder_list': (Empty, 'Show the learner their upcoming reminders.'),
    'reminder_cancel': (ReminderTarget, 'Cancel a reminder after visible confirmation.'),
    'reminder_snooze': (ReminderMove, 'Move a reminder by a stated number of minutes.'),
    'reminder_reschedule': (ReminderReschedule, 'Move a one-time reminder to an exact future time; clarify ambiguous AM/PM.'),
    'context_search': (Search, 'Search the learner owned notes for relevant content.'),
    'workspace_open': (Open, 'Open a known owned resource in the workspace.'),
    'session_summarize': (Empty, 'Show a transcript summary draft; never mark mastery.'),
    'study_recommend': (Empty, 'Recommend what to revise using the existing learning recommendations.'),
}


def schemas():
    return [{'type': 'function', 'function': {'name': name, 'description': description, 'parameters': model.model_json_schema()}} for name, (model, description) in REGISTRY.items()]


class Tools:
    def __init__(self, store, provider):
        self.store, self.provider = store, provider

    def validate_focus(self, owner, focus):
        from ..workspace_note_service import WorkspaceNoteService
        if focus.get('source_span_id'):
            MaterialService(self.store).source(owner,focus['source_span_id'])
        if focus.get('note_id'):
            WorkspaceNoteService(self.store).get(owner, focus['note_id'])
        if focus.get('quiz_id'):
            self.quiz(owner, focus)
        if focus.get('lesson_id'):
            artifact = self.store.get_artifact(focus['lesson_id'])
            if not artifact:
                fail('not_found', 'Lesson unavailable.', 404)
            MaterialService(self.store).session(owner, artifact.session_id)

    def quiz(self, owner, focus):
        from ..quiz_service import QuizService
        if not focus.get('quiz_id'):
            fail('voice_focus_required', 'Open a quiz first.', 422)
        return QuizService(self.store, self.provider).public(owner, focus['quiz_id'])

    def visual_context(self, owner, focus):
        if not focus.get('lesson_id') or not focus.get('visualization_id'):
            return None
        artifact = self.store.get_artifact(focus['lesson_id'])
        if not artifact:
            return None
        MaterialService(self.store).session(owner, artifact.session_id)
        value = next((value for block in artifact.blocks for value in block.visualizations
                      if value.get('id') == focus['visualization_id']), None)
        if not value:
            fail('not_found', 'The focused visual is unavailable.', 404)
        if value.get('type') == 'generated_ui_ref':
            record = WorkflowStore(self.store).read(owner, value['id'], 'generated_visual')
            value = record['spec']
            controls = [{**control, 'current':value.get('controlValues', {}).get(control['id'], control['initial'])}
                        for control in value.get('controls', [])]
        else:
            controls = value.get('parameters', [])
        return {'id': value['id'], 'title': value['title'], 'revision': value.get('revision', 1), 'controls': controls,
                'editable': bool(controls)}

    def execute(self, owner, session, name, raw, key):
        if name not in REGISTRY:
            fail('voice_tool_denied', 'That tool is unavailable.', 422)
        args = REGISTRY[name][0].model_validate(raw)
        sid, context = session['chat_id'], session['context']
        focus = context['focus']
        MaterialService(self.store).session(owner, sid)
        self.validate_focus(owner, focus)
        records = WorkflowStore(self.store)
        if name.startswith('calendar_'):
            from ..calendar.service import CalendarService
            from ..calendar.contracts import Decision
            from fastapi import HTTPException
            service = CalendarService(self.store)
            if name == 'calendar_read':
                result = service.occurrences(owner, args.start, args.end, context['timezone'], args.calendarIds or None, agent=True)
                return {'status':'succeeded','result':result,'userMessage':'Schedule checked using your calendar permissions.','uiIntent':{'action':'open_calendar'}}
            if name == 'calendar_availability':
                return {'status':'succeeded','result':service.availability(owner,args,agent=True),'userMessage':'Availability checked. Only complete schedule data can confirm free time.','uiIntent':{'action':'open_calendar'}}
            if name == 'calendar_propose':
                result = service.propose(owner, args.model_copy(update={'sessionId':sid}), key)
                return {'status':'succeeded','result':result,'userMessage':'Review the proposed calendar change on screen. You can allow this change once or save permission for future ordinary edits.'}
            with service.transaction(owner) as conn:
                proposal = service.read(conn,owner,'proposals',args.proposalId)
                if proposal.get('sessionId') != sid: fail('not_found','Calendar proposal unavailable in this conversation.',404)
            try:
                result = service.decide(owner,args.proposalId,Decision(expectedRevision=proposal['revision'],proposalHash=proposal['proposalHash'],decision='allow'),key,unattended=True)
                return {'status':'succeeded','result':result,'userMessage':'Calendar change applied.' if result['status']=='applied' else 'Calendar change is waiting for Google confirmation.','uiIntent':{'action':'open_calendar'}}
            except HTTPException as cause:
                if cause.detail.get('code') != 'approval_required': raise
                return {'status':'succeeded','result':proposal,'userMessage':'Please approve this calendar change on the visible calendar card.'}
        if name=='quiz_revise_question':
            from ..quiz_service import QuizService
            quiz=self.quiz(owner,focus)
            result=QuizService(self.store,self.provider).revise_question(owner,quiz['id'],args.question_number,args.difficulty,focus.get('expected_revision'),key)
            return {'status':'queued' if result.get('jobId') else 'succeeded','jobId':result.get('jobId'),'jobKind':'next','result':result,'userMessage':'Question difficulty updated in this quiz.','uiIntent':{'action':'refresh_quiz','targetId':quiz['id']}}
        if name == 'workspace_focus':
            return {'status':'succeeded','userMessage':'Workspace view updated.','uiIntent':{'action':'focus_workspace' if args.focused else 'restore_workspace'}}
        if name == 'side_chat_open':
            from ..workspace_note_service import WorkspaceNoteService
            if not focus.get('note_id') or focus.get('selection_start') is None or focus.get('selection_end') is None:
                fail('selection_required','Select a note passage to discuss separately.',422)
            note = WorkspaceNoteService(self.store).get(owner,focus['note_id'])
            start,end = focus['selection_start'],focus['selection_end']
            if note.revision != focus.get('expected_revision') or not 0 <= start < end <= len(note.body) or end-start > 6000:
                fail('selection_changed','The selected note changed. Select it again.',409)
            return {'status':'succeeded','userMessage':'Side conversation opened.','result':{'title':note.title,'excerpt':note.body[start:end],'note':{'noteId':note.id,'expectedRevision':note.revision,'startOffset':start,'endOffset':end}},'uiIntent':{'action':'open_side_chat'}}

        def enqueue(target, kind, payload, message):
            job = records.enqueue(owner, target, kind, payload, key)
            return {'status': 'queued', 'jobId': job['id'], 'jobKind': kind, 'userMessage': message}

        if name=='note_propose_edit':
            from ..note_draft_models import CreateNoteDraft
            if not focus.get('note_id') or focus.get('selection_start') is None or focus.get('selection_end') is None:
                fail('selection_required','Select the note passage you want to revise.',422)
            selection={'noteId':focus['note_id'],'expectedRevision':focus.get('expected_revision'),'startOffset':focus['selection_start'],'endOffset':focus['selection_end']}
            command=CreateNoteDraft(origin_kind='mentioned_notes',note_context={'notes':[selection]},replacement=selection,edit_request=args.request[:1000])
            return enqueue(sid,'note_draft',command.model_dump(mode='json'),'Preparing suggested changes for your review.')

        if name == 'quiz_create':
            from ..assessment_models import QuizCreate
            command = QuizCreate(session_id=sid, requested_topic=args.topic, count=args.count)
            return enqueue(sid, 'create', command.model_dump(), 'Creating your quiz.')
        if name in {'quiz_answer', 'quiz_next', 'quiz_hint'}:
            from ..assessment_models import AnswerCommand
            quiz = self.quiz(owner, focus)
            expected = focus.get('expected_revision')
            if expected != quiz['revision']:
                fail('revision_conflict', 'The quiz changed. Look at the current question and try again.', 409)
            if name == 'quiz_next':
                return enqueue(quiz['id'], 'next', {'expected_revision': expected}, 'Loading the next question.')
            current = quiz.get('current')
            if not current or focus.get('presentation_id') != current['id']:
                fail('revision_conflict', 'The question changed. Please answer the current question.', 409)
            if name == 'quiz_hint':
                return enqueue(current['id'], 'hint', {}, 'Getting a hint.')
            # The planner may identify intent, but cannot invent the student's answer.
            response = context.get('utterance') or args.response
            selected = [] if context.get('utterance') else args.selected_ids
            options = current.get('options', [])
            if options and not selected:
                import re
                matches = re.findall(r'\b([a-f])\b', response.lower())
                if len(matches) == 1 and ord(matches[0])-ord('a') < len(options):
                    selected = [options[ord(matches[0])-ord('a')]['id']]
                else:
                    selected = [option['id'] for option in options if option['label'].strip().casefold() == response.strip().casefold()]
            if options and (not selected or any(value not in {option['id'] for option in options} for value in selected)):
                fail('voice_answer_unclear', 'Please say the option letter clearly, or choose it on screen.', 422)
            command = AnswerCommand(presentation_id=current['id'], expected_revision=expected, response=response, selected_ids=selected)
            return enqueue(quiz['id'], 'answer', command.model_dump(), 'Checking your answer.')
        if name in {'tutor_explain', 'visual_create'}:
            from ..assessment_models import JourneyCommand
            from ..journey_service import JourneyService
            journey = JourneyService(self.store, self.provider).get(owner, sid)
            request = args.request if name == 'tutor_explain' else 'Create an educational diagram and explain it: ' + args.request
            note_context = None
            if focus.get('note_id') and focus.get('selection_start') is not None and focus.get('selection_end') is not None:
                if focus['selection_start'] >= focus['selection_end'] or not focus.get('expected_revision'):
                    fail('invalid_selection', 'Select the passage again before asking.', 422)
                note_context = {'notes':[{'noteId':focus['note_id'],'expectedRevision':focus['expected_revision'],'startOffset':focus['selection_start'],'endOffset':focus['selection_end']}]}
            command = JourneyCommand(mode='ask', message=request, expected_revision=journey.get('revision', 1), note_context=note_context, selected_text=focus.get('selected_text'), selected_span_ids=[focus['source_span_id']] if focus.get('source_span_id') else [])
            return enqueue(sid, 'voice_teach', {'command': command.model_dump(mode='json'), 'visual': name == 'visual_create'}, 'Preparing an explanation.' if name == 'tutor_explain' else 'Preparing your diagram.')
        if name == 'visual_update':
            from ..visualization_service import VisualChange, VisualizationService
            if not all(focus.get(k) for k in ('lesson_id', 'visualization_id', 'expected_revision')):
                fail('voice_focus_required', 'Select a visualization first.', 422)
            result = VisualizationService(self.store).change(owner, focus['lesson_id'], focus['visualization_id'], VisualChange(operation='change_parameter', expected_revision=focus['expected_revision'], parameter_id=args.parameter_id, value=args.value))
            return {'status': 'succeeded', 'artifactRef': {'kind': 'visualization', 'id': result.id}, 'userMessage': 'Updated the diagram.', 'uiIntent': {'action': 'refresh', 'targetId': result.id}}
        if name == 'note_create':
            from ..workspace_note_models import WorkspaceNoteCreate
            from ..workspace_note_service import WorkspaceNoteService
            if not focus.get('lesson_id'):
                fail('voice_focus_required', 'Select the explanation you want to save.', 422)
            artifact = self.store.get_artifact(focus['lesson_id'])
            note = WorkspaceNoteService(self.store).create(owner, WorkspaceNoteCreate(title=artifact.title, body='\n\n'.join(block.body for block in artifact.blocks), frontmatter={'session_id': sid, 'lesson_id': artifact.id, 'source': 'voice_saved_lesson', 'generated': True}), command_id=key)
            return {'status': 'succeeded', 'artifactRef': {'kind': 'note', 'id': note.id}, 'userMessage': 'Saved your explanation as a note.', 'uiIntent': {'action': 'open_note', 'targetId': note.id}}
        if name == 'flashcards_create':
            from ..flashcards.contracts import FlashcardRequest
            from ..agent_execution.coordinator import Coordinator
            from ..agent_execution.contracts import Message
            from ..workspace_note_service import WorkspaceNoteService
            if not focus.get('note_id'):
                fail('voice_focus_required', 'Open the saved note to use for flashcards.', 422)
            note = WorkspaceNoteService(self.store).get(owner, focus['note_id'])
            command = FlashcardRequest(sessionId=sid, sourceRefs=[{'kind': 'note', 'id': note.id, 'revision': note.revision}], clientCommandId=key)
            task = Coordinator(self.store).admit(owner, Message(clientMessageId=key, sessionId=sid, text=command.objective, capability='flashcards', flashcardSpec=command), key)
            return {'status': 'queued', 'task': task, 'taskId': task.get('run', task).get('id'), 'userMessage': 'Creating flashcards. Track them in your study tasks.'}
        if name.startswith('reminder_'):
            from ..reminder_service import ReminderCreate, ReminderService
            service = ReminderService(self.store)
            if name == 'reminder_list':
                rows = service.listing(owner, 'pending')['reminders']
                rows = sorted(rows, key=lambda item: item['dueAt'])[:12]
                return {'status': 'succeeded', 'result': {'reminders': rows}, 'userMessage': f"You have {len(rows)} upcoming reminder{'s' if len(rows) != 1 else ''}.", 'uiIntent': {'action': 'open_reminders'}}
            if name == 'reminder_create':
                prefs = service.preferences(owner)
                result = service.create(owner, ReminderCreate(when=args.when, message=args.message, timezone=context['timezone'], sessionId=sid, channels=prefs['channels']), key)
                return {'status': 'succeeded', 'artifactRef': {'kind': 'reminder', 'id': result['id']}, 'result': result, 'userMessage': 'Reminder scheduled. The exact time and delivery channel are on the receipt.', 'uiIntent': {'action': 'open_reminders', 'targetId': result['id']}}
            if name == 'reminder_reschedule':
                result = service.reschedule(owner, args.reminder_id, args.when, context['timezone'], key)
            else:
                result = service.cancel(owner, args.reminder_id) if name == 'reminder_cancel' else service.snooze(owner, args.reminder_id, args.minutes, key)
            return {'status': 'succeeded', 'result': result, 'userMessage': 'Reminder updated.', 'uiIntent': {'action': 'open_reminders', 'targetId': args.reminder_id}}
        if name == 'context_search':
            from ..workspace_note_service import WorkspaceNoteService
            return {'status': 'succeeded', 'notes': [n.model_dump(mode='json', by_alias=True) for n in WorkspaceNoteService(self.store).search(owner, args.query, 5)], 'userMessage': 'Here are the matching notes.'}
        if name == 'workspace_open':
            from ..workspace_note_service import WorkspaceNoteService
            if args.kind == 'note':
                WorkspaceNoteService(self.store).get(owner, args.target_id)
            elif args.kind == 'quiz':
                self.quiz(owner, {'quiz_id': args.target_id})
            else:
                fail('voice_tool_denied', 'Open source passages from their cited lesson.', 422)
            return {'status': 'succeeded', 'userMessage': 'Opening it.', 'uiIntent': {'action': 'open_'+args.kind, 'targetId': args.target_id}}
        if name == 'session_summarize':
            from .store import VoiceStore
            from ..workspace_note_models import WorkspaceNoteCreate
            from ..workspace_note_service import WorkspaceNoteService
            turns = VoiceStore(self.store).records(owner, session['id'], 'turns')
            actions = VoiceStore(self.store).records(owner, session['id'], 'actions', {'succeeded'})
            body = '# Voice study session\n\n' + '\n\n'.join('You: '+turn['data']['text'] for turn in turns) + '\n\n## Completed work\n\n' + '\n'.join('- '+a['data'].get('result', {}).get('userMessage', a['data'].get('tool', 'Study task')) for a in actions)
            note = WorkspaceNoteService(self.store).create(owner, WorkspaceNoteCreate(title='Voice study session', body=body, frontmatter={'session_id': sid, 'voice_session_id': session['id'], 'source': 'voice_transcript', 'assessed_mastery': False}), command_id=key)
            return {'status': 'succeeded', 'userMessage': 'Saved a session recap with your requests and completed work.', 'artifactRef': {'kind': 'note', 'id': note.id}, 'uiIntent': {'action': 'open_note', 'targetId': note.id}}
        if name == 'study_recommend':
            from ..recommendation_service import RecommendationService
            result = RecommendationService(self.store).get_or_create(owner, sid)
            return {'status': 'succeeded', 'result': result.model_dump(mode='json', by_alias=True) if hasattr(result, 'model_dump') else result, 'userMessage': 'Your study recommendations are ready.', 'uiIntent': {'action': 'refresh_chat'}}
        fail('voice_tool_denied', 'That tool is unavailable.', 422)
