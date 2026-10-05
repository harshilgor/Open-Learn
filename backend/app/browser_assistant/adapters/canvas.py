"""Canvas API discovery supplies evidence, not title-based exam guesses."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from .documents import document_observation
from ..contracts import EvidenceCandidate, DateValue
from ..policy import check_url
from ..reconciliation import map_course
from ...identity import fail


def resource_url(connection, action):
    course = action.external_course_id
    routes = {
        'courses': '/api/v1/courses?enrollment_state=active&enrollment_type=student&include[]=term&per_page=100',
        'assignments': f'/api/v1/courses/{course}/assignments?override_assignment_dates=true&per_page=100',
        'syllabus': f'/api/v1/courses/{course}?include[]=syllabus_body',
        'announcements': f'/api/v1/announcements?context_codes[]=course_{course}&per_page=100',
        'modules': f'/api/v1/courses/{course}/modules?include[]=items&per_page=100',
        'calendar': '/api/v1/calendar_events?' + urlencode({'context_codes[]': 'course_' + str(course),
            'start_date': (datetime.now(timezone.utc)-timedelta(days=30)).date().isoformat(),
            'end_date': (datetime.now(timezone.utc)+timedelta(days=180)).date().isoformat(), 'per_page': 100})}
    if action.resource != 'courses' and not course: fail('invalid_input', 'Choose a Canvas course.', 422)
    url = connection['origin'] + routes[action.resource]
    if action.cursor:
        check_url(action.cursor, connection)
        base, cursor = urlsplit(url), urlsplit(action.cursor)
        from urllib.parse import parse_qs
        expected, actual = parse_qs(base.query), parse_qs(cursor.query)
        if cursor.path != base.path or any(actual.get(k) != v for k, v in expected.items() if k not in {'page', 'per_page'}):
            fail('origin_not_approved', 'Canvas pagination changed its resource scope.', 403)
        url = action.cursor
    return url


def platform_script():
    return '(' + Path(__file__).with_name('canvas-read.js').read_text(encoding='utf-8') + ')'


def discover(conn, run, connection, snapshot):
    if not snapshot.get('accountId'): fail('account_changed', 'Confirm the student account before reading courses.', 409)
    if connection.get('accountId') and connection['accountId'] != snapshot['accountId']:
        fail('account_changed', 'The signed-in Canvas account changed. Reconnect it.', 409)
    tasks, enrollments = [], []
    for item in snapshot.get('platformItems', []):
        if item.get('workflow_state') not in {None, 'available'}: continue
        if not any(e.get('type') in {'student', 'StudentEnrollment'} for e in item.get('enrollments', [])): continue
        term = item.get('term') or {}
        term_id = str(term.get('id', 'current'))
        if connection.get('term') not in {'current', term_id, term.get('name')}: continue
        end = item.get('end_at') or term.get('end_at')
        if end:
            try:
                parsed = datetime.fromisoformat(end.replace('Z', '+00:00'))
                if parsed.tzinfo and parsed < datetime.now(timezone.utc): continue
            except ValueError: pass
        if run.get('intent',{}).get('save'):
            course = map_course(conn, run['owner_id'], connection, str(item['id']), item.get('name', 'Canvas course'), term_id)
        else:
            from sqlalchemy import text
            course = conn.execute(text('SELECT course_id FROM external_course_links WHERE owner_id=:owner AND connection_id=:connection AND external_id=:external AND term=:term'), {'owner':run['owner_id'],'connection':connection['id'],'external':str(item['id']),'term':term_id}).scalar_one_or_none()
        enrollments.append({'courseId': course, 'externalId': str(item['id']), 'name': item.get('name', 'Canvas course'), 'term': term_id})
        for resource in ('assignments', 'calendar', 'syllabus', 'announcements', 'modules'):
            tasks.append({'tool': 'read_platform_resource', 'resource': resource, 'externalCourseId': str(item['id'])})
    return enrollments, tasks


def platform_candidates(snapshot, action):
    # Structured assignments have authoritative student-specific due timestamps.
    # Exam classification still requires an explicit exam label.
    import re
    candidates = []
    for n, item in enumerate(snapshot.get('platformItems', [])):
        label = str(item.get('name') or item.get('title') or '')[:300]
        quote = next((b['text'] for b in snapshot['blocks'] if b['ref'] == f'item:{n}'), '')
        if not quote or not label: continue
        exam = bool(re.search(r'\b(midterm|exam|final examination|test)\b', label, re.I))
        if action.resource == 'assignments':
            due = item.get('due_at')
            date = DateValue(kind='instant', value=due) if due else DateValue(kind='unknown')
            candidates.append(EvidenceCandidate(kind='assessment' if exam else 'assignment', title=label,
                snapshot_id=snapshot['id'], block_ref=f'item:{n}', quote=quote,
                course_external_id=action.external_course_id, external_id='assignment:' + str(item['id']),
                date=date, confirmation='confirmed'))
        elif action.resource == 'calendar' and item.get('start_at'):
            candidates.append(EvidenceCandidate(kind='assessment' if exam else 'meeting', title=label,
                snapshot_id=snapshot['id'], block_ref=f'item:{n}', quote=quote,
                course_external_id=action.external_course_id, external_id='calendar:' + str(item['id']),
                date=DateValue(kind='instant', value=item['start_at']),
                end=DateValue(kind='instant', value=item['end_at']) if item.get('end_at') else None,
                location=item.get('location_name'), confirmation='confirmed'))
    return candidates
