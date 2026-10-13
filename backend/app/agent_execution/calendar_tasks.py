"""Bounded, read-only Google Calendar task parsing and execution."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .google_connector import GoogleAdapter, GoogleConnections
from .connected_contracts import ConnectorError

MAX_RANGE_DAYS = 31
MAX_PAGES = 5
PAGE_SIZE = 20


def parse_calendar_window(text: str, timezone_name: str, *, now: datetime | None = None) -> dict | None:
    """Resolve supported relative or explicit date ranges to RFC 3339 bounds."""
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, TypeError):
        raise ValueError('Choose a valid IANA timezone before reading Calendar.') from None
    local_now = (now or datetime.now(zone)).astimezone(zone)
    lower = re.sub(r'\s+', ' ', str(text or '')).strip().lower()
    start_day: date | None = None
    end_day: date | None = None
    explicit = re.search(r'\bfrom\s+(\d{4}-\d{2}-\d{2})\s+(?:to|through|until)\s+(\d{4}-\d{2}-\d{2})\b', lower)
    if explicit:
        try:
            start_day = date.fromisoformat(explicit.group(1))
            end_day = date.fromisoformat(explicit.group(2)) + timedelta(days=1)
        except ValueError:
            return None
    elif re.search(r'\bnext\s+(?:7|seven)\s+days?\b', lower):
        start = local_now
        end = local_now + timedelta(days=7)
        return {'timeMin': start.isoformat(timespec='seconds'), 'timeMax': end.isoformat(timespec='seconds'),
                'timeZone': timezone_name}
    elif re.search(r'\btoday\b', lower):
        start_day = local_now.date(); end_day = start_day + timedelta(days=1)
    elif re.search(r'\btomorrow\b', lower):
        start_day = local_now.date() + timedelta(days=1); end_day = start_day + timedelta(days=1)
    elif re.search(r'\bthis\s+week\b', lower):
        start_day = local_now.date() - timedelta(days=local_now.weekday()); end_day = start_day + timedelta(days=7)
    elif re.search(r'\bnext\s+week\b', lower):
        start_day = local_now.date() - timedelta(days=local_now.weekday()) + timedelta(days=7); end_day = start_day + timedelta(days=7)
    if start_day is None or end_day is None or end_day <= start_day or (end_day - start_day).days > MAX_RANGE_DAYS:
        return None
    start = datetime.combine(start_day, time.min, tzinfo=zone)
    end = datetime.combine(end_day, time.min, tzinfo=zone)
    return {'timeMin': start.isoformat(timespec='seconds'), 'timeMax': end.isoformat(timespec='seconds'),
            'timeZone': timezone_name}


def calendar_id_from_text(text: str) -> str:
    match = re.search(r'\bcalendar\s*id\s*(?:is|=|:)\s*([^\s,;]+)', str(text or ''), re.I)
    return match.group(1)[:300] if match else 'primary'


def resolve_calendar_task_inputs(store, run, connections):
    """Select an already-authorized account or return a learner question."""
    from .kernel import AskUserDecision

    spec = dict(run.get('calendarRead') or {})
    steering = str((run.get('constraints') or {}).get('steering') or '')
    timezone_name = spec.get('timeZone') or 'America/Los_Angeles'
    bounds = {'timeMin': spec.get('timeMin'), 'timeMax': spec.get('timeMax'), 'timeZone': timezone_name}
    if not bounds['timeMin'] or not bounds['timeMax']:
        bounds = parse_calendar_window(steering, timezone_name) or parse_calendar_window(run.get('message', ''), timezone_name)
    spec.setdefault('calendarId', 'primary')
    spec['timeZone'] = timezone_name
    if not bounds:
        return spec, AskUserDecision(kind='ask_user', question='What date range should I check?', inputKind='choice',
            options=['Today', 'Tomorrow', 'This week', 'Next week']).model_dump(by_alias=True)
    spec.update(bounds)

    eligible = [item for item in connections if item.get('status') == 'connected'
                and 'calendar_read' in item.get('capabilities', [])]
    selected = next((item for item in eligible if item['id'] == spec.get('connectionId')), None)
    if selected is None and steering:
        named = [item for item in eligible if str(item.get('email', '')).casefold() in steering.casefold()]
        if len(named) == 1:
            selected = named[0]
    if selected is None and len(eligible) == 1:
        selected = eligible[0]
    if selected is None and not eligible:
        return spec, AskUserDecision(kind='ask_user', question=(
            'I can check that once you connect Google Calendar with read-only access in Connected actions and child tasks. '
            'Connect it there, then reply with the account email you want me to use.'
        ), inputKind='text').model_dump(by_alias=True)
    if selected is None:
        emails = list(dict.fromkeys(str(item.get('email') or '').strip() for item in eligible if item.get('email')))
        if 1 < len(emails) <= 12:
            return spec, AskUserDecision(kind='ask_user', question='Which connected Google account should I use?',
                inputKind='choice', options=emails).model_dump(by_alias=True)
        return spec, AskUserDecision(kind='ask_user', question='Which connected Google account should I use? Reply with its email address.',
            inputKind='text').model_dump(by_alias=True)
    spec['connectionId'] = selected['id']
    return spec, None


def execute_calendar_read(store, owner: str, run: dict, still_current):
    """Read at most 100 event summaries; provider text stays untrusted data."""
    spec = run.get('calendarRead') or {}
    connection_id = spec.get('connectionId')
    calendar_id = spec.get('calendarId') or 'primary'
    time_min, time_max = spec.get('timeMin'), spec.get('timeMax')
    if not isinstance(time_min, str) or not isinstance(time_max, str):
        raise ConnectorError('calendar_range_invalid')
    try:
        ZoneInfo(spec.get('timeZone') or 'America/Los_Angeles')
        start = datetime.fromisoformat(str(time_min).replace('Z', '+00:00'))
        end = datetime.fromisoformat(str(time_max).replace('Z', '+00:00'))
        if (start.utcoffset() is None or end.utcoffset() is None or end <= start
                or end - start > timedelta(days=MAX_RANGE_DAYS)):
            raise ValueError
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        raise ConnectorError('calendar_range_invalid') from None
    if not connection_id or not isinstance(calendar_id, str) or not calendar_id or len(calendar_id) > 300:
        raise ConnectorError('calendar_task_inputs_invalid')

    connections = GoogleConnections(store)
    adapter = GoogleAdapter(connections)
    events: dict[str, dict] = {}
    page_token = None
    pages = 0
    has_more = False
    while pages < MAX_PAGES and len(events) < PAGE_SIZE * MAX_PAGES:
        still_current()
        result = adapter.read(owner, connection_id, 'calendar', page=page_token, calendar_id=calendar_id,
                              time_min=spec['timeMin'], time_max=spec['timeMax'])
        payload = result.get('data') if isinstance(result, dict) else None
        if not isinstance(payload, dict) or not isinstance(payload.get('items', []), list):
            raise ConnectorError('calendar_result_invalid')
        pages += 1
        for item in payload.get('items', [])[:PAGE_SIZE]:
            if not isinstance(item, dict) or not isinstance(item.get('id'), str):
                continue
            start_value = item.get('start') if isinstance(item.get('start'), dict) else {}
            end_value = item.get('end') if isinstance(item.get('end'), dict) else {}
            events[item['id']] = {
                'id': item['id'][:300], 'title': str(item.get('summary') or 'Untitled event')[:300],
                'start': str(start_value.get('dateTime') or start_value.get('date') or '')[:80],
                'end': str(end_value.get('dateTime') or end_value.get('date') or '')[:80],
                'location': str(item.get('location') or '')[:300],
            }
        page_token = payload.get('nextPageToken')
        if page_token is not None and (not isinstance(page_token, str) or not page_token or len(page_token) > 2048):
            raise ConnectorError('calendar_result_invalid')
        if not page_token:
            has_more = False
            break
        has_more = True
    still_current()
    complete = not has_more
    retrieved_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    records = list(events.values())
    manifest = {
        'schemaVersion': 1, 'provider': 'google_calendar', 'calendarId': calendar_id,
        'timeZone': spec.get('timeZone'), 'range': {'start': spec['timeMin'], 'end': spec['timeMax']},
        'retrievedAt': retrieved_at, 'events': records,
        'coverage': {'complete': complete, 'pagesRead': pages, 'eventsRead': len(records),
                     'moreAvailable': has_more},
        'limitations': [] if complete else ['The result reached the five-page/100-event limit; narrow the range to see a complete set.'],
    }
    source_id = 'calendar_' + hashlib.sha256(f"{connection_id}:{calendar_id}:{spec['timeMin']}:{spec['timeMax']}".encode()).hexdigest()[:32]
    lineage = {'inputHash': run['inputHash'], 'inputRevision': run['desired_input_revision'],
               'toolVersion': 'google-calendar-read-v1', 'connectionId': connection_id,
               'connectionCapability': 'calendar_read',
               'calendarId': calendar_id, 'timeMin': spec['timeMin'], 'timeMax': spec['timeMax']}
    summary = (f"Found {len(records)} Calendar event{'s' if len(records) != 1 else ''} in {calendar_id} "
               f"from {time_min[:10]} through {time_max[:10]}. "
               + ('More events are available; narrow the date range for complete coverage.' if not complete
                  else 'The selected range was fully paged.'))
    if records:
        preview = [f"• {event['start'] or 'Time unavailable'} — {event['title'][:160]}" for event in records[:5]]
        summary += '\n' + '\n'.join(preview)
        if len(records) > 5:
            summary += f"\n…and {len(records) - 5} more. Download the private event list for details."
    return {'outputs': [{'name': 'calendar-events.json', 'mediaType': 'application/json',
                         'content': (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode(),
                         'lineage': lineage}],
            'summary': summary,
            'sources': [{'id': source_id, 'title': f'Google Calendar · {calendar_id}',
                         'canonicalUrl': 'https://calendar.google.com', 'contentAvailable': False,
                         'retrievedAt': retrieved_at}],
            'completion': {'policyVersion': 'google-calendar-read-v1',
                           'status': 'verified' if complete else 'partial',
                           'partial': not complete,
                           'checks': [{'criterion': 'calendar_scope_and_range', 'status': 'pass'},
                                      {'criterion': 'event_schema', 'status': 'pass'},
                                      {'criterion': 'pagination_coverage', 'status': 'pass' if complete else 'unknown'}],
                           'limitations': manifest['limitations']}}
