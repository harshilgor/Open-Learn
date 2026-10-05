import base64
import hashlib
import json
import os
import re
import time
from pathlib import Path
from datetime import datetime
from sqlalchemy import text
from .contracts import Observation
from .policy import check_url
from .store import AssistantStore
from ..identity import fail
from ..object_storage import LocalImmutableObjects, S3ImmutableObjects
from ..workflow_store import uid, encoded


def evidence_objects(store):
    if os.getenv('OPENLEARN_ASSISTANT_S3_BUCKET'):
        import boto3
        return S3ImmutableObjects(boto3.client('s3',endpoint_url=os.getenv('OPENLEARN_ASSISTANT_S3_ENDPOINT') or os.getenv('OPENLEARN_OBJECT_ENDPOINT') or None), os.environ['OPENLEARN_ASSISTANT_S3_BUCKET'], prefix='assistant')
    from sqlalchemy.engine import make_url
    database = make_url(store.url).database
    root = Path(os.getenv('OPENLEARN_ASSISTANT_OBJECTS_DIR') or (str(Path(database).parent / 'assistant-objects') if database and not database.startswith('file:') else 'backend/data/assistant-objects'))
    return LocalImmutableObjects(root)


def retain_snapshot(store, conn, run, connection, observation):
    check_url(observation.url, connection)
    data = observation.model_dump(by_alias=True, exclude_none=True)
    data['id'] = uid('snapshot')
    if observation.screenshot:
        try: image = base64.b64decode(observation.screenshot, validate=True)
        except ValueError: fail('invalid_input', 'Invalid screenshot encoding.', 422)
        if len(image) > 2_000_000: fail('invalid_input', 'Screenshot exceeds 2 MB.', 413)
        key = uid('image')
        digest = evidence_objects(store).put(run['owner_id'], key, image)
        conn.execute(text('INSERT INTO assistant_objects(id,owner_id,object_key,sha256,expires_at) VALUES(:id,:owner,:key,:sha,:expires)'),
                     {'id': key, 'owner': run['owner_id'], 'key': key, 'sha': digest, 'expires': time.time()+86400})
        data.pop('screenshot', None)
        data['imageObject'] = key
    # Never persist unbounded platform responses or login observations.
    raw = encoded(data)
    if len(raw) > 2_000_000: fail('invalid_input', 'Page observation is too large.', 413)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    conn.execute(text('INSERT INTO browser_snapshots(id,owner_id,run_id,connection_id,url,sha256,payload,created_at,expires_at) VALUES(:id,:owner,:run,:connection,:url,:sha,:payload,:now,:expires)'),
                 {'id': data['id'], 'owner': run['owner_id'], 'run': run['id'], 'connection': connection['id'], 'url': observation.url,
                  'sha': digest, 'payload': raw, 'now': time.time(), 'expires': time.time()+86400})
    return data


def date_supported(value, quote):
    if not value or value.kind in {'unknown', 'timezone_unknown'}: return True
    if not value.value: return False
    try:
        parsed = datetime.fromisoformat(value.value.replace('Z', '+00:00'))
    except ValueError:
        return False
    if value.kind == 'instant' and parsed.tzinfo is None: return False
    if value.value in quote: return True
    if value.kind == 'date_only' and value.value[:10] in quote: return True
    normalized = quote.lower()
    month = parsed.strftime('%B').lower()
    short = parsed.strftime('%b').lower()
    day = str(parsed.day)
    # A year must be supported; no defaulting an old syllabus into the current year.
    if str(parsed.year) not in quote: return False
    months = '(?:' + re.escape(month) + '|' + re.escape(short) + r'\.?)'
    month_matches = re.search(r'\b' + months + r'\s+' + day + r'(?:st|nd|rd|th)?[,]?\s+' + str(parsed.year) + r'\b', normalized) or re.search(r'\b' + day + r'\s+' + months + r'[,]?\s+' + str(parsed.year) + r'\b', normalized)
    numeric = re.search(r'\b0?' + str(parsed.month) + r'[/\-]0?' + str(parsed.day) + r'[/\-]' + str(parsed.year) + r'\b', quote)
    if not (month_matches or numeric): return False
    # A precise instant also requires an explicit time and timezone representation.
    if value.kind == 'instant':
        return parsed.strftime('%H:%M') in quote and (re.search(r'Z|[+-]\d\d:\d\d|UTC|GMT', quote) is not None)
    return True


def validate_candidate(candidate, snapshots):
    snapshot = next((s for s in snapshots if s['id'] == candidate.snapshot_id), None)
    if not snapshot: fail('invalid_evidence', 'The model cited an unavailable page.', 422)
    block = next((b for b in snapshot.get('blocks', []) if b['ref'] == candidate.block_ref), None)
    visual = candidate.block_ref == 'vision' and snapshot.get('imageObject') and candidate.image_region is not None
    if visual:
        x,y,width,height = candidate.image_region
        if not all(0 <= n <= 1 for n in (x,y,width,height)) or width == 0 or height == 0 or x+width>1 or y+height>1:
            fail('invalid_evidence', 'Visual evidence requires a bounded image region.', 422)
        candidate.confirmation = 'tentative'
    elif not block or candidate.quote not in block['text']:
        fail('invalid_evidence', 'The cited passage does not support this fact.', 422)
    if candidate.kind == 'assessment' and not re.search(r'\b(midterm|exam|final examination|test)\b', candidate.quote, re.I):
        fail('invalid_evidence', 'Exam dates require an explicit exam reference.', 422)
    if not date_supported(candidate.date, candidate.quote):
        fail('invalid_evidence', 'The source does not support this precise date.', 422)
    if candidate.end and not date_supported(candidate.end, candidate.quote):
        fail('invalid_evidence', 'The source does not support the end time.', 422)
    return snapshot


def source_record(snapshot, connection, quote, ref):
    from .policy import safe_url
    return {'locator': safe_url(snapshot['url']), 'revision': snapshot['documentRevision'], 'connectionId': connection['id'],
            'snapshotId': snapshot['id'], 'blockRef': ref, 'quote': quote, 'studentSpecific': bool(snapshot.get('accountId')),
            'accountId': snapshot.get('accountId'), 'extractionMethod': 'visual_needs_review' if ref == 'vision' else 'structured_page', 'observedAt': datetime.now().astimezone().isoformat()}
