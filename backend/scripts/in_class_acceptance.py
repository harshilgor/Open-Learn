"""Deterministic acceptance probes; defaults to a fresh disposable SQLite DB.

Run: python -m backend.scripts.in_class_acceptance --output work/in-class-acceptance.json
Optional PostgreSQL: set OPENLEARN_ACCEPTANCE_DATABASE_URL to a NEW EMPTY database
named openlearn_acceptance_*. Existing databases are refused before migrations.
This is local evidence, never a real-provider/device/hosted acceptance claim.
"""
from __future__ import annotations

import argparse
import sys
import hashlib
import json
import os
import platform
import time
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


class NotesProvider:
    def complete_json(self, prompt, tokens=4000):
        evidence = json.loads(prompt.split('\n', 1)[1])
        return {'blocks': [{'title': 'Deterministic class notes', 'body': evidence[0]['text'], 'segmentIds': [evidence[0]['id']]}]}


class PagedTranscriber:
    def __init__(self, count):
        self.count = count
    def transcribe_chunk(self, content, mime, duration, previous):
        from backend.app.lecture_provider import TranscribedSpan, TranscriptionResult
        return TranscriptionResult('acceptance-fake', 'deterministic', [
            TranscribedSpan(index * 200, (index + 1) * 200, f'Cell membrane evidence number {index} supports cell structure.')
            for index in range(self.count)
        ])


def isolated_location(folder, allow_remote):
    configured = os.getenv('OPENLEARN_ACCEPTANCE_DATABASE_URL')
    if not configured:
        return folder / 'acceptance.sqlite'
    url = make_url(configured)
    if not url.drivername.startswith('postgresql') or not (url.database or '').startswith('openlearn_acceptance_'):
        raise ValueError('Use only a PostgreSQL database named openlearn_acceptance_*; application DATABASE_URL is never used.')
    if not allow_remote and url.host not in {'localhost', '127.0.0.1', '::1'}:
        raise ValueError('Remote PostgreSQL requires --allow-remote-test-db and an isolated empty acceptance database.')
    probe = create_engine(configured)
    try:
        if inspect(probe).get_table_names():
            raise ValueError('Acceptance database must be empty. Refusing to migrate an existing database.')
    finally:
        probe.dispose()
    return configured


def run(folder, location):
    from backend.app.storage import Store
    from backend.app.in_class_models import ClassCreate
    from backend.app.in_class_service import InClassService
    from backend.app.lecture_service import LectureService
    from backend.app.lecture_pipeline import transcribe_chunk
    from backend.app import in_class_metrics as metrics

    os.environ['AI_TUTOR_NOTE_VAULT_DIR'] = str(folder / 'notes')
    os.environ['AI_TUTOR_RECORDINGS_DIR'] = str(folder / 'audio')
    os.environ['OPENLEARN_MIGRATE_ON_START'] = 'true'
    db = Store(location)
    try:
        service = InClassService(db, NotesProvider())
        owner = 'acceptance-' + uuid4().hex
        def create():
            command = ClassCreate(recording={'id': 'rec_' + uuid4().hex, 'title': 'Acceptance class', 'startedAtMs': 1000}, deviceId='acceptance-phone', policy={'notes': True, 'materials': False, 'practice': False, 'flashcards': False})
            return command, service.create(owner, command)
        command, initial = create()
        class_id = initial['session']['id']
        checks = {}
        assert service.create(owner, command)['session']['id'] == class_id
        try:
            service.create(owner, command.model_copy(update={'device_id': 'other-phone'}))
            raise AssertionError('Conflicting device setup accepted')
        except HTTPException as error:
            assert error.status_code == 409
        assert service.snapshot(owner, class_id)['session']['id'] == class_id
        try:
            service.snapshot('foreign-owner', class_id)
            raise AssertionError('Foreign-owner read accepted')
        except HTTPException as error:
            assert error.status_code == 404
        checks['idempotent_setup_device_conflict_owner_scoped_read'] = True

        content = b'\x1a\x45\xdf\xa3' + b'a' * 50
        for sequence, count, start in ((0, 150, 0), (1, 55, 30000)):
            LectureService(db).put_chunk(owner, command.recording.id, sequence, content, start_ms=start, end_ms=start + count * 200, media_type='audio/webm', checksum=hashlib.sha256(content).hexdigest())
            assert transcribe_chunk(db, owner, command.recording.id, sequence, PagedTranscriber(count))
        for _ in range(12):
            service.tick(4)
        with db.engine.connect() as conn:
            payload = json.loads(conn.execute(text('SELECT payload FROM class_sessions WHERE id=:id'), {'id': class_id}).scalar_one())
        assert payload['coordinatorSegmentCount'] == 205
        stage = service.metrics(owner, class_id)['stages']['coordination']
        assert stage['counters']['segmentsRead'] >= 205
        with db.engine.connect() as conn:
            reads = [json.loads(value).get('segmentsRead', 0) for value in conn.execute(text("SELECT counters_json FROM class_processing_metrics WHERE class_id=:id AND stage='coordination'"), {'id': class_id}).scalars()]
        assert max(reads) <= 100 and sum(reads) == 205
        snap = service.snapshot(owner, class_id)
        assert any(output['kind'] == 'notes' and output['status'] == 'ready' for output in snap['outputs'])
        replay = service.snapshot(owner, class_id, snap['cursor'], initialized=True)
        assert replay['delta'] and replay['events'] == []
        checks['205_segments_paged_at_100_and_live_notes_before_stop'] = True
        checks['multi_view_snapshot_cursor_replay'] = True

        _, second = create()
        other_id = second['session']['id']
        for target in (class_id, other_id):
            for index in range(3):
                service.jobs.enqueue(owner, target, 'class_specialist', {'probe': index}, 'acceptance-interactive:' + target + ':' + str(index), queue='interactive', priority=100)
            service.jobs.enqueue(owner, target, 'class_specialist', {'probe': 'batch'}, 'acceptance-batch:' + target, queue='batch', priority=0)
        selected = []
        def execute(job, **kwargs):
            selected.append((job['target_id'], job['queue']))
            with db.transaction() as conn:
                service.jobs.finish(conn, job, {'acceptanceProbe': True})
            return 'completed'
        service.execute = execute
        service.tick(4)
        assert len(selected) == 4 and {target for target, _ in selected} == {class_id, other_id}
        assert max(Counter(target for target, _ in selected).values()) <= 2
        assert any(queue == 'batch' for _, queue in selected)
        checks['cross_class_fairness_two_per_class_reserved_batch_slot'] = True

        with db.transaction() as conn:
            for index in range(10):
                metrics.record(conn, owner=owner, class_id=class_id, stage='acceptance-percentile', correlation_id=index, started_at=100 + index, finished_at=100 + index + (index + 1) / 1000)
        percentile = service.metrics(owner, class_id)['stages']['acceptance-percentile']
        assert percentile['runP50Ms'] == 5.0 and percentile['runP90Ms'] == 9.0
        retention_base = time.time() + 100
        with db.transaction() as conn:
            for index in range(metrics.MAX_SAMPLES_PER_CLASS + 1):
                metrics.record(conn, owner=owner, class_id=other_id, stage='acceptance-retention', correlation_id=index, started_at=retention_base + index, finished_at=retention_base + index + 0.01)
        retained = service.metrics(owner, other_id)['stages']['acceptance-retention']
        assert retained['sampleCount'] == metrics.MAX_SAMPLES_PER_CLASS
        with db.engine.connect() as conn:
            assert metrics.summarize(conn, 'foreign-owner', class_id)['stages'] == {}
        checks['metrics_nearest_rank_percentiles_retention_owner_scope'] = True
        return {'environment': platform.platform(), 'databaseDialect': db.engine.dialect.name, 'provider': 'deterministic/no network', 'checks': checks, 'coordination': stage, 'acceptedSegments': 205, 'notExercised': ['real providers', 'native devices', 'screen readers', 'hosted services', 'PostgreSQL unless explicitly configured']}
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--allow-remote-test-db', action='store_true')
    args = parser.parse_args()
    work = Path('work'); work.mkdir(exist_ok=True)
    started = time.time()
    folder = work / ('in-class-acceptance-' + uuid4().hex)
    folder.mkdir()
    result = run(folder, isolated_location(folder, args.allow_remote_test_db))
    result['localEvidenceDirectory'] = str(folder.resolve())
    result['elapsedSeconds'] = round(time.time() - started, 3)
    rendered = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + '\n', encoding='utf-8')
    print(rendered)


if __name__ == '__main__':
    main()
