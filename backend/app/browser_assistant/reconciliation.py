import json
import re
from datetime import datetime, timezone
from sqlalchemy import text
from .evidence import validate_candidate, source_record
from .policy import checksum
from ..academic_planning import AcademicPlanningService
from ..course_models import CourseTeachingPreferences, CourseReminderPreferences
from ..workflow_store import uid, encoded
from ..identity import fail


def map_course(conn, owner, connection, external_id, name, term):
    row = conn.execute(text('SELECT course_id FROM external_course_links WHERE owner_id=:owner AND connection_id=:connection AND external_id=:external AND term=:term'),
                       {'owner': owner, 'connection': connection['id'], 'external': str(external_id), 'term': str(term)}).first()
    if row: return row[0]
    identifier = 'course_' + checksum(f"{owner}:{connection['id']}:{external_id}:{term}")[:32]
    # Reuse an explicit legacy mapping only when its authenticated student matches.
    legacy = set()
    for payload in conn.execute(text('SELECT payload FROM canvas_connections WHERE owner_id=:owner'), {'owner':owner}).scalars():
        old = json.loads(payload)
        if old.get('origin') == connection['origin'] and old.get('canvasStudentId') == connection.get('accountId') and old.get('status') == 'paired':
            mapped = old.get('courses',{}).get(str(external_id))
            if mapped and conn.execute(text('SELECT id FROM courses WHERE owner_id=:owner AND id=:id AND archived_at IS NULL'), {'owner':owner,'id':mapped}).first(): legacy.add(mapped)
    if len(legacy) == 1: identifier = next(iter(legacy))
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(text('''INSERT INTO courses(id,owner_id,name,goal,teaching_preferences,reminder_preferences,created_at,updated_at)
        VALUES(:id,:owner,:name,'Imported course',:teaching,:reminders,:now,:now) ON CONFLICT(id) DO NOTHING'''),
        {'id': identifier, 'owner': owner, 'name': name[:300], 'teaching': CourseTeachingPreferences().model_dump_json(),
         'reminders': CourseReminderPreferences().model_dump_json(), 'now': now})
    conn.execute(text('''INSERT INTO external_course_links(id,owner_id,connection_id,external_id,term,course_id,payload)
        VALUES(:id,:owner,:connection,:external,:term,:course,:payload) ON CONFLICT(owner_id,connection_id,external_id,term) DO NOTHING'''),
        {'id': uid('enrollment'), 'owner': owner, 'connection': connection['id'], 'external': str(external_id), 'term': str(term),
         'course': identifier, 'payload': encoded({'name': name, 'term': str(term), 'accountId': connection.get('accountId')})})
    return identifier


def save_candidates(store, conn, run, connection, candidates, snapshots):
    svc = AcademicPlanningService(store)
    saved = []
    titles = {}
    for candidate in candidates:
        if candidate.external_id: continue
        key = (candidate.course_id or candidate.course_external_id or run.get('courseId'), candidate.title.lower().strip())
        date = candidate.date.value if candidate.date else None
        if key in titles and titles[key] != date:
            fail('ambiguous_event', 'Several exams have the same title and different dates. Supply distinct event names before saving.', 422)
        titles[key] = date
    for candidate in candidates:
        snapshot = validate_candidate(candidate, snapshots)
        course = candidate.course_id or run.get('courseId')
        if candidate.course_external_id:
            row = conn.execute(text('SELECT course_id FROM external_course_links WHERE owner_id=:owner AND connection_id=:connection AND external_id=:external ORDER BY term'),
                               {'owner': run['owner_id'], 'connection': connection['id'], 'external': candidate.course_external_id}).all()
            if len(row) != 1: fail('ambiguous_course', 'Choose the course before saving this fact.', 422)
            course = row[0][0]
        if not course: fail('course_required', 'Select an OpenLearn course for these academic facts.', 422)
        source = source_record(snapshot, connection, candidate.quote, candidate.block_ref)
        if candidate.image_region: source['imageRegion'] = candidate.image_region
        source['confirmation'] = candidate.confirmation
        # Unstructured identity is independent of the date and preserved across source revisions.
        identity = candidate.external_id or ('browser:' + checksum(connection['id'] + ':' +
                   re.sub(r'\s+', ' ', candidate.title.lower()).strip() + ':' + connection.get('term', 'current'))[:32])
        fields = {'title': candidate.title, 'instructions': candidate.quote}
        if candidate.date: fields['start' if candidate.kind == 'meeting' else 'due' if candidate.kind == 'assignment' else 'date'] = candidate.date.model_dump(exclude_none=True)
        if candidate.end: fields['end'] = candidate.end.model_dump(exclude_none=True)
        if candidate.recurrence: fields['recurrence'] = candidate.recurrence
        if candidate.location: fields['location'] = candidate.location
        entity = svc.ingest_in_transaction(conn, run['owner_id'], course, {'kind': candidate.kind,
                'externalId': connection['id'] + ':' + identity, 'origin': 'browser', 'fields': fields,
                'source': source, 'confirmation': candidate.confirmation,
                'idempotencyKey': checksum(identity + snapshot['documentRevision'] + encoded(fields))})
        from .reminders import schedule_entity
        schedule_entity(store, conn, run['owner_id'], entity)
        field = 'start' if candidate.kind == 'meeting' else 'due' if candidate.kind == 'assignment' else 'date'
        selected = entity['facts'].get(field) or entity['facts']['title']
        saved.append({'entityId': entity['id'], 'revision': entity['revision'], 'courseId': course, 'title': candidate.title,
                      'kind': candidate.kind, 'date': entity['facts'].get(field,{}).get('value'),
                      'source': selected.get('source') or source, 'conflict': any(f.get('conflict') for f in entity['facts'].values())})
    return saved
