"""Executor-independent policy. Page content never expands task authority."""
import hashlib
import ipaddress
import re
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from ..identity import fail

TERMINAL = {'completed', 'completed_partial', 'cancelled', 'failed'}
WAITING = {'waiting_for_user', 'waiting_for_login', 'waiting_for_device', 'paused'}
DANGEROUS = re.compile(r'\b(submit|purchase|pay|delete|remove|send|enroll|drop|withdraw|start (?:quiz|exam|attempt)|begin (?:quiz|exam|attempt))\b', re.I)
SENSITIVE = re.compile(r'password|credit.?card|card number|security code|\bcvv\b|one.?time|verification code', re.I)


def origin(url):
    try:
        p = urlsplit(url)
        if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in {None, 443}:
            raise ValueError()
        host = p.hostname.lower().rstrip('.')
        if host == 'localhost' or host.endswith(('.localhost', '.local', '.internal')):
            raise ValueError()
        try:
            if not ipaddress.ip_address(host).is_global:
                raise ValueError()
        except ValueError:
            # Distinguish a hostname from a forbidden literal address.
            if ':' in host or re.fullmatch(r'[\d.]+', host):
                raise
        return 'https://' + host
    except (ValueError, TypeError):
        fail('origin_not_approved', 'Use a public HTTPS website without embedded credentials.', 422)


def check_url(url, connection, *, resolve=False):
    approved = {connection['origin'], *connection.get('approvedOrigins', [])}
    if origin(url) not in approved:
        fail('origin_not_approved', 'Approve ' + origin(url) + ' in this connection before following its links.', 403)
    if resolve:
        from ..url_ingestion import validate_public_url
        validate_public_url(url)
    return url


def safe_url(url):
    p = urlsplit(url)
    # Private query strings and fragments do not belong in activity messages.
    return urlunsplit((p.scheme, p.netloc, p.path, '', ''))


def timezone(value):
    try:
        return ZoneInfo(value)
    except (ValueError, KeyError):
        fail('invalid_timezone', 'Select a valid IANA timezone.', 422)


def authorize_action(action, connection, snapshot=None):
    if action.url:
        check_url(action.url, connection)
    if action.cursor:
        check_url(action.cursor, connection)
    if action.tool == 'navigate' and not action.url:
        fail('invalid_input', 'Navigation requires a URL.', 422)
    if action.tool == 'find' and not action.query:
        fail('invalid_input', 'Finding text requires a search phrase.', 422)
    if action.tool == 'read_platform_resource':
        if connection.get('platform') != 'canvas' or not action.resource:
            fail('capability_unavailable', 'This connection has no supported platform API.', 422)
    if action.tool in {'click', 'fill', 'press_key'}:
        if not snapshot or action.snapshot_id != snapshot['id']:
            fail('stale_reference', 'Read the page again before interacting.', 409)
        control = next((c for c in snapshot.get('controls', []) if c['ref'] == action.element_ref), None)
        if not control:
            fail('stale_reference', 'This control is no longer in the page observation.', 409)
        if DANGEROUS.search(control['name']) or SENSITIVE.search(control['name']):
            fail('action_blocked', 'This reading task cannot use that consequential control.', 403)
        if control.get('href'):
            check_url(control['href'], connection)
        if action.tool in {'fill', 'press_key'} and not control.get('writable'):
            fail('action_blocked', 'Only page search fields can be filled during a reading task.', 403)
        if action.tool == 'press_key' and action.value not in {'Enter', 'Escape', 'ArrowDown', 'ArrowUp', 'Tab'}:
            fail('action_blocked', 'That key is outside the reading task.', 403)
    return action


def checksum(value):
    return hashlib.sha256(value.encode()).hexdigest()


def require_course(conn, owner, course):
    from sqlalchemy import text
    if not conn.execute(text('SELECT id FROM courses WHERE owner_id=:owner AND id=:id AND archived_at IS NULL'), {'owner':owner,'id':course}).first():
        fail('not_found','Course unavailable.',404)
