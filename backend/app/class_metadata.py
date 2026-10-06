"""Owner-scoped class request ledger; session JSON retains compact pointers only."""
import json
import time

from sqlalchemy import text

MAX_PAGE = 100


def _scope(conn, owner, class_id):
    if not conn.execute(text('SELECT 1 FROM class_sessions WHERE id=:class AND owner_id=:owner'), {'class': class_id, 'owner': owner}).first():
        raise LookupError('Class session is unavailable to this owner.')


def upsert_need(conn, owner, class_id, need):
    _scope(conn, owner, class_id)
    conn.execute(text('''INSERT INTO class_need_requests
        (id,owner_id,class_id,window_id,status,created_at,updated_at,payload)
        VALUES(:id,:owner,:class,:window,:status,:created,:updated,:payload)
        ON CONFLICT(owner_id,class_id,id) DO UPDATE SET
        window_id=excluded.window_id,status=excluded.status,updated_at=excluded.updated_at,payload=excluded.payload'''),
        {'id': need['id'], 'owner': owner, 'class': class_id, 'window': need.get('windowId'),
         'status': need.get('status', 'open'), 'created': float(need.get('createdAt', time.time())),
         'updated': time.time(), 'payload': json.dumps(need, separators=(',', ':'), ensure_ascii=False)})


def get_need(conn, owner, class_id, need_id):
    _scope(conn, owner, class_id)
    raw = conn.execute(text('SELECT payload FROM class_need_requests WHERE owner_id=:owner AND class_id=:class AND id=:id'),
                       {'owner': owner, 'class': class_id, 'id': need_id}).scalar_one_or_none()
    if raw is not None:
        return json.loads(raw)
    # Imported legacy profiles may postdate the migration. Read without mutating
    # on a read connection; the next locked save performs normalization.
    legacy = conn.execute(text('SELECT payload FROM class_sessions WHERE id=:class AND owner_id=:owner'), {'class': class_id, 'owner': owner}).scalar_one()
    return next((need for need in json.loads(legacy).get('needInfo', []) if need.get('id') == need_id), None)


def list_needs(conn, owner, class_id, *, after=None, limit=MAX_PAGE, status=None):
    """Stable ID keyset pages. Cursor is opaque request ID, never a SQL fragment."""
    _scope(conn, owner, class_id)
    limit = max(1, min(MAX_PAGE, int(limit)))
    conditions = ''
    params = {'owner': owner, 'class': class_id, 'limit': limit + 1}
    if after is not None:
        conditions += ' AND id>:after'; params['after'] = str(after)
    if status is not None:
        conditions += ' AND status=:status'; params['status'] = str(status)
    rows = conn.execute(text('SELECT id,payload FROM class_need_requests WHERE owner_id=:owner AND class_id=:class' + conditions + ' ORDER BY id LIMIT :limit'), params).mappings().all()
    more = len(rows) > limit
    rows = rows[:limit]
    return {'items': [json.loads(row['payload']) for row in rows], 'hasMore': more,
            'nextCursor': rows[-1]['id'] if more else None}


def migrate_legacy(conn, item):
    """Move legacy arrays within the same locked session save transaction.

    Calling repeatedly is safe. Hydrated API views must not be passed back as
    legacy arrays: mark them `_metadataView` and strip them without persisting.
    """
    owner, class_id = item['owner'], item['id']
    _scope(conn, owner, class_id)
    view = item.pop('_metadataView', False)
    needs = item.pop('needInfo', [])
    if not view:
        for need in needs:
            if isinstance(need, dict) and isinstance(need.get('id'), str):
                # Never overwrite a newer normalized entry with an old array.
                if not conn.execute(text('SELECT 1 FROM class_need_requests WHERE owner_id=:owner AND class_id=:class AND id=:id'), {'owner': owner, 'class': class_id, 'id': need['id']}).first():
                    upsert_need(conn, owner, class_id, need)
    item.pop('materialVersionIds', None)  # material_attachments is canonical.
    item.pop('needInfoNextCursor', None)
    item.pop('needInfoHasMore', None)
    item['metadataVersion'] = 1
    return item


def snapshot_view(conn, item):
    """Produce a bounded client view without hydrating coordinator state."""
    result = dict(item)
    page = list_needs(conn, item['owner'], item['id'])
    result.update(needInfo=page['items'], needInfoHasMore=page['hasMore'], needInfoNextCursor=page['nextCursor'], _metadataView=True)
    result['materialVersionIds'] = list(conn.execute(text('''SELECT version_id FROM material_attachments
        WHERE session_id=:session ORDER BY version_id LIMIT :limit'''), {'session': item.get('sessionId'), 'limit': MAX_PAGE}).scalars())
    return result


def payload_measurement(item):
    """Diagnostic sizes for actual JSON fields, avoiding invented scale claims."""
    encode = lambda value: len(json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))
    return {'bytes': encode(item), 'fields': {key: encode(value) for key, value in item.items()}}
