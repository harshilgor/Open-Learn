"""Durable, revision-fenced hierarchy for long class summaries and recall.

The hierarchy is stored in the existing immutable class input-window ledger.
Its specialist results use the existing class output and learning-job ledgers,
so a process restart resumes queued leaves and parents without a new scheduler.
"""
import hashlib
import json

from sqlalchemy import bindparam, text


def _fingerprint(value):
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


VERSION = 1
DIRECT_WINDOW_LIMIT = 6
LEAF_WINDOW_FANOUT = 2
MERGE_FANOUT = 6
REVISION_CHECK_WINDOW_PAGE = 100
REVISION_CHECK_SEGMENT_PAGE = 500
PACKAGE_PLAN_PAGE = 100


def advance_package_plan_page(conn, item, package_id, package, now, schedule_leaf, schedule_ready):
    """Build one bounded page of a durable synthesis plan.

    A page reads at most 100 source IDs and writes at most 50 leaf nodes per
    modality (or 16 merge nodes per modality). Progress lives in the package
    record; each continuation is emitted by the caller in the same transaction.
    """
    state = package.get('synthesisBuild')
    if not state:
        return package, True

    level = int(state['level'])
    cursor = int(state.get('cursor', 0))
    source_count = int(state['sourceCount'])
    fanout = LEAF_WINDOW_FANOUT if level == 0 else MERGE_FANOUT
    limit = max(fanout, (PACKAGE_PLAN_PAGE // fanout) * fanout)
    limit = min(limit, source_count - cursor)
    if limit <= 0:
        raise ValueError('Synthesis plan cursor exceeded its source count')

    transcript_rows = None
    if level == 0:
        transcript_rows = conn.execute(text("""SELECT window_id FROM class_session_window_membership
            WHERE owner_id=:owner AND class_id=:class AND set_id=:package AND purpose='transcript'
              AND ordinal>=:cursor ORDER BY ordinal LIMIT :limit"""), {
            'owner': item['owner'], 'class': item['id'], 'package': package_id,
            'limit': limit, 'cursor': cursor,
        }).scalars().all()
        if len(transcript_rows) != limit:
            raise ValueError('Synthesis plan source page is incomplete')

    for modality in ('summary', 'recall'):
        if level == 0:
            rows = transcript_rows
            child_kind = 'transcript'
        else:
            rows = conn.execute(text("""SELECT node_id FROM class_synthesis_plan_membership
                WHERE owner_id=:owner AND class_id=:class AND package_id=:package
                  AND modality=:modality AND level=:level AND ordinal>=:cursor
                ORDER BY ordinal LIMIT :limit"""), {
                'owner': item['owner'], 'class': item['id'], 'package': package_id,
                'modality': modality, 'level': level - 1, 'limit': limit, 'cursor': cursor,
            }).scalars().all()
            child_kind = 'synthesis'
        if len(rows) != limit:
            raise ValueError('Synthesis plan source page is incomplete')
        for group_offset in range(0, len(rows), fanout):
            children = rows[group_offset:group_offset + fanout]
            ordinal = (cursor // fanout) + (group_offset // fanout)
            node_id = 'synthesis_' + _fingerprint([
                item['id'], package_id, modality, level, ordinal, children,
            ])
            node_payload = {
                'type': 'hierarchical_synthesis',
                'packageWindow': package_id,
                'modality': modality,
                'level': level,
                'children': children,
                'childKind': child_kind,
                'parentId': None,
            }
            conn.execute(text("""INSERT INTO class_input_windows
                (id,owner_id,class_id,kind,revision,payload,created_at)
                VALUES(:id,:owner,:class,'synthesis',1,:payload,:now)
                ON CONFLICT(id) DO NOTHING"""), {
                'id': node_id, 'owner': item['owner'], 'class': item['id'],
                'payload': json.dumps(node_payload, separators=(',', ':')), 'now': now,
            })
            conn.execute(text("""INSERT INTO class_synthesis_plan_membership
                (owner_id,class_id,package_id,modality,level,ordinal,node_id)
                VALUES(:owner,:class,:package,:modality,:level,:ordinal,:node)
                ON CONFLICT DO NOTHING"""), {
                'owner': item['owner'], 'class': item['id'], 'package': package_id,
                'modality': modality, 'level': level, 'ordinal': ordinal, 'node': node_id,
            })

            if level == 0:
                schedule_leaf(conn, item, node_id, modality, package_id)
            else:
                for child_id in children:
                    child_raw = conn.execute(text("""SELECT payload FROM class_input_windows
                        WHERE id=:id AND owner_id=:owner AND class_id=:class AND kind='synthesis'"""), {
                        'id': child_id, 'owner': item['owner'], 'class': item['id'],
                    }).scalar_one_or_none()
                    if child_raw is None:
                        raise ValueError('Synthesis plan child is unavailable')
                    child_payload = json.loads(child_raw)
                    child_payload['parentId'] = node_id
                    conn.execute(text('UPDATE class_input_windows SET payload=:payload WHERE id=:id AND owner_id=:owner'), {
                        'payload': json.dumps(child_payload, separators=(',', ':')),
                        'id': child_id, 'owner': item['owner'],
                    })
                    schedule_ready(conn, item, child_id, modality, package_id)

    cursor += len(rows)
    if cursor < source_count:
        state.update(level=level, cursor=cursor, sourceCount=source_count)
        package['synthesisBuild'] = state
        return package, False

    output_count = (source_count + fanout - 1) // fanout
    if output_count > MERGE_FANOUT:
        package['synthesisBuild'] = {
            'version': VERSION,
            'level': level + 1,
            'cursor': 0,
            'sourceCount': output_count,
        }
        return package, False

    synthesis = {}
    for modality in ('summary', 'recall'):
        root_rows = conn.execute(text("""SELECT node_id FROM class_synthesis_plan_membership
            WHERE owner_id=:owner AND class_id=:class AND package_id=:package
              AND modality=:modality AND level=:level
            ORDER BY ordinal LIMIT :limit"""), {
            'owner': item['owner'], 'class': item['id'], 'package': package_id,
            'modality': modality, 'level': level, 'limit': MERGE_FANOUT,
        }).scalars().all()
        if len(root_rows) != output_count:
            raise ValueError('Synthesis plan root page is incomplete')
        synthesis[modality] = {
            'children': root_rows,
            'version': VERSION,
            'boundedCoverage': True,
        }
        for child_id in root_rows:
            child_raw = conn.execute(text("""SELECT payload FROM class_input_windows
                WHERE id=:id AND owner_id=:owner AND class_id=:class AND kind='synthesis'"""), {
                'id': child_id, 'owner': item['owner'], 'class': item['id'],
            }).scalar_one_or_none()
            if child_raw is None:
                raise ValueError('Synthesis plan root is unavailable')
            child_payload = json.loads(child_raw)
            child_payload['parentId'] = package_id
            conn.execute(text('UPDATE class_input_windows SET payload=:payload WHERE id=:id AND owner_id=:owner'), {
                'payload': json.dumps(child_payload, separators=(',', ':')),
                'id': child_id, 'owner': item['owner'],
            })

    package['synthesis'] = synthesis
    package.pop('synthesisBuild', None)
    return package, True


def package_sources_current(conn, owner, class_id, recording_id, package):
    """Check all package source revisions with bounded in-memory pages."""
    lock = " FOR SHARE" if conn.dialect.name == "postgresql" else ""
    window_set_id=package.get('windowSetId')
    window_count=int(package.get('windowCount',len(package.get('windows') or [])))
    legacy_windows=package.get('windows') or []
    if window_set_id:
        membership_count=conn.execute(text("SELECT COUNT(*) FROM class_session_window_membership WHERE owner_id=:owner AND class_id=:class AND set_id=:set AND purpose='transcript'"),{'owner':owner,'class':class_id,'set':window_set_id}).scalar_one()
        if int(membership_count)!=window_count:return False
    after_ordinal = -1
    checked = 0
    while checked < window_count:
        if window_set_id:
            page_rows=conn.execute(text("""SELECT ordinal,window_id FROM class_session_window_membership
                WHERE owner_id=:owner AND class_id=:class AND set_id=:set AND purpose='transcript'
                  AND ordinal>:after ORDER BY ordinal LIMIT :limit"""),{
                'owner':owner,'class':class_id,'set':window_set_id,'limit':REVISION_CHECK_WINDOW_PAGE,'after':after_ordinal,
            }).all()
            if not page_rows:return False
            after_ordinal=page_rows[-1][0]
            page_ids=[row[1] for row in page_rows]
        else:
            start=checked
            page_ids=legacy_windows[start:start + REVISION_CHECK_WINDOW_PAGE]
        if not page_ids:return False
        checked += len(page_ids)
        rows = conn.execute(text("""SELECT id,payload FROM class_input_windows
            WHERE owner_id=:owner AND class_id=:class AND kind='transcript' AND id IN :ids""").bindparams(
                bindparam("ids", expanding=True)), {
            "owner": owner, "class": class_id, "ids": page_ids,
        }).mappings().all()
        if len(rows) != len(page_ids):
            return False
        expected = {}
        for row in rows:
            payload = json.loads(row["payload"])
            for segment in payload.get("segments", []):
                expected[segment["id"]] = segment["normalization_version"]
        segment_ids = list(expected)
        for offset in range(0, len(segment_ids), REVISION_CHECK_SEGMENT_PAGE):
            segment_page = segment_ids[offset:offset + REVISION_CHECK_SEGMENT_PAGE]
            current = dict(conn.execute(text("""SELECT id,normalization_version
                FROM lecture_transcript_segments WHERE recording_id=:recording AND id IN :ids""" + lock).bindparams(
                    bindparam("ids", expanding=True)), {
                "recording": recording_id, "ids": segment_page,
            }).all())
            if any(current.get(segment_id) != expected[segment_id] for segment_id in segment_page):
                return False
    return True
