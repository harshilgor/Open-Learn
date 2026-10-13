"""Bounded recurrence expansion with local-time identity and DST validation."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from dateutil.rrule import rrulestr
from ..identity import fail


def parse(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None: raise ValueError()
        return result
    except (ValueError, AttributeError): fail('invalid_time', 'Provide a date and time with UTC offset.', 422)


def bounds(start, end):
    lo, hi = parse(start), parse(end)
    if hi <= lo or hi - lo > timedelta(days=93): fail('invalid_range', 'Choose a range between one instant and 93 days.', 422)
    return lo, hi


def expand(event, lo, hi, display_zone):
    temporal = event['temporal']; zone = ZoneInfo(temporal['timezone'])
    mode = temporal['mode']
    if mode == 'timed':
        start = parse(temporal['start']).astimezone(zone)
        duration = parse(temporal['end']) - parse(temporal['start'])
    elif mode == 'all_day':
        start = datetime.combine(datetime.fromisoformat(temporal['startDate']).date(), time.min, zone)
        duration = datetime.fromisoformat(temporal['endDate']) - datetime.fromisoformat(temporal['startDate'])
    elif temporal.get('dueAt'):
        start = parse(temporal['dueAt']).astimezone(zone); duration = timedelta(0)
    else:
        start = datetime.combine(datetime.fromisoformat(temporal['dueDate']).date(), time.min, zone); duration = timedelta(0)
    recurrence = event.get('recurrence')
    if recurrence:
        # Incremental xafter avoids building an unbounded historical recurrence list.
        rule = rrulestr('\n'.join(event['recurrenceRules']) if event.get('recurrenceRules') else recurrence, dtstart=start)
        candidates = rule.xafter(lo.astimezone(zone) - duration - timedelta(days=1), inc=True)
    else: candidates = [start]
    result = []
    for index, candidate in enumerate(candidates):
        if index >= 1500: fail('expansion_limit', 'Narrow the date range.', 422)
        if candidate > hi.astimezone(zone) + timedelta(days=1): break
        wall = candidate.replace(tzinfo=None)
        candidate = wall.replace(tzinfo=zone, fold=0)
        if candidate.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != wall: continue
        finish = candidate + duration
        if mode == 'all_day' or (mode == 'deadline' and temporal.get('dueDate')):
            left, right = lo.astimezone(display_zone).date(), hi.astimezone(display_zone).date()
            if not (candidate.date() <= right and (finish.date() > left if mode == 'all_day' else candidate.date() >= left)): continue
        elif not (candidate < hi and (finish > lo if duration else candidate >= lo)): continue
        key = candidate.isoformat()
        item = {**event, 'eventId': event['id'], 'occurrenceKey': key, 'id': event['id'] + '@' + key}
        current = dict(temporal)
        if mode == 'timed': current.update(start=candidate.isoformat(), end=finish.isoformat())
        elif mode == 'all_day': current.update(startDate=candidate.date().isoformat(), endDate=finish.date().isoformat())
        elif temporal.get('dueAt'): current['dueAt'] = candidate.isoformat()
        else: current['dueDate'] = candidate.date().isoformat()
        item['temporal'] = current
        item['sortAt'] = candidate.timestamp()
        result.append(item)
    return result
