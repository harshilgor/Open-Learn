"""Shared agent-worker dispatch; no second queue or worker owner."""
from ..identity import fail
from .contracts import FlashcardRequest
from .sources import resolve
from .generation import generate
from .service import DeckService

def execute_task(worker,job):
    repo=worker.repo;owner=job['owner_id'];svc=DeckService(worker.store)
    with repo.transaction() as conn:
        run=repo.run(conn,owner,job['target_id']);repo.jobs.validate_lease(conn,job)
        if run['status'] in {'paused','waiting','cancelled','completed','completed_partial','failed'} or run['desired_input_revision']!=job['input_revision']:
            repo.jobs.finish(conn,job,{'ignored':True});return
        request=FlashcardRequest.model_validate(run['constraints']['flashcardRequest']);manifest=run['constraints']['flashcardManifest']
        run=repo.update(conn,run,status='running',phase='drafting');repo.event(conn,run,'task.phase_changed',phase='drafting');expected=run['revision']
    def guard():
        with repo.transaction() as conn:
            current=repo.run(conn,owner,run['id']);repo.jobs.validate_lease(conn,job)
            if current['revision']!=expected or current['desired_input_revision']!=job['input_revision']:fail('revision_conflict','Task changed during generation.',409)
    def phase(value):
        nonlocal expected
        with repo.transaction() as conn:
            current=repo.run(conn,owner,run['id']);repo.jobs.validate_lease(conn,job)
            if current['revision']!=expected:fail('revision_conflict','Task changed.',409)
            current=repo.update(conn,current,phase=value);expected=current['revision'];repo.event(conn,current,'task.phase_changed',phase=value)
    result=generate(worker.provider_getter(),request,manifest,guard,phase)
    guard()
    with repo.transaction() as conn:
        current=repo.run(conn,owner,run['id']);repo.jobs.validate_lease(conn,job)
        if current['revision']!=expected:fail('revision_conflict','Task changed.',409)
        fresh=resolve(worker.store,conn,owner,request)
        if [(s['id'],s['hash']) for s in fresh['sources']]!=[(s['id'],s['hash']) for s in manifest['sources']]:fail('source_revision_conflict','Sources changed. Start a new request with current revisions.',409)
        if request.target_deck_id:
            deck=svc.repo.get(conn,owner,'decks',request.target_deck_id,True)
            if deck['revision']!=request.expected_deck_revision:fail('deck_changed','Deck changed during generation. Retry with its current revision.',409)
        else:deck=svc.create(conn,owner,'Flashcards · '+manifest['sources'][0]['title'],manifest,request)
        deck=svc.append(conn,owner,deck,result,manifest,run['id'])
        status='completed_partial' if result['partial'] else 'completed'
        summary=f"{len(result['cards'])} cards prepared from {len(manifest['sources'])} study sources. Inspect and publish selected cards."
        completion={'status':'partial' if result['partial'] else 'complete','partial':result['partial'],'candidateCount':len(result['candidates']),'quality':'Model checks are fallible; inspect the supporting passages.'}
        references=[{'kind':'flashcard_deck','id':deck['id']}]
        current=repo.update(conn,current,status=status,phase='draft_ready',summary=summary,completion=completion,resultReferences=references,deckId=deck['id'],pendingRequests=[])
        current=repo.checkpoint(conn,current);repo.event(conn,current,'task.completed',references=references,completion=completion)
        repo.activity(conn,current,'final:'+current['id'],'task.completed',text=summary,references=references,completion=completion)
        repo.jobs.finish(conn,job,{'taskId':run['id'],'deckId':deck['id'],'status':status})
