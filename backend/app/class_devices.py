"""Owner-scoped phone pairing and acknowledged recording-device control."""
import hashlib
import hmac
import json
import secrets
import time
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text

from .in_class_models import ClassCreate
from .in_class_service import InClassService
from .lecture_service import LectureService
from .workflow_store import encoded


def error(code, message, status=409):
    raise HTTPException(status, {'code': code, 'message': message})


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class ClassDeviceService:
    def __init__(self, store):
        self.store = store
        self.classes = InClassService(store)

    @staticmethod
    def cleanup(conn,limit=25):
        now=time.time()
        expired=conn.execute(text("SELECT id FROM class_pairings WHERE state='pending' AND expires_at<:now ORDER BY expires_at LIMIT :limit"),{'now':now,'limit':limit}).scalars().all()
        for identifier in expired:
            conn.execute(text("UPDATE class_pairings SET state='expired' WHERE id=:id AND state='pending'"),{'id':identifier})
        rates=conn.execute(text('SELECT id FROM class_pairing_rates WHERE window_start<:before ORDER BY window_start LIMIT :limit'),{'before':now-86400,'limit':limit}).scalars().all()
        for identifier in rates:conn.execute(text('DELETE FROM class_pairing_rates WHERE id=:id AND window_start<:before'),{'id':identifier,'before':now-86400})
        rows=conn.execute(text("SELECT id,owner_id,payload FROM class_sessions WHERE created_at<:before AND payload LIKE '%awaiting-phone-%' AND payload NOT LIKE :expired AND NOT EXISTS (SELECT 1 FROM class_capture_runs r WHERE r.class_id=class_sessions.id) AND NOT EXISTS (SELECT 1 FROM lecture_audio_chunks a WHERE a.recording_id=class_sessions.recording_id) ORDER BY created_at LIMIT :limit"),{'before':now-86400,'limit':limit,'expired':'%"draftExpired":true%'}).mappings().all()
        for row in rows:
            saved=json.loads(row['payload'])
            if str(saved.get('deviceId','')).startswith('awaiting-phone-') and not saved.get('draftExpired'):
                saved.update(draftExpired=True,cancelled=True)
                conn.execute(text('UPDATE class_sessions SET payload=:payload,revision=revision+1 WHERE id=:id AND owner_id=:owner'),{'id':row['id'],'owner':row['owner_id'],'payload':encoded(saved)})

    def draft(self, owner, body):
        from .class_features import require
        require('phonePairing')
        recording = 'rec_' + digest(owner + ':' + body.commandId)[:32]
        result = self.classes.create(owner, ClassCreate(recording={'id': recording, 'title': body.title, 'courseId': body.courseId,
            'buddyId': body.buddyId, 'startedAtMs': body.startedAtMs, 'preferences': {'keepAudio': body.policy.keepAudio if body.policy.keepAudio is not None else True}},
            deviceId='awaiting-phone-' + digest(body.deviceId)[:24], materialVersionIds=body.materialVersionIds, policy=body.policy))
        return result

    def rate(self, owner, device, network):
        # Hashed dimensions avoid storing IP addresses. Authenticated owner is
        # required before any claim; each dimension has an independent budget.
        now = time.time()
        with self.store.transaction() as conn:
            for dimension in (owner, 'device:' + owner + ':' + device, 'network:' + network):
                key = digest(dimension)
                row = conn.execute(text('SELECT window_start,attempts FROM class_pairing_rates WHERE id=:id'), {'id': key}).first()
                if row and now - row[0] < 60:
                    if row[1] >= 10:
                        error('pairing_rate_limited', 'Too many pairing attempts. Wait one minute.', 429)
                    conn.execute(text('UPDATE class_pairing_rates SET attempts=attempts+1 WHERE id=:id'), {'id': key})
                else:
                    conn.execute(text('INSERT INTO class_pairing_rates(id,owner_id,window_start,attempts) VALUES(:id,:owner,:now,1) ON CONFLICT(id) DO UPDATE SET window_start=:now,attempts=1'), {'id': key, 'owner': owner, 'now': now})

    def pairing(self, owner, class_id, body):
        from .class_features import require
        require('phonePairing')
        self.rate(owner, body.deviceId, 'pair-issue:' + owner)
        with self.store.transaction() as conn:
            item = self.classes.row(conn, owner, class_id, True)
            if item.get('draftExpired'):error('draft_expired','This empty class draft expired. Start a new class.')
            active = conn.execute(text('SELECT state FROM class_capture_runs WHERE owner_id=:owner AND class_id=:class ORDER BY epoch DESC LIMIT 1'), {'owner': owner, 'class': class_id}).scalar_one_or_none()
            if active and active not in {'stopped', 'interrupted'}:
                error('capture_owned', 'Stop or acknowledge the current recording device before switching.')
            if not item['deviceId'].startswith('awaiting-phone-') and active is None:
                error('capture_owned', 'This class already records on its original device. Start a phone class from setup.')
            prior = conn.execute(text('SELECT id,payload,expires_at FROM class_pairings WHERE owner_id=:owner AND class_id=:class AND state=\'pending\' ORDER BY expires_at DESC LIMIT 1'), {'owner': owner, 'class': class_id}).mappings().first()
            if prior and json.loads(prior['payload']).get('commandId') == body.commandId and prior['expires_at'] > time.time():
                # Challenge is intentionally not stored in plaintext. A refresh
                # creates a new challenge and revokes the unavailable prior one.
                conn.execute(text('UPDATE class_pairings SET state=\'revoked\' WHERE id=:id'), {'id': prior['id']})
            conn.execute(text('UPDATE class_pairings SET state=\'revoked\' WHERE owner_id=:owner AND class_id=:class AND state=\'pending\''), {'owner': owner, 'class': class_id})
            code = ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(12))
            identifier, expiry = 'pair_' + uuid4().hex, time.time() + 120
            conn.execute(text('INSERT INTO class_pairings(id,owner_id,class_id,challenge_hash,state,expires_at,payload) VALUES(:id,:owner,:class,:hash,\'pending\',:expires,:payload)'), {'id': identifier, 'owner': owner, 'class': class_id, 'hash': digest(code), 'expires': expiry, 'payload': encoded({'commandId': body.commandId, 'requestingDeviceId': body.deviceId, 'requestingDeviceName':body.deviceName, 'title': item['title']})})
            link = 'openlearn://class-pair?code=' + code
            import qrcode
            from qrcode.image.svg import SvgPathImage
            svg = qrcode.make(link, image_factory=SvgPathImage).to_string().decode()
            return {'id': identifier, 'classId': class_id, 'code': code, 'expiresAt': expiry, 'deepLink': link, 'qrSvg': svg, 'title': item['title']}

    def preview(self, owner, body, network='local'):
        from .class_features import require
        require('phonePairing')
        self.rate(owner, body.deviceId, network)
        code_hash=digest(body.code.strip().upper().replace('-', '').replace(' ', ''))
        with self.store.engine.connect() as conn:
            row=conn.execute(text('SELECT * FROM class_pairings WHERE challenge_hash=:hash AND owner_id=:owner'),{'hash':code_hash,'owner':owner}).mappings().first()
            if not row:error('pairing_unavailable','This pairing code is unavailable.',404)
            if row['state']!='pending' or row['expires_at']<=time.time():error('pairing_expired','This pairing code expired or was used. Generate a new one.')
            item=self.classes.row(conn,owner,row['class_id'])
            if item.get('draftExpired'):error('draft_expired','This empty class draft expired. Start a new class.')
            saved=json.loads(row['payload'])
            return {'pairingId':row['id'],'classId':row['class_id'],'title':item['title'],'ownerId':owner,'expiresAt':row['expires_at'],
                    'requestingDeviceId':saved['requestingDeviceId'],'requestingDeviceName':saved.get('requestingDeviceName','Open Learn laptop')}

    def claim(self, owner, body, network='local'):
        from .class_features import require
        require('phonePairing')
        if not body.consent:
            error('recording_consent_required', 'Confirm permission to record on the phone.', 422)
        self.rate(owner, body.deviceId, network)
        code_hash = digest(body.code.strip().upper().replace('-', '').replace(' ', ''))
        with self.store.transaction() as conn:
            row = conn.execute(text('SELECT * FROM class_pairings WHERE challenge_hash=:hash AND owner_id=:owner'), {'hash': code_hash, 'owner': owner}).mappings().first()
            if not row:
                error('pairing_unavailable', 'This pairing code is unavailable.', 404)
            saved = json.loads(row['payload'])
            if row['state'] == 'claimed':
                if saved.get('claimCommandId') != body.commandId or saved.get('claimedDeviceId') != body.deviceId or not hmac.compare_digest(saved.get('capabilityHash', ''), digest(body.captureCapability)):
                    error('pairing_used', 'This pairing code has already been used.')
                run = self.run(conn, owner, row['class_id'], saved['runId'])
                return self.claim_payload(conn, owner, row['class_id'], run)
            if row['state'] != 'pending' or row['expires_at'] <= time.time():
                error('pairing_expired', 'This pairing code expired. Generate a new one.')
            item = self.classes.row(conn, owner, row['class_id'], True)
            if item.get('draftExpired'):error('draft_expired','This empty class draft expired. Start a new class.')
            recording = LectureService(self.store)._row(owner, item['recordingId'], conn)
            if recording['expected_chunk_count'] is not None:
                error('class_finished', 'This class has finished. Start a new recording.')
            prior = conn.execute(text('SELECT * FROM class_capture_runs WHERE owner_id=:owner AND class_id=:class ORDER BY epoch DESC LIMIT 1'), {'owner': owner, 'class': row['class_id']}).mappings().first()
            if prior and prior['state'] not in {'stopped', 'interrupted'}:
                error('capture_owned', 'The current recording device has not acknowledged stopping.')
            previous = json.loads(prior['payload']) if prior else {}
            if previous.get('endClass'):
                error('class_end_pending', 'This class has a confirmed Stop. Start a new class to record more.')
            epoch = prior['epoch'] + 1 if prior else item.get('captureEpoch', 1)
            run_id = 'run_' + uuid4().hex
            payload = {'recordingId': item['recordingId'], 'sequenceBase': previous.get('sequenceBase', 0) + previous.get('sealedChunkCount', 0),
                       'startMs': previous.get('audioEndMs', 0), 'audioEndMs': previous.get('audioEndMs', 0), 'sealedChunkCount': 0,
                       'capabilityHash': digest(body.captureCapability), 'consentGrantedAt': time.time(), 'endClass': False}
            conn.execute(text('INSERT INTO class_capture_runs(id,owner_id,class_id,device_id,epoch,state,last_seen_at,payload) VALUES(:id,:owner,:class,:device,:epoch,\'paired\',:now,:payload)'), {'id': run_id, 'owner': owner, 'class': row['class_id'], 'device': body.deviceId, 'epoch': epoch, 'now': time.time(), 'payload': encoded(payload)})
            item.update(deviceId=body.deviceId, captureEpoch=epoch, captureCapabilityHash=payload['capabilityHash'], activeRunId=run_id)
            self.classes.save(conn, item)
            self.classes.event(conn, item, 'capture.paired', {'runId': run_id, 'deviceId': body.deviceId, 'epoch': epoch})
            saved.update(claimCommandId=body.commandId, claimedDeviceId=body.deviceId, capabilityHash=payload['capabilityHash'], runId=run_id)
            changed = conn.execute(text('UPDATE class_pairings SET state=\'claimed\',payload=:payload WHERE id=:id AND state=\'pending\''), {'id': row['id'], 'payload': encoded(saved)})
            if changed.rowcount != 1:
                error('pairing_used', 'This pairing code was claimed by another request.')
            run = self.run(conn, owner, row['class_id'], run_id)
            return self.claim_payload(conn, owner, row['class_id'], run)

    def run(self, conn, owner, class_id, run_id):
        lock = ' FOR UPDATE' if conn.dialect.name == 'postgresql' else ''
        row = conn.execute(text('SELECT * FROM class_capture_runs WHERE id=:id AND owner_id=:owner AND class_id=:class' + lock), {'id': run_id, 'owner': owner, 'class': class_id}).mappings().first()
        if not row:
            error('run_unavailable', 'This recording device is unavailable.', 404)
        return {**row, 'payload': json.loads(row['payload'])}

    def claim_payload(self, conn, owner, class_id, run):
        item = self.classes.row(conn, owner, class_id)
        return {'classId': class_id, 'recordingId': item['recordingId'], 'sessionId': item['sessionId'], 'title': item['title'], 'courseId': item.get('courseId'),
                'speechQuality':item.get('policy',{}).get('speechQuality','balanced'),
                'runId': run['id'], 'epoch': run['epoch'], 'revision': run['revision'], 'sequenceBase': run['payload']['sequenceBase'], 'startMs': run['payload']['startMs']}

    def heartbeat(self, owner, class_id, run_id, body, capability):
        with self.store.transaction() as conn:
            item = self.classes.row(conn, owner, class_id, True)
            run = self.run(conn, owner, class_id, run_id)
            data = run['payload']
            if not hmac.compare_digest(data['capabilityHash'], digest(capability)):
                error('capture_capability_mismatch', 'This recording capability is invalid.')
            if item.get('activeRunId') != run_id:
                error('stale_capture_epoch', 'A newer device owns this class. Stop this microphone and upload saved audio through recovery.')
            if run['state'] in {'stopped', 'interrupted'} and body.state not in {'stopped', 'interrupted'}:
                error('fresh_capture_required', 'A stopped run cannot restart. Pair a new capture with permission.')
            if body.audioEndMs < data['audioEndMs'] or body.sealedChunkCount < data['sealedChunkCount']:
                error('capture_clock_conflict', 'Recording progress cannot move backward.')
            data.update(audioEndMs=body.audioEndMs, sealedChunkCount=body.sealedChunkCount, batteryPercent=body.batteryPercent, backlog=body.backlog)
            if body.endClass and body.state == 'stopped':
                data['endClass'] = True
            conn.execute(text('UPDATE class_capture_runs SET state=:state,payload=:payload,last_seen_at=:now,revision=revision+1 WHERE id=:id AND revision=:revision'), {'id': run_id, 'revision': run['revision'], 'state': body.state, 'payload': encoded(data), 'now': time.time()})
            # Resume requests expire and can never open a microphone on reconnect.
            conn.execute(text("UPDATE class_capture_commands SET state='expired',updated_at=:now WHERE owner_id=:owner AND class_id=:class AND state IN ('pending','delivered') AND json_extract(payload,'$.action')='resume' AND created_at<:expiry") if conn.dialect.name == 'sqlite' else text("UPDATE class_capture_commands SET state='expired',updated_at=:now WHERE owner_id=:owner AND class_id=:class AND state IN ('pending','delivered') AND payload::jsonb->>'action'='resume' AND created_at<:expiry"), {'owner': owner, 'class': class_id, 'now': time.time(), 'expiry': time.time() - 15})
            commands = conn.execute(text("SELECT id,state,payload FROM class_capture_commands WHERE owner_id=:owner AND class_id=:class AND state IN ('pending','delivered') ORDER BY created_at LIMIT 20"), {'owner': owner, 'class': class_id}).mappings().all()
            pending = []
            for command in commands:
                value = json.loads(command['payload'])
                if value['runId'] == run_id:
                    pending.append({'id': command['id'], **value})
                    conn.execute(text("UPDATE class_capture_commands SET state='delivered' WHERE id=:id AND state='pending'"), {'id': command['id']})
            self.classes.event(conn, item, 'capture.status', {'runId': run_id, 'state': body.state, 'audioEndMs': body.audioEndMs})
            return {'runRevision': run['revision'] + 1, 'commands': pending}

    def command(self, owner, class_id, body):
        with self.store.transaction() as conn:
            item = self.classes.row(conn, owner, class_id, True)
            identifier = 'capture_' + digest(owner + ':' + class_id + ':' + body.commandId)[:32]
            existing = conn.execute(text('SELECT payload,state FROM class_capture_commands WHERE id=:id AND owner_id=:owner'), {'id': identifier, 'owner': owner}).first()
            if existing:
                saved = json.loads(existing[0])
                if saved['action'] != body.action or saved['runId'] != body.runId:
                    error('idempotency_conflict', 'This command ID was used for another recording action.')
                return {'id': identifier, 'state': existing[1], **saved}
            run = self.run(conn, owner, class_id, body.runId)
            if item.get('activeRunId') != run['id']:
                error('stale_capture_epoch', 'This recording device has been replaced.')
            if run['revision'] != body.expectedRevision:
                error('revision_conflict', 'Recording status changed. Refresh and try again.')
            if body.action == 'resume' and run['state'] != 'paused':
                error('fresh_capture_required', 'Resume requires a paused run and phone confirmation.')
            data = {'runId': run['id'], 'epoch': run['epoch'], 'action': body.action, 'expiresAt': time.time() + (15 if body.action == 'resume' else 86400)}
            conn.execute(text('INSERT INTO class_capture_commands(id,owner_id,class_id,state,created_at,updated_at,payload) VALUES(:id,:owner,:class,\'pending\',:now,:now,:payload)'), {'id': identifier, 'owner': owner, 'class': class_id, 'now': time.time(), 'payload': encoded(data)})
            self.classes.event(conn, item, 'capture.command', {'commandId': identifier, 'action': body.action, 'state': 'pending'})
            return {'id': identifier, 'state': 'pending', **data}

    def ack(self, owner, class_id, command_id, body, capability):
        with self.store.transaction() as conn:
            item = self.classes.row(conn, owner, class_id, True)
            command = conn.execute(text('SELECT * FROM class_capture_commands WHERE id=:id AND owner_id=:owner AND class_id=:class'), {'id': command_id, 'owner': owner, 'class': class_id}).mappings().first()
            if not command:
                error('command_unavailable', 'This command is unavailable.', 404)
            data = json.loads(command['payload'])
            run = self.run(conn, owner, class_id, data['runId'])
            if item.get('activeRunId') != run['id'] or not hmac.compare_digest(run['payload']['capabilityHash'], digest(capability)):
                error('stale_capture_epoch', 'A newer recording device owns the class.')
            if command['state'] in {'acknowledged', 'rejected', 'expired'}:
                return {'id': command_id, 'state': command['state']}
            if data['action'] == 'resume' and data['expiresAt'] < time.time():
                body.accepted = False
            if body.accepted:
                expected = {'pause': 'paused', 'resume': 'recording', 'stop': 'stopped', 'handoff': 'stopped'}[data['action']]
                if body.state != expected:
                    error('capture_ack_mismatch', 'The observed microphone state does not match the command.')
                if data['action'] in {'stop', 'handoff'}:
                    if body.audioEndMs < run['payload']['audioEndMs'] or body.sealedChunkCount < run['payload']['sealedChunkCount']:
                        error('capture_clock_conflict', 'The stopped audio manifest moved backward.')
                    run['payload'].update(audioEndMs=body.audioEndMs, sealedChunkCount=body.sealedChunkCount, endClass=data['action'] == 'stop')
                conn.execute(text('UPDATE class_capture_runs SET state=:state,payload=:payload,revision=revision+1,last_seen_at=:now WHERE id=:id'), {'id': run['id'], 'state': body.state, 'payload': encoded(run['payload']), 'now': time.time()})
            state = 'acknowledged' if body.accepted else 'rejected'
            data.update(observedAt=time.time(), observedState=body.state)
            conn.execute(text('UPDATE class_capture_commands SET state=:state,payload=:payload,revision=revision+1,updated_at=:now WHERE id=:id'), {'id': command_id, 'state': state, 'payload': encoded(data), 'now': time.time()})
            self.classes.event(conn, item, 'capture.acknowledged', {'commandId': command_id, 'state': state, 'captureState': body.state})
            return {'id': command_id, 'state': state}

    def status(self, owner, class_id):
        with self.store.engine.connect() as conn:
            item = self.classes.row(conn, owner, class_id)
            row = conn.execute(text('SELECT id,device_id,epoch,state,last_seen_at,revision,payload FROM class_capture_runs WHERE owner_id=:owner AND class_id=:class ORDER BY epoch DESC LIMIT 1'), {'owner': owner, 'class': class_id}).mappings().first()
            commands = conn.execute(text('SELECT id,state,payload FROM class_capture_commands WHERE owner_id=:owner AND class_id=:class ORDER BY created_at DESC LIMIT 10'), {'owner': owner, 'class': class_id}).mappings().all()
        if not row:
            return {'run': None, 'commands': []}
        data = json.loads(row['payload'])
        return {'run': {'id': row['id'], 'deviceId': row['device_id'], 'epoch': row['epoch'], 'state': row['state'], 'revision': row['revision'],
                        'stale': time.time() - row['last_seen_at'] > 15, 'lastSeenAt': row['last_seen_at'], 'audioEndMs': data['audioEndMs'],
                        'backlog': data.get('backlog'), 'batteryPercent': data.get('batteryPercent')},
                'commands': [{'id': command['id'], 'state': command['state'], **{key: json.loads(command['payload']).get(key) for key in ('runId', 'action', 'expiresAt')}} for command in commands]}
