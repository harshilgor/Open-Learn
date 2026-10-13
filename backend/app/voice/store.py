"""Transactional receipts and ordered replay; no process-local ownership locks."""
import hashlib
import json
import time
from uuid import uuid4
from sqlalchemy import text
from ..identity import assert_owner_active, fail


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def fingerprint(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def identifier(prefix):
    return prefix + '_' + uuid4().hex


class VoiceStore:
    def __init__(self, store):
        self.store = store

    def session(self, owner, sid, conn=None, active=False):
        if conn is None:
            with self.store.engine.connect() as connection:
                return self.session(owner, sid, connection, active)
        assert_owner_active(conn, owner)
        row = conn.execute(text('SELECT * FROM voice_sessions WHERE id=:id AND owner_id=:owner'), {'id': sid, 'owner': owner}).mappings().first()
        if not row:
            fail('not_found', 'Voice session unavailable.', 404)
        if active and (row['status'] != 'active' or row['expires_at'] <= time.time()):
            fail('voice_ended', 'This voice session has ended.', 409)
        return {**dict(row), 'context': json.loads(row['payload'])}

    def emit(self, conn, owner, sid, kind, data):
        # UPDATE locks the session and allocates a monotonic sequence atomically.
        seq = conn.execute(text('UPDATE voice_sessions SET sequence=sequence+1 WHERE id=:id AND owner_id=:owner RETURNING sequence'), {'id': sid, 'owner': owner}).scalar_one()
        event = {'sequence': seq, 'type': kind, 'voiceSessionId': sid, **data}
        conn.execute(text('INSERT INTO voice_events(id,owner_id,session_id,sequence,created_at,payload) VALUES(:id,:owner,:sid,:seq,:now,:payload)'),
                     {'id': identifier('ve'), 'owner': owner, 'sid': sid, 'seq': seq, 'now': time.time(), 'payload': encode(event)})
        return event

    def events(self, owner, sid, after=0):
        with self.store.engine.connect() as conn:
            self.session(owner, sid, conn)
            return [json.loads(r) for r in conn.execute(text('SELECT payload FROM voice_events WHERE session_id=:sid AND owner_id=:owner AND sequence>:seq ORDER BY sequence LIMIT 200'), {'sid': sid, 'owner': owner, 'seq': after}).scalars()]

    def record(self, conn, table, owner, sid, key, payload, status='queued'):
        if table not in {'turns', 'actions', 'speech_segments'}:
            raise ValueError('Unknown voice record')
        digest = fingerprint(payload)
        rid = identifier(table)
        result = conn.execute(text(f'INSERT INTO voice_{table}(id,owner_id,session_id,command_key,request_hash,status,created_at,payload) VALUES(:id,:owner,:sid,:key,:hash,:status,:now,:payload) ON CONFLICT(session_id,command_key) DO NOTHING'),
                              {'id': rid, 'owner': owner, 'sid': sid, 'key': key, 'hash': digest, 'status': status, 'now': time.time(), 'payload': encode(payload)})
        row = conn.execute(text(f'SELECT * FROM voice_{table} WHERE session_id=:sid AND command_key=:key AND owner_id=:owner'), {'sid': sid, 'key': key, 'owner': owner}).mappings().one()
        if row['request_hash'] != digest:
            fail('idempotency_conflict', 'That utterance or action already has different content.', 409)
        return {**dict(row), 'data': json.loads(row['payload'])}, result.rowcount == 1

    def update(self, conn, table, owner, rid, status, payload):
        if table not in {'turns', 'actions', 'speech_segments'}:
            raise ValueError('Unknown voice record')
        conn.execute(text(f'UPDATE voice_{table} SET status=:status,payload=:payload WHERE id=:id AND owner_id=:owner'), {'status': status, 'payload': encode(payload), 'id': rid, 'owner': owner})

    def records(self, owner, sid, table, statuses=None):
        if table not in {'turns', 'actions', 'speech_segments'}:
            raise ValueError('Unknown voice record')
        with self.store.engine.connect() as conn:
            self.session(owner, sid, conn)
            rows = conn.execute(text(f'SELECT * FROM voice_{table} WHERE session_id=:sid AND owner_id=:owner ORDER BY created_at LIMIT 200'), {'sid': sid, 'owner': owner}).mappings()
            return [{**dict(r), 'data': json.loads(r['payload'])} for r in rows if statuses is None or r['status'] in statuses]

    def end(self, owner, sid, reason='user'):
        with self.store.transaction() as conn:
            session = self.session(owner, sid, conn)
            if session['status'] == 'ended':
                return session
            conn.execute(text("UPDATE voice_sessions SET status='ended',epoch=epoch+1 WHERE id=:id AND owner_id=:owner"), {'id': sid, 'owner': owner})
            seconds = max(0, min(session['expires_at'], time.time()) - session['created_at'])
            conn.execute(text('UPDATE voice_usage SET settled_seconds=:seconds WHERE session_id=:sid AND settled_seconds IS NULL'), {'seconds': int(seconds), 'sid': sid})
            conn.execute(text("UPDATE voice_actions SET status='cancelled' WHERE session_id=:sid AND status='awaiting_confirmation'"), {'sid': sid})
            self.emit(conn, owner, sid, 'session.ended', {'reason': reason})
            return self.session(owner, sid, conn)
