from backend.tests.test_learning_workflows import env, command, quiz_ready
from backend.app.workflow_store import WorkflowStore

def test_upcoming_question_revision_is_owned_and_idempotent(env):
    client,store,_,session=env
    job=command(client,'/quizzes',{'sessionId':session.id,'count':3})
    qid=job['result']['quizId']
    body={'questionNumber':3,'difficulty':'stretch','expectedRevision':1}
    path=f'/v1/quizzes/{qid}/question-difficulty'
    headers={'Idempotency-Key':'adjust-three'}
    response=client.post(path,json=body,headers=headers)
    assert response.status_code==200,response.text
    assert response.json()['regenerating'] is False
    assert WorkflowStore(store).read('local',qid,'quiz')['questionDifficulty']['3']=='stretch'
    repeated=client.post(path,json=body,headers=headers)
    assert repeated.json()==response.json()
    stale=client.post(path,json=body,headers={'Idempotency-Key':'new-stale'})
    assert stale.status_code==409
    invalid=client.post(path,json={**body,'questionNumber':4,'expectedRevision':2},headers={'Idempotency-Key':'outside-quiz'})
    assert invalid.status_code==422

def test_current_question_regeneration_keeps_quiz_identity(env):
    client,store,provider,session=env
    quiz=quiz_ready(client,session)
    original=quiz['current']['id']
    generate=provider.complete_json
    def revised(prompt,max_tokens=4000):
        value=generate(prompt,max_tokens)
        if prompt.startswith('You author'):
            value={**value,'stem':'Given an event B, which population defines the conditional probability?','family':'conditional_reference_population'}
        return value
    provider.complete_json=revised
    response=client.post(f"/v1/quizzes/{quiz['id']}/question-difficulty",json={'questionNumber':1,'difficulty':'stretch','expectedRevision':quiz['revision']},headers={'Idempotency-Key':'replace-current'})
    assert response.status_code==200,response.text
    assert response.json()['quizId']==quiz['id'] and response.json()['jobId']
    refreshed=client.get(f"/v1/quizzes/{quiz['id']}").json()
    assert refreshed['current'],client.get(f"/v1/learning-jobs/{response.json()['jobId']}").json()
    assert refreshed['current']['id']!=original
    assert WorkflowStore(store).read('local',original,'presentation')['id']==original
