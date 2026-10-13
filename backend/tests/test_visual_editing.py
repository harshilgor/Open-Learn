"""Conversational editing: edit-target grounding, declared revisions and lineage."""
import asyncio
import json

import pytest
from sqlalchemy import text

from backend.app.models import utc_now
from backend.app.openintelligentui import GeneratedVisual, extract_controls, generate
from backend.app.session_models import LearningSession, LessonArtifact, LessonBlock
from backend.app.storage import Store
from backend.app.visual_context import visual_grounding
from backend.app.visual_runs import VisualRuns
from backend.app.workflow_store import WorkflowStore
from backend.tests.test_visual_repair_loop import agent_runs, candidate_events, runtime, sse  # noqa: F401 - fixture

PENDULUM_HTML = ('<label for="gravity">Gravity</label><input id="gravity" aria-label="Gravity" type="range" min="1" max="25" value="9.8">'
                 '<label for="length">Length</label><input id="length" aria-label="Length" type="range" min="0.1" max="5" value="1">')


@pytest.fixture
def conversation(tmp_path, monkeypatch):
    """Two turns: the first lesson owns a generated pendulum, the second asks for a change."""
    store = Store(tmp_path / 'edits.db')
    monkeypatch.setattr('backend.app.identity.assert_principal_active', lambda *args: None)
    with store.transaction() as conn:
        conn.execute(text("INSERT INTO topic_scopes(id,payload) VALUES('scope-test','{}')"))
        conn.execute(text("INSERT INTO graph_versions(id,scope_id,payload) VALUES('graph-test','scope-test','{}')"))
    now = utc_now()
    store.save_session(LearningSession(id='session-test', graph_id='graph-test', created_at=now, updated_at=now))
    records = WorkflowStore(store)
    spec = GeneratedVisual(id='visual_parent', renderer='open_generative_ui', title='Pendulum', revision=3,
                           content={'html': [PENDULUM_HTML], 'htmlComplete': True, 'generating': False, 'jsFunctions': 'function f(){}',
                                    'jsExpressions': ['f()']},
                           controls=extract_controls(PENDULUM_HTML), control_values={'gravity': 3.7})
    first = LessonArtifact(id='lesson-one', session_id='session-test', concept_id='c', gear='Quick', title='Pendulum',
                           blocks=[LessonBlock(id='b1', kind='explanation', body='T = 2π√(L/g).', order=0,
                                               visualizations=[{'version': 2, 'type': 'generated_ui_ref', 'id': 'visual_parent', 'revision': 3,
                                                                'title': 'Pendulum', 'runId': 'run-one'}])])
    second = LessonArtifact(id='lesson-two', session_id='session-test', concept_id='c', gear='Quick', title='Damping',
                            blocks=[LessonBlock(id='b2', kind='explanation', body='Damping removes energy.', order=0)])
    store.save_artifact(first)
    store.save_artifact(second)
    with store.transaction() as conn:
        records.put(conn, 'local', 'generated_visual', {'id': 'visual_parent', 'lessonId': 'lesson-one', 'sessionId': 'session-test',
                                                        'spec': spec.model_dump(mode='json', by_alias=True), 'runId': 'run-one'}, 'lesson-one')
        records.put(conn, 'local', 'journey', {'id': 'journey_session-test', 'sessionId': 'session-test', 'turns': [
            {'question': 'Show a pendulum', 'lesson': first.model_dump(mode='json', by_alias=True)},
            {'question': 'Now add air resistance', 'lesson': second.model_dump(mode='json', by_alias=True)}]}, 'session-test')
    yield store, records
    store.close()


def test_edit_request_receives_exact_source_and_state(conversation):
    store, records = conversation
    with store.transaction() as conn:
        grounding = visual_grounding(conn, records, 'local', 'session-test', 'lesson-two', 'Now add air resistance to this simulation')
    target = grounding['editTarget']
    assert target['id'] == 'visual_parent' and target['revision'] == 3
    assert target['source']['html'] == [PENDULUM_HTML]
    assert target['controlValues'] == {'gravity': 3.7}


def test_unrelated_question_gets_no_source(conversation):
    store, records = conversation
    with store.transaction() as conn:
        grounding = visual_grounding(conn, records, 'local', 'session-test', 'lesson-two', 'What is entropy?')
    assert 'editTarget' not in grounding
    assert grounding['priorVisuals'][0]['description']  # still described as text


def test_a_lessons_own_visual_is_not_an_edit_target(conversation):
    store, records = conversation
    with store.transaction() as conn:
        grounding = visual_grounding(conn, records, 'local', 'session-test', 'lesson-one', 'Make this slower')
    assert 'editTarget' not in grounding


def test_oversized_source_is_not_shared(conversation, monkeypatch):
    store, records = conversation
    monkeypatch.setattr('backend.app.visual_context.MAX_EDIT_SOURCE_CHARS', 50)
    with store.transaction() as conn:
        grounding = visual_grounding(conn, records, 'local', 'session-test', 'lesson-two', 'Now add air resistance')
    assert 'editTarget' not in grounding


def edited_events(edit_of):
    html = PENDULUM_HTML + '<label for="damping">Damping</label><input id="damping" aria-label="Damping" type="range" min="0" max="1" value="0.1">'
    events = candidate_events('edit', html, 'function f(){}', ['f()'])
    args = json.loads(events[2]['delta'])
    if edit_of:
        args['editOf'] = edit_of
    events[2]['delta'] = json.dumps(args)
    return events


def run_edit(monkeypatch, runtime_fixture, edit_of):
    runs, requests = runtime_fixture
    seen = []

    def verify(content, controls=(), values=None, **kwargs):
        seen.append(values)
        return {'status': 'passed', 'findings': [], 'digest': 'd', 'durationMs': 1}
    monkeypatch.setattr('backend.app.visual_verification.verify_blocking', verify)
    monkeypatch.setattr('backend.app.visual_verification.unavailable_reason', lambda: None)
    runs.append(sse(edited_events(edit_of)))
    target = {'id': 'visual_parent', 'title': 'Pendulum', 'revision': 3, 'lineage': {'rootId': 'visual_root', 'version': 2},
              'controls': [], 'controlValues': {'gravity': 3.7, 'length': 99}, 'source': {'html': [PENDULUM_HTML]}}

    async def emit(value):
        pass
    result = asyncio.run(generate('owner-a', 'job_edit', {'title': 'Pendulum', 'editTarget': target}, 'Add air resistance', emit))
    return result[0], seen, requests


def test_declared_edit_gets_lineage_and_verified_carried_state(runtime, monkeypatch):
    visual, seen, requests = run_edit(monkeypatch, runtime, 'visual_parent')
    assert visual.lineage.model_dump(by_alias=True) == {'rootId': 'visual_root', 'parentId': 'visual_parent', 'parentRevision': 3, 'version': 3}
    # Out-of-range saved values are dropped; surviving values are what verification tested.
    assert visual.control_values == {'gravity': 3.7} and seen == [{'gravity': 3.7}]
    prompt = agent_runs(requests)[0]['body']['messages'][-1]['content']
    assert 'editTarget' in prompt and PENDULUM_HTML.replace('"', '\\"') in prompt


@pytest.mark.parametrize('edit_of', [None, 'visual_someone_else'])
def test_undeclared_or_foreign_edits_are_new_visuals(runtime, monkeypatch, edit_of):
    visual, seen, _ = run_edit(monkeypatch, runtime, edit_of)
    assert visual.lineage is None and visual.control_values == {} and seen == [{}]


def test_commit_keeps_lineage_only_for_an_owned_parent_in_the_session(conversation):
    store, records = conversation
    service = VisualRuns(store)
    with store.transaction() as conn:
        run = service.admit(conn, 'local', 'session-test', 'lesson-two', {'title': 'Damping', 'sources': []}, 'Now add air resistance', 'edit-key')
    assert run['brief']['editTarget']['id'] == 'visual_parent'
    job = records.claim(run['jobId'], lease_seconds=240)
    html = PENDULUM_HTML
    edited = GeneratedVisual(id='temporary', renderer='open_generative_ui', title='Pendulum',
                             content={'html': [html], 'htmlComplete': True, 'generating': False}, controls=extract_controls(html),
                             control_values={'gravity': 3.7},
                             lineage={'rootId': 'visual_parent', 'parentId': 'visual_parent', 'parentRevision': 3, 'version': 2})
    foreign = edited.model_copy(update={'lineage': edited.lineage.model_copy(update={'parent_id': 'visual_missing'})})
    with store.transaction() as conn:
        result = service.commit(conn, job, [edited.model_dump(mode='json', by_alias=True), foreign.model_dump(mode='json', by_alias=True)])
    kept, dropped = (records.read('local', ref['id'], 'generated_visual')['spec'] for ref in result['artifactRefs'])
    assert kept['lineage']['parentId'] == 'visual_parent' and kept['controlValues'] == {'gravity': 3.7}
    assert dropped['lineage'] is None
    # The parent is untouched: an edit never mutates the earlier version.
    assert records.read('local', 'visual_parent', 'generated_visual')['spec']['revision'] == 3
