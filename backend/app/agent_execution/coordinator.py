"""Admission and human replies commit once; work is independent of subscribers."""
import json
import time
from sqlalchemy import text
from ..identity import fail
from ..workflow_store import encoded, uid
from .contracts import Command
from .repository import Repository, TERMINAL, digest
from .config import admission_enabled
from .tools import FIXTURE, parse_csv, constraints_from


class Coordinator:
    def __init__(self, store): self.store=store;self.repo=Repository(store)

    def admit(self, owner, body, key):
        if not key or len(key)>200: fail('invalid_input','Provide a stable Idempotency-Key.',422)
        data=body.model_dump(by_alias=True);hash_value=digest(data)
        with self.repo.transaction() as conn:
            self.repo.session(conn,owner,body.session_id)
            existing=conn.execute(text('SELECT * FROM agent_messages WHERE owner_id=:owner AND (client_message_id=:client OR command_key=:key)'),{'owner':owner,'client':body.client_message_id,'key':key}).mappings().first()
            if existing:
                if existing['request_hash']!=hash_value: fail('idempotency_conflict','That message identity has different content.',409)
                return json.loads(existing['response'])
            identifier=uid('message')
            response={'schemaVersion':2,'messageId':identifier,'admissionId':identifier,'status':'direct','handled':False,'references':[]}
            if body.target_task_id or body.reply_to_request_id:
                if not body.target_task_id:
                    row=conn.execute(text('SELECT run_id FROM agent_input_requests WHERE id=:id AND owner_id=:owner'),{'id':body.reply_to_request_id,'owner':owner}).first()
                    if not row: fail('not_found','Question unavailable.',404)
                    target=row[0]
                else: target=body.target_task_id
                run=self.repo.run(conn,owner,target)
                if run['sessionId']!=body.session_id: fail('not_found','Task unavailable in this conversation.',404)
                if body.expected_revision is None: fail('invalid_input','Reply requires the task revision.',422)
                command=Command(commandId='reply_'+identifier,action='answer_input' if body.reply_to_request_id else 'steer',expectedRevision=body.expected_revision,
                    requestId=body.reply_to_request_id,expectedRequestRevision=body.expected_request_revision,messageId=identifier,text=body.text)
                if run['status'] in TERMINAL and command.action=='steer':
                    if conn.execute(text('SELECT 1 FROM agent_delegated_children WHERE child_id=:id AND owner_id=:owner'),{'id':run['id'],'owner':owner}).first():fail('delegation_depth_denied','Start a separate user task; bounded children cannot create follow-up children.',403)
                    if not admission_enabled():fail('capability_unavailable','New agent tasks are disabled.',503)
                    if run['status'] not in {'completed','completed_partial'}: fail('invalid_state','Start a new task to change this result.',409)
                    if run['revision']!=command.expected_revision: fail('revision_conflict','Task changed. Refresh before correcting it.',409)
                    if run['kind']=='flashcards':
                        fail('invalid_input','Use Make flashcards with current source revisions to create a corrected deck.',422)
                    elif run['kind']=='research':
                        from .research_contracts import ResearchSpec
                        spec=ResearchSpec.model_validate({**run['researchSpec'],'query':body.text}).model_dump(by_alias=True)
                        child=self.create(conn,owner,body.session_id,body.text,'followup:'+identifier,None,{},parent=run['id'],kind='research',research_spec=spec)
                    else:
                        corrected=constraints_from(body.text,run['constraints'],parse_csv(run['csvText']))
                        child=self.create(conn,owner,body.session_id,body.text,'followup:'+identifier,run['csvText'],corrected,parent=run['id'],kind=run['kind'],input_material=run.get('inputMaterial'))
                    response.update(status='queued',handled=True,references=[{'kind':'task','id':child['id']}])
                else:
                    input_material=None
                    ack=self.apply_command(conn,owner,target,command)
                    response.update(status='accepted',handled=True,references=[{'kind':'task','id':target},{'kind':'command','id':ack['commandId']}])
            elif body.capability:
                if not admission_enabled(): fail('capability_unavailable','New agent admission is disabled. Existing work remains available.',503)
                if body.capability=='flashcards':
                    from ..flashcards.sources import resolve
                    spec=body.flashcard_spec
                    if not spec or spec.session_id!=body.session_id:fail('invalid_input','Provide flashcard sources for this conversation.',422)
                    manifest=resolve(self.store,conn,owner,spec)
                    if spec.target_deck_id:
                        from ..flashcards.repository import Repository as FlashcardRepository
                        deck=FlashcardRepository(self.store).get(conn,owner,'decks',spec.target_deck_id,True)
                        if deck['revision']!=spec.expected_deck_revision:fail('revision_conflict','Deck changed.',409)
                        if deck.get('courseId')!=manifest.get('courseId'):fail('source_scope_mismatch','Choose a deck in the current course.',422)
                    run=self.create(conn,owner,body.session_id,body.text,'message:'+identifier,None,{'flashcardRequest':spec.model_dump(by_alias=True),'flashcardManifest':manifest},kind='flashcards')
                elif body.capability=='research':
                    from .research_contracts import ResearchSpec
                    spec=ResearchSpec.model_validate(body.research_spec or {'query':body.text}).model_dump(by_alias=True)
                    run=self.create(conn,owner,body.session_id,body.text,'message:'+identifier,None,{},kind='research',research_spec=spec)
                else:
                    if body.capability=='sandbox_lab':
                        from .sandbox_config import readiness
                        state=readiness()
                        if state['state']!='available':fail('capability_unavailable',state['reasonCode'],503)
                    input_material=None
                    csv_value=body.csv_text or FIXTURE
                    if body.material_version_id:
                        if body.capability!='sandbox_lab' or body.csv_text:fail('invalid_input','Select one sandbox CSV input: inline text or material version.',422)
                        from .sandbox_inputs import material_csv
                        csv_value,input_material=material_csv(self.store,owner,body.session_id,body.material_version_id,conn)
                    rows=parse_csv(csv_value);constraints=constraints_from(body.text,{},rows)
                    run=self.create(conn,owner,body.session_id,body.text,'message:'+identifier,csv_value,constraints,kind=body.capability,input_material=input_material)
                response.update(status='queued',handled=True,references=[{'kind':'task','id':run['id']}])
            conn.execute(text('INSERT INTO agent_messages(id,owner_id,session_id,client_message_id,command_key,request_hash,payload,response,created_at) VALUES(:id,:owner,:session,:client,:key,:hash,:payload,:response,:now)'),{'id':identifier,'owner':owner,'session':body.session_id,'client':body.client_message_id,'key':key,'hash':hash_value,'payload':encoded(data),'response':encoded(response),'now':time.time()})
            if response['handled']:
                run=self.repo.run(conn,owner,next(r['id'] for r in response['references'] if r['kind']=='task'))
                self.repo.activity(conn,run,'user:'+identifier,'user.message',messageId=identifier,text=body.text)
            return response

    def create(self, conn, owner, session, message, key, csv_value, constraints, parent=None, kind='lab_analysis', research_spec=None,input_material=None):
        if conn.execute(text("SELECT count(*) FROM assistant_runs WHERE owner_id=:owner AND runtime_owner='agent_v2' AND status IN ('queued','running')"),{'owner':owner}).scalar_one()>=2:
            fail('task_limit','Two tasks are already active. Pause or finish one before starting another.',429)
        now=time.time()
        run={'id':uid('assistant'),'owner_id':owner,'runtime_owner':'agent_v2','revision':1,'desired_input_revision':1,'sessionId':session,'message':message,'kind':kind,'status':'queued','phase':'inspect','waitReason':None,'csvText':csv_value,'researchSpec':research_spec,'inputHash':digest(csv_value or research_spec),'constraints':constraints,'pendingRequests':[],'artifacts':[],'completion':None,'commandCursor':0,'checkpointVersion':0,'parentTaskId':parent,'createdAt':now,'updatedAt':now,'summary':None,'connectionId':None}
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
            message=command.text or (command.answer or {}).get('text','')
            if not isinstance(message,str) or not message.strip(): fail('invalid_input','Provide an answer or change.',422)
            if (command.answer or {}).get('attachments'): fail('invalid_input','Attachments are not supported in this development adapter.',422)
            if run['kind'] in {'lab_analysis','sandbox_lab'}:
                try: constraints=constraints_from(message,run['constraints'],parse_csv(run['csvText']))
                except ValueError as exc: fail('invalid_input',str(exc),422)
            else:
                constraints={**run['constraints'],'steering':message}
            if run['kind']=='flashcards':
                constraints['flashcardRequest']={**constraints['flashcardRequest'],'objective':message[:1000]}
            if command.action=='answer_input':
                request=conn.execute(text('SELECT * FROM agent_input_requests WHERE id=:id AND owner_id=:owner AND run_id=:run'),{'id':command.request_id,'owner':owner,'run':task_id}).mappings().first()
                if not request: fail('not_found','Question unavailable for this task.',404)
                if request['status']!='open' or request['revision']!=command.expected_request_revision: fail('revision_conflict','This question was already answered or changed.',409)
                if run['kind'] in {'lab_analysis','sandbox_lab'} and not constraints.get('distanceUnit'): fail('invalid_input','Specify centimeters or meters before resuming.',422)
                conn.execute(text("UPDATE agent_input_requests SET status='answered',revision=revision+1,payload=:payload WHERE id=:id AND status='open' AND revision=:revision"),{'id':request['id'],'revision':request['revision'],'payload':encoded({**json.loads(request['payload']),'answerCommandId':command.command_id,'answerMessageId':command.message_id,'answerText':message})})
                changes['pendingRequests']=[r for r in run['pendingRequests'] if r['requestId']!=request['id']]
                self.repo.event(conn,run,'input.answered',requestId=request['id'])
            changes.update(constraints=constraints,desired_input_revision=run['desired_input_revision']+1,phase='inspect',status='paused' if run['status']=='paused' else 'queued',waitReason=None)
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
            cursor=conn.execute(text('SELECT sequence FROM agent_activity_cursors WHERE owner_id=:owner AND session_id=:session'),{'owner':owner,'session':session}).scalar_one()
            if after is not None and after>cursor: fail('resync_required','Activity cursor is ahead of the server. Reload the snapshot.',409)
            query='SELECT sequence,payload FROM agent_activity WHERE owner_id=:owner AND session_id=:session AND sequence>:after ORDER BY sequence LIMIT 100'
            rows=conn.execute(text(query),{'owner':owner,'session':session,'after':after or 0}).mappings().all()
            tasks=conn.execute(text("SELECT id FROM assistant_runs WHERE owner_id=:owner AND session_id=:session AND runtime_owner='agent_v2' ORDER BY created_at DESC LIMIT 100"),{'owner':owner,'session':session}).scalars().all()
            items=[{'sequence':r['sequence'],**json.loads(r['payload'])} for r in rows]
            # Pagination must not skip undelivered items.
            return {'schemaVersion':2,'cursor':items[-1]['sequence'] if len(items)==100 else cursor,'hasMore':len(items)==100 and items[-1]['sequence']<cursor,'items':items,'tasks':[self.repo.descriptor(self.repo.run(conn,owner,id)) for id in reversed(tasks)]}
