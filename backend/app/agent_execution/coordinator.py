"""Admission and human replies commit once; work is independent of subscribers."""
import json
import time
from sqlalchemy import text
from ..identity import fail
from ..workflow_store import encoded, uid
from .contracts import Command, InputAnswer
from .repository import Repository, TERMINAL, digest
from .config import admission_enabled
from .tools import FIXTURE, parse_csv, constraints_from


class Coordinator:
    def __init__(self, store): self.store=store;self.repo=Repository(store)

    def admit(self, owner, body, key):
        if not key or len(key)>200: fail('invalid_input','Provide a stable Idempotency-Key.',422)
        data=body.model_dump(by_alias=True)
        # Preserve hashes for pre-admission clients whose schema had no routing context.
        for field, default in [('courseId', None), ('previousBrowserTaskId', None), ('presentation','conversation'), ('timezone','America/Los_Angeles')]:
            if data.get(field) == default: data.pop(field, None)
        hash_value=digest(data)
        from .admission import classify_message, plan_message
        can_classify = not body.capability and not body.target_task_id and not body.reply_to_request_id
        # Avoid paying for a repeated semantic decision when a client retries
        # an already committed message. The transaction below repeats this
        # check to close the concurrent-request race.
        if can_classify:
            with self.store.engine.connect() as conn:
                existing = conn.execute(text('SELECT request_hash,response FROM agent_messages WHERE owner_id=:owner AND (client_message_id=:client OR command_key=:key)'),
                    {'owner':owner,'client':body.client_message_id,'key':key}).mappings().first()
            if existing:
                if existing['request_hash'] != hash_value:
                    fail('idempotency_conflict','That message identity has different content.',409)
                return json.loads(existing['response'])
        plan = classify_message(body.text) if can_classify else None
        if plan and body.previous_browser_task_id:
            from ..browser_assistant.intent import followup
            if followup(body.text):
                from .admission import AdmissionPlan
                plan = AdmissionPlan(kind='browser')
        inferred_csv = body.material_version_id or (body.attachments[0].version_id if len(body.attachments) == 1 and body.attachments[0].name.lower().endswith('.csv') else None)
        capability = body.capability or ('research' if plan and plan.kind == 'research' else 'lab_analysis' if plan and plan.kind == 'analysis' and (inferred_csv or body.csv_text) else None)
        with self.repo.transaction() as conn:
            self.repo.session(conn,owner,body.session_id)
            if body.attachments:
                from ..material_service import MaterialService
                for attachment in body.attachments:
                    version = MaterialService(self.store).version(owner, attachment.version_id, conn)
                    if version['role'] in {'answer_key','sample_paper'} and (body.capability or plan and plan.kind != 'direct'): fail('source_scope_denied','Assessment sources cannot enter general agent execution.',403)
                    if not conn.execute(text('SELECT 1 FROM material_attachments WHERE session_id=:session AND version_id=:version'), {'session':body.session_id,'version':attachment.version_id}).first():
                        fail('source_scope_denied','Attach this owned material to the conversation before using it.',403)
            existing=conn.execute(text('SELECT * FROM agent_messages WHERE owner_id=:owner AND (client_message_id=:client OR command_key=:key)'),{'owner':owner,'client':body.client_message_id,'key':key}).mappings().first()
            if existing:
                if existing['request_hash']!=hash_value: fail('idempotency_conflict','That message identity has different content.',409)
                return json.loads(existing['response'])
            if plan and plan.kind == 'flashcards':
                from ..flashcards.contracts import FlashcardRequest
                refs = []
                if body.attachments:
                    from ..material_service import MaterialService
                    refs = [{'kind':'material','id':attachment.version_id,'revision':MaterialService(self.store).version(owner,attachment.version_id,conn)['version']} for attachment in body.attachments]
                else:
                    from ..study_note_service import StudyNoteService
                    note = StudyNoteService(self.store).find_note(owner,body.session_id)
                    if note: refs = [{'kind':'lesson','id':note.id,'revision':note.revision}]
                if refs:
                    body = body.model_copy(update={'flashcard_spec':FlashcardRequest(sessionId=body.session_id,courseId=body.course_id,origin=body.presentation,sourceRefs=refs,objective=body.text[:1000],clientCommandId=body.client_message_id)})
                    capability = 'flashcards'
            identifier=uid('message')
            response={'schemaVersion':2,'messageId':identifier,'admissionId':identifier,'status':'direct','handled':False,'references':[]}
            if body.target_task_id or body.reply_to_request_id:
                if body.reply_to_request_id and (body.expected_request_revision is None or body.expected_revision is None):
                    fail('invalid_input','A reply to a question requires its task and question revisions.',422)
                if body.reply_to_request_id and not body.target_task_id:
                    row=conn.execute(text('SELECT run_id FROM agent_input_requests WHERE id=:id AND owner_id=:owner AND session_id=:session'),{'id':body.reply_to_request_id,'owner':owner,'session':body.session_id}).first()
                    if not row: fail('not_found','Question unavailable.',404)
                    target=row[0]
                else: target=body.target_task_id
                task_row=conn.execute(text('SELECT session_id,runtime_owner,status,revision,payload FROM assistant_runs WHERE id=:id AND owner_id=:owner'),{'id':target,'owner':owner}).mappings().first()
                if not task_row or task_row['session_id']!=body.session_id: fail('not_found','Task unavailable in this conversation.',404)
                runtime_owner=task_row['runtime_owner'] or 'browser_legacy'
                if runtime_owner!='agent_v2':
                    if not body.reply_to_request_id: fail('invalid_input','Continue this website task by replying to its current question.',422)
                    if body.attachments: fail('input_kind_mismatch','Website task questions accept text answers only.',409)
                    from ..browser_assistant.service import AssistantService
                    browser_run=AssistantService(self.store).resolve_conversation_input(
                        conn, owner, target, body.reply_to_request_id, body.expected_revision,
                        body.expected_request_revision, body.text, identifier)
                    response.update(status='accepted',handled=True,runtimeOwner='browser_legacy',
                        references=[{'kind':'task','id':target},{'kind':'input','id':body.reply_to_request_id}],
                        taskRevision=browser_run.get('revision'))
                    command=None
                    run=None
                else:
                    run=self.repo.run(conn,owner,target)
                    if run['sessionId']!=body.session_id: fail('not_found','Task unavailable in this conversation.',404)
                    if body.expected_revision is None: fail('invalid_input','Reply requires the task revision.',422)
                    command=Command(commandId='reply_'+identifier,action='answer_input' if body.reply_to_request_id else 'steer',expectedRevision=body.expected_revision,
                        requestId=body.reply_to_request_id,expectedRequestRevision=body.expected_request_revision,messageId=identifier,
                        text=None if body.reply_to_request_id else body.text,
                        answer=InputAnswer(text=body.text,attachments=body.attachments) if body.reply_to_request_id else None)
                if run and run['status'] in TERMINAL and command.action=='steer':
                    if conn.execute(text('SELECT 1 FROM agent_delegated_children WHERE child_id=:id AND owner_id=:owner'),{'id':run['id'],'owner':owner}).first():fail('delegation_depth_denied','Start a separate user task; bounded children cannot create follow-up children.',403)
                    if not admission_enabled():fail('capability_unavailable','New agent tasks are disabled.',503)
                    if run['status'] not in {'completed','completed_partial'}: fail('invalid_state','Start a new task to change this result.',409)
                    if run['revision']!=command.expected_revision: fail('revision_conflict','Task changed. Refresh before correcting it.',409)
                    if run['kind']=='flashcards':
                        fail('invalid_input','Use Make flashcards with current source revisions to create a corrected deck.',422)
                    elif run['kind']=='research':
                        from .research_contracts import ResearchSpec
                        spec=ResearchSpec.model_validate({**run['researchSpec'],'query':body.text}).model_dump(by_alias=True)
                        child=self.create(conn,owner,body.session_id,body.text,'followup:'+identifier,None,{},parent=run['id'],parent_revision=run['desired_input_revision'],kind='research',research_spec=spec,accepted_usage_cap_micro=body.accepted_usage_cap_micro)
                    elif run['kind']=='calendar_read':
                        from .calendar_tasks import calendar_id_from_text,parse_calendar_window
                        try: bounds=parse_calendar_window(body.text,body.timezone)
                        except ValueError as exc: fail('invalid_input',str(exc),422)
                        spec={'calendarId':calendar_id_from_text(body.text),'timeZone':body.timezone,**(bounds or {})}
                        child=self.create(conn,owner,body.session_id,body.text,'followup:'+identifier,None,{},parent=run['id'],parent_revision=run['desired_input_revision'],kind='calendar_read',calendar_read=spec,accepted_usage_cap_micro=body.accepted_usage_cap_micro)
                    else:
                        if run['kind']=='lab_analysis' and run.get('analysisMode')=='general':
                            from .tools import parse_dataset_csv
                            parse_dataset_csv(run['csvText'])
                            corrected={**run['constraints'],'steering':body.text}
                        else: corrected=constraints_from(body.text,run['constraints'],parse_csv(run['csvText']))
                        child=self.create(conn,owner,body.session_id,body.text,'followup:'+identifier,run['csvText'],corrected,parent=run['id'],parent_revision=run['desired_input_revision'],kind=run['kind'],input_material=run.get('inputMaterial'),accepted_usage_cap_micro=body.accepted_usage_cap_micro,analysis_mode=run.get('analysisMode','lab'))
                    response.update(status='queued',handled=True,references=[{'kind':'task','id':child['id']}])
                elif command:
                    ack=self.apply_command(conn,owner,target,command)
                    response.update(status='accepted',handled=True,references=[{'kind':'task','id':target},{'kind':'command','id':ack['commandId']}])
            elif plan and plan.kind == 'calendar_read':
                if not admission_enabled(): fail('capability_unavailable','New agent tasks are disabled. Existing work remains available.',503)
                from .calendar_tasks import calendar_id_from_text,parse_calendar_window
                try: bounds=parse_calendar_window(body.text,body.timezone)
                except ValueError as exc: fail('invalid_input',str(exc),422)
                spec={'calendarId':calendar_id_from_text(body.text),'timeZone':body.timezone,**(bounds or {})}
                run=self.create(conn,owner,body.session_id,body.text,'message:'+identifier,None,{},kind='calendar_read',calendar_read=spec,accepted_usage_cap_micro=body.accepted_usage_cap_micro)
                response.update(status='queued',handled=True,references=[{'kind':'task','id':run['id']}])
            elif plan and plan.kind == 'browser':
                import os
                if os.getenv('OPENLEARN_BROWSER_ASSISTANT_ENABLED', 'true') != 'true':
                    fail('capability_unavailable', 'Browser assistance is disabled. Enable a browser connection to continue this request.', 503)
                from ..browser_assistant.service import AssistantService
                from ..browser_assistant.contracts import TaskCreate
                run = AssistantService(self.store).create(owner, TaskCreate(message=body.text, sessionId=body.session_id, courseId=body.course_id, previousTaskId=body.previous_browser_task_id), 'message:' + identifier, connection=conn)
                response.update(status='queued', handled=True, runtimeOwner='browser_legacy', references=[{'kind':'task','id':run['id']}])
            elif plan and plan.kind == 'control':
                rows = conn.execute(text("SELECT id,payload FROM assistant_runs WHERE owner_id=:owner AND session_id=:session AND status NOT IN ('completed','completed_partial','failed','cancelled') ORDER BY updated_at DESC LIMIT 10"), {'owner':owner,'session':body.session_id}).mappings().all()
                if len(rows) == 1:
                    target = json.loads(rows[0]['payload'])
                    if target.get('runtime_owner') == 'agent_v2':
                        ack = self.apply_command(conn, owner, rows[0]['id'], Command(commandId='control_'+identifier, action=plan.action, expectedRevision=target['revision']))
                        response.update(status='accepted',handled=True,references=[{'kind':'task','id':rows[0]['id']}])
                    else:
                        response.update(status='requires_action',handled=True,directive={'kind':'browser_control','taskId':rows[0]['id'],'action':plan.action},references=[{'kind':'task','id':rows[0]['id']}],runtimeOwner='browser_legacy')
                else:
                    response.update(status='needs_input',handled=True,question='Which task should I '+plan.action+'?' if rows else 'There is no active task in this conversation to '+plan.action+'.',references=[{'kind':'task','id':row['id']} for row in rows])
            elif plan and plan.kind in {'flashcards','reminder','analysis','connected_action','memory','responsibility'} and capability is None:
                response.update(status='requires_action',handled=True,directive={'kind':plan.kind},references=[])
                if plan.kind == 'analysis':
                    response.update(status='needs_input',question='Attach the dataset as a CSV and tell me what you want to learn from it. Open Learn can profile columns, missing values, and numeric summaries; Daytona lab analysis supports the trial, distance, and time workflow.')
                if plan.kind == 'responsibility':
                    response.update(status='needs_input',question='Choose a course, schedule, and run limit in Ongoing work before I start monitoring. A one-time website check does not enable recurring work.')
                if plan.kind == 'connected_action':
                    response.update(status='needs_input',question='Connect the relevant app in Agent workspace, then prepare a concrete action for review. Sending or changing an external calendar requires its approval card.')
            elif capability:
                if not admission_enabled(): fail('capability_unavailable','New agent admission is disabled. Existing work remains available.',503)
                if capability=='flashcards':
                    from ..flashcards.sources import resolve
                    spec=body.flashcard_spec
                    if not spec or spec.session_id!=body.session_id:fail('invalid_input','Provide flashcard sources for this conversation.',422)
                    manifest=resolve(self.store,conn,owner,spec)
                    if spec.target_deck_id:
                        from ..flashcards.repository import Repository as FlashcardRepository
                        deck=FlashcardRepository(self.store).get(conn,owner,'decks',spec.target_deck_id,True)
                        if deck['revision']!=spec.expected_deck_revision:fail('revision_conflict','Deck changed.',409)
                        if deck.get('courseId')!=manifest.get('courseId'):fail('source_scope_mismatch','Choose a deck in the current course.',422)
                    run=self.create(conn,owner,body.session_id,body.text,'message:'+identifier,None,{'flashcardRequest':spec.model_dump(by_alias=True),'flashcardManifest':manifest},kind='flashcards',accepted_usage_cap_micro=body.accepted_usage_cap_micro)
                elif capability=='research':
                    from .research_contracts import ResearchSpec
                    spec=ResearchSpec.model_validate(body.research_spec or {'query':body.text}).model_dump(by_alias=True)
                    csv_value=body.csv_text or None;input_material=None;analysis_mode='lab'
                    if inferred_csv:
                        if csv_value:fail('invalid_input','Select one dataset input: inline CSV or an attached material.',422)
                        from .sandbox_inputs import material_csv
                        csv_value,input_material=material_csv(self.store,owner,body.session_id,inferred_csv,conn,allow_general=True)
                    if csv_value:
                        from .tools import choose_analysis_mode
                        analysis_mode,_=choose_analysis_mode(csv_value,body.text)
                    run=self.create(conn,owner,body.session_id,body.text,'message:'+identifier,csv_value,{},kind='research',research_spec=spec,input_material=input_material,accepted_usage_cap_micro=body.accepted_usage_cap_micro,analysis_mode=analysis_mode)
                else:
                    if capability=='sandbox_lab':
                        from .sandbox_config import readiness
                        state=readiness()
                        if state['state']!='available':fail('capability_unavailable',state['reasonCode'],503)
                    input_material=None
                    csv_value=body.csv_text or FIXTURE
                    if inferred_csv:
                        if capability not in {'sandbox_lab','lab_analysis'} or body.csv_text:fail('invalid_input','Select one sandbox CSV input: inline text or material version.',422)
                        from .sandbox_inputs import material_csv
                        csv_value,input_material=material_csv(self.store,owner,body.session_id,inferred_csv,conn)
                    if capability=='sandbox_lab':
                        rows=parse_csv(csv_value);constraints=constraints_from(body.text,{},rows);analysis_mode='lab'
                    else:
                        from .tools import choose_analysis_mode
                        analysis_mode,constraints=choose_analysis_mode(csv_value,body.text)
                    run=self.create(conn,owner,body.session_id,body.text,'message:'+identifier,csv_value,constraints,kind=capability,input_material=input_material,accepted_usage_cap_micro=body.accepted_usage_cap_micro,analysis_mode=analysis_mode)
                response.update(status='queued',handled=True,references=[{'kind':'task','id':run['id']}])
            conn.execute(text('INSERT INTO agent_messages(id,owner_id,session_id,client_message_id,command_key,request_hash,payload,response,created_at) VALUES(:id,:owner,:session,:client,:key,:hash,:payload,:response,:now)'),{'id':identifier,'owner':owner,'session':body.session_id,'client':body.client_message_id,'key':key,'hash':hash_value,'payload':encoded(data),'response':encoded(response),'now':time.time()})
            if response['handled'] and response.get('runtimeOwner') != 'browser_legacy' and response['references'] and response['status'] in {'queued','accepted'}:
                run=self.repo.run(conn,owner,next(r['id'] for r in response['references'] if r['kind']=='task'))
                self.repo.activity(conn,run,'user:'+identifier,'user.message',messageId=identifier,text=body.text)
            return response

    def create(self, conn, owner, session, message, key, csv_value, constraints, parent=None, parent_revision=None, kind='lab_analysis', research_spec=None,input_material=None,accepted_usage_cap_micro=None,usage_root_id=None,analysis_mode='lab',calendar_read=None):
        if conn.execute(text("SELECT count(*) FROM assistant_runs WHERE owner_id=:owner AND runtime_owner='agent_v2' AND status IN ('queued','running')"),{'owner':owner}).scalar_one()>=2:
            fail('task_limit','Two tasks are already active. Pause or finish one before starting another.',429)
        now=time.time()
        identifier=uid('assistant')
        if usage_root_id is None:
            usage_root_id=identifier
            from ..usage.ledger import Ledger,UsageError
            from ..usage.policy import Policy
            policy=Policy.load();ledger=Ledger(self.store,policy)
            cap=accepted_usage_cap_micro if accepted_usage_cap_micro is not None else policy.grant
            try:ledger.accept_task_cap_in_transaction(conn,owner,usage_root_id,cap,now)
            except UsageError as exc:fail(exc.detail.get('code','usage_task_cap_invalid'),exc.detail.get('message','Task maximum is unavailable.'),exc.status_code)
        from .kernel import TaskRequirements
        output_names = {'lab_analysis':['analysis.xlsx','analysis.pdf','analysis.csv','report.json'] if analysis_mode=='general' else ['analysis.xlsx','speeds.png','analysis.csv'],
                        'sandbox_lab':['analysis.xlsx','speeds.png','analysis.csv','report.json'],
                        'research':['research-report.md','research-sources.json'],
                        'calendar_read':['calendar-events.json']}.get(kind, [])
        requirements = TaskRequirements(requestedOutputs=output_names).model_dump(by_alias=True)
        input_hash=(digest({'message':message,'calendarRead':calendar_read}) if calendar_read is not None else
                    digest([csv_value,research_spec]) if csv_value is not None and research_spec is not None else
                    digest(csv_value if csv_value is not None else research_spec))
        dependencies=[{'id':parent,'kind':'task','status':'satisfied','required':True,'sourceId':parent,'sourceRevision':parent_revision or 1}] if parent else []
        run={'id':identifier,'owner_id':owner,'runtime_owner':'agent_v2','revision':1,'desired_input_revision':1,'sessionId':session,'message':message,'kind':kind,'analysisMode':analysis_mode,'status':'queued','phase':'inspect','waitReason':None,'csvText':csv_value,'researchSpec':research_spec,'calendarRead':calendar_read,'inputHash':input_hash,'constraints':constraints,'pendingRequests':[],'dependencies':dependencies,'requirements':requirements,'operationalNoteRefs':[],'executionContext':None,'kernelState':{'decisions':0,'toolCalls':0,'repeatedNoProgress':0,'recentSignatures':[]},'answerAttachments':[],'artifacts':[],'completion':None,'commandCursor':0,'checkpointVersion':0,'parentTaskId':parent,'usageRootId':usage_root_id,'createdAt':now,'updatedAt':now,'summary':None,'connectionId':None}
        run['inputMaterial']=input_material
        conn.execute(text("INSERT INTO assistant_runs(id,owner_id,revision,session_id,command_key,request_hash,status,payload,created_at,updated_at,runtime_owner,desired_input_revision) VALUES(:id,:owner,1,:session,:key,:hash,'queued',:payload,:now,:now,'agent_v2',1)"),{'id':run['id'],'owner':owner,'session':session,'key':key,'hash':digest(run),'payload':encoded({k:v for k,v in run.items() if k!='owner_id'}),'now':now})
        self.repo.event(conn,run,'task.created');run=self.repo.checkpoint(conn,run);self.repo.schedule(conn,run)
        self.repo.activity(conn,run,'task:'+run['id'],'task.created')
        return run

    def command(self, owner, task_id, command):
        with self.repo.transaction() as conn: return self.apply_command(conn,owner,task_id,command)

    def apply_command(self, conn, owner, task_id, command):
        run=self.repo.run(conn,owner,task_id);data=command.model_dump(by_alias=True);hash_value=digest(data)
        existing=conn.execute(text('SELECT * FROM agent_commands WHERE id=:id AND owner_id=:owner'),{'id':command.command_id,'owner':owner}).mappings().first()
        if existing:
            if existing['request_hash']!=hash_value or existing['run_id']!=task_id: fail('idempotency_conflict','Command identity has different content.',409)
            return json.loads(existing['ack'])
        if conn.execute(text('SELECT 1 FROM agent_commands WHERE id=:id'),{'id':command.command_id}).first(): fail('idempotency_conflict','Use a new command identity.',409)
        if run['revision']!=command.expected_revision: fail('revision_conflict','Task changed. Refresh before applying the change.',409)
        if run['status'] in TERMINAL: fail('invalid_state','This task has finished. Submit a linked follow-up.',409)
        changes={'commandCursor':run['commandCursor']+1}
        if command.action in {'answer_input','steer'}:
            answer = command.answer.model_dump(by_alias=True, exclude_none=True) if command.answer else {}
            message=command.text or answer.get('text') or answer.get('selectedOption','') or ('Attached file.' if answer.get('attachments') else '')
            if not isinstance(message,str) or not message.strip(): fail('invalid_input','Provide an answer or change.',422)
            request = None
            request_payload = {}
            if command.action=='answer_input':
                if not command.request_id or command.expected_request_revision is None:
                    fail('invalid_input','Answer the exact open question using its current revision.',422)
                request=conn.execute(text('SELECT * FROM agent_input_requests WHERE id=:id AND owner_id=:owner AND run_id=:run'),{'id':command.request_id,'owner':owner,'run':task_id}).mappings().first()
                if not request: fail('not_found','Question unavailable for this task.',404)
                request_payload=json.loads(request['payload'])
                if request['status']!='open' or request['revision']!=command.expected_request_revision:
                    fail('revision_conflict','This question was already answered or changed.',409)
                input_kind=request_payload.get('inputKind','text')
                if input_kind=='choice':
                    # The chat composer sends its selected chip as text. Accept
                    # that only when it exactly matches one of this request's
                    # offered options, then persist it as the structured choice.
                    if answer.get('selectedOption') is None and answer.get('text') in request_payload.get('options',[]):
                        answer['selectedOption']=answer['text']
                    if answer.get('selectedOption') not in request_payload.get('options',[]):
                        fail('invalid_input','Choose one of the listed options.',422)
                elif answer.get('selectedOption') is not None:
                    fail('input_kind_mismatch','This question does not accept a choice.',409)
                if answer.get('attachments') and input_kind not in {'file','voice_transcript'}:
                    fail('input_kind_mismatch','This question does not accept file attachments.',409)
                if input_kind=='file' and not answer.get('attachments'):
                    fail('input_required','Attach a file to answer this question.',422)
                if input_kind=='confirmation' and message.lower() not in {'yes','no','confirm','cancel','approved','denied'}:
                    fail('invalid_input','Confirm or decline this request.',422)
                for attachment in answer.get('attachments',[]):
                    from ..material_service import MaterialService
                    MaterialService(self.store).version(owner,attachment['versionId'],conn)
                    if not conn.execute(text('SELECT 1 FROM material_attachments WHERE session_id=:session AND version_id=:version'),{'session':run['sessionId'],'version':attachment['versionId']}).first():
                        fail('source_scope_denied','Attach this owned material to the conversation before using it.',403)
            if run['kind'] in {'lab_analysis','sandbox_lab'}:
                try:
                    csv_text=run['csvText'];input_material=run.get('inputMaterial')
                    csv_attachments=[a for a in answer.get('attachments',[]) if a['name'].lower().endswith('.csv')]
                    if csv_attachments:
                        if len(csv_attachments)!=1: fail('invalid_input','Attach one CSV file to replace the analysis input.',422)
                        from .sandbox_inputs import material_csv
                        csv_text,input_material=material_csv(self.store,owner,run['sessionId'],csv_attachments[0]['versionId'],conn)
                        changes.update(csvText=csv_text,inputMaterial=input_material,inputHash=digest(csv_text))
                    if run.get('analysisMode')=='general':
                        from .tools import parse_dataset_csv
                        parse_dataset_csv(csv_text)
                        constraints={**run['constraints'],'steering':message}
                    else:
                        constraints=constraints_from(message,run['constraints'],parse_csv(csv_text))
                except ValueError as exc: fail('invalid_input',str(exc),422)
            else:
                constraints={**run['constraints'],'steering':message}
            if run['kind']=='flashcards':
                constraints['flashcardRequest']={**constraints['flashcardRequest'],'objective':message[:1000]}
            if command.action=='answer_input':
                if run['kind'] in {'lab_analysis','sandbox_lab'} and run.get('analysisMode')!='general' and not constraints.get('distanceUnit'): fail('invalid_input','Specify centimeters or meters before resuming.',422)
                if not any(item.get('requestId') == request['id'] for item in run.get('pendingRequests', [])):
                    fail('revision_conflict','This question is no longer pending for the task.',409)
                prior_attachments=list(run.get('answerAttachments',[]))
                for attachment in answer.get('attachments',[]):
                    prior_attachments.append({'versionId':attachment['versionId'],'name':attachment.get('name',''),'requestId':request['id'],'requestRevision':request['revision']})
                changes['answerAttachments']=prior_attachments[-40:]
                changed=conn.execute(text("UPDATE agent_input_requests SET status='answered',revision=revision+1,payload=:payload WHERE id=:id AND owner_id=:owner AND run_id=:run AND status='open' AND revision=:revision"),{'id':request['id'],'owner':owner,'run':task_id,'revision':request['revision'],'payload':encoded({**request_payload,'answerCommandId':command.command_id,'answerMessageId':command.message_id,'answerText':message,'answerAttachments':answer.get('attachments',[]),'selectedOption':answer.get('selectedOption')})})
                if changed.rowcount!=1: fail('revision_conflict','This question was already answered or changed.',409)
                changes['pendingRequests']=[r for r in run['pendingRequests'] if r['requestId']!=request['id']]
                self.repo.event(conn,run,'input.answered',requestId=request['id'])
            still_waiting = command.action == 'answer_input' and any(item.get('required', True) and item.get('state', 'open') == 'open' for item in changes.get('pendingRequests', []))
            next_status = 'paused' if run['status']=='paused' else 'waiting' if still_waiting else 'queued'
            changes.update(constraints=constraints,desired_input_revision=run['desired_input_revision']+1,executionContext=None,
                           phase='clarify' if still_waiting else 'inspect',status=next_status,
                           waitReason='user_input' if still_waiting else None)
            if command.action=='steer' and constraints.get('distanceUnit') and run['pendingRequests']:
                conn.execute(text("UPDATE agent_input_requests SET status='superseded',revision=revision+1 WHERE run_id=:run AND status='open'"),{'run':task_id})
                changes['pendingRequests']=[]
                self.repo.event(conn,run,'input.superseded')
            from .artifacts import Artifacts
            Artifacts(self.store).cleanup(conn,owner,task_id)
        elif command.action=='pause': changes.update(status='paused',waitReason=None)
        elif command.action=='cancel':
            changes.update(status='cancelled',waitReason=None,pendingRequests=[])
            conn.execute(text("UPDATE agent_input_requests SET status='cancelled',revision=revision+1 WHERE run_id=:run AND status='open'"),{'run':task_id})
            from .artifacts import Artifacts
            Artifacts(self.store).cleanup(conn,owner,task_id)
        elif command.action=='resume':
            if run['status']!='paused': fail('invalid_state','Only paused work can resume.',409)
            changes.update(status='waiting' if run['pendingRequests'] else 'queued',waitReason='user_input' if run['pendingRequests'] else None)
        # Fence jobs now; no stale operation can publish after acceptance.
        conn.execute(text("UPDATE learning_jobs SET status='cancelled',cancellation_requested=true,cancel_requested=true,lease=NULL,expires=NULL WHERE owner_id=:owner AND target_id=:run AND kind='agent_step' AND status IN ('queued','retry_wait','running')"),{'owner':owner,'run':task_id})
        run=self.repo.update(conn,run,**changes);run=self.repo.checkpoint(conn,run)
        if run['status']=='queued': self.repo.schedule(conn,run)
        ack={'commandId':command.command_id,'taskId':task_id,'acceptedRevision':run['revision'],'applicationState':'applied'}
        conn.execute(text('INSERT INTO agent_commands(id,owner_id,run_id,cursor,request_hash,payload,ack,created_at) VALUES(:id,:owner,:run,:cursor,:hash,:payload,:ack,:now)'),{'id':command.command_id,'owner':owner,'run':task_id,'cursor':run['commandCursor'],'hash':hash_value,'payload':encoded(data),'ack':encoded(ack),'now':time.time()})
        self.repo.event(conn,run,'command.applied',commandId=command.command_id,action=command.action)
        self.repo.activity(conn,run,'command:'+command.command_id,'command.applied',text='Change applied.' if command.action in {'steer','answer_input'} else f'Task {run["status"]}.',commandId=command.command_id)
        return ack

    def snapshot(self, owner, session, after=None):
        with self.repo.transaction() as conn:
            self.repo.session(conn,owner,session)
            cursor_row=conn.execute(text('SELECT sequence,pruned_through FROM agent_activity_cursors WHERE owner_id=:owner AND session_id=:session'),{'owner':owner,'session':session}).one()
            cursor,pruned_through=cursor_row
            if after is not None and after>cursor: fail('resync_required','Activity cursor is ahead of the server. Reload the snapshot.',409)
            if after is not None and after<pruned_through:
                tasks=conn.execute(text("SELECT id FROM assistant_runs WHERE owner_id=:owner AND session_id=:session AND runtime_owner='agent_v2' ORDER BY created_at DESC LIMIT 100"),{'owner':owner,'session':session}).scalars().all()
                return {'schemaVersion':2,'cursor':cursor,'hasMore':False,'resnapshotRequired':True,'prunedThrough':pruned_through,'items':[],'tasks':[self.repo.descriptor(self.repo.run(conn,owner,id)) for id in reversed(tasks)]}
            query='SELECT sequence,payload FROM agent_activity WHERE owner_id=:owner AND session_id=:session AND sequence>:after ORDER BY sequence LIMIT 100'
            rows=conn.execute(text(query),{'owner':owner,'session':session,'after':max(after or 0,pruned_through)}).mappings().all()
            tasks=conn.execute(text("SELECT id FROM assistant_runs WHERE owner_id=:owner AND session_id=:session AND runtime_owner='agent_v2' ORDER BY created_at DESC LIMIT 100"),{'owner':owner,'session':session}).scalars().all()
            items=[{'sequence':r['sequence'],**json.loads(r['payload'])} for r in rows]
            # Pagination must not skip undelivered items.
            return {'schemaVersion':2,'cursor':items[-1]['sequence'] if len(items)==100 else cursor,'hasMore':len(items)==100 and items[-1]['sequence']<cursor,'resnapshotRequired':False,'prunedThrough':pruned_through,'items':items,'tasks':[self.repo.descriptor(self.repo.run(conn,owner,id)) for id in reversed(tasks)]}
