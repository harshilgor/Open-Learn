"""Bounded HTTPS navigation without browser compute for simple public pages."""
import hashlib
import html
from html.parser import HTMLParser
from urllib.parse import urljoin
import httpx
from ..contracts import Observation
from ..policy import check_url
from ...url_ingestion import validate_public_url, extract_readable, MAX_BYTES
from ...identity import fail


class Links(HTMLParser):
    def __init__(self, base):
        super().__init__(); self.base = base; self.links = []; self.current = None
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('href'):
            self.current = {'href': urljoin(self.base, attrs['href']), 'name': attrs.get('aria-label', '')}
    def handle_data(self, value):
        if self.current: self.current['name'] += value
    def handle_endtag(self, tag):
        if tag == 'a' and self.current:
            self.links.append(self.current); self.current = None


class PublicExecutor:
    def execute(self, action, connection, previous=None):
        if action.tool in {'click', 'read_document'}:
            control = next((c for c in (previous or {}).get('controls', []) if c['ref'] == action.element_ref), None)
            url = action.url or (control or {}).get('href')
        else:
            url = action.url or (previous or {}).get('url') or connection['origin']
        if action.tool not in {'navigate', 'observe', 'find', 'click', 'read_document'}:
            fail('capability_unavailable', 'Connect the browser companion to interact with this website.', 422)
        check_url(url, connection, resolve=True)
        with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
            for _ in range(4):
                check_url(url, connection, resolve=True)
                with client.stream('GET', url, headers={'User-Agent': 'OpenLearn-Assistant/1.0'}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        url = urljoin(url, response.headers.get('location', '')); continue
                    if response.status_code in {401, 403}:
                        return Observation(url=url, document_revision='login', status='login_required')
                    response.raise_for_status()
                    content_type = response.headers.get('content-type', '').split(';')[0]
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_BYTES: fail('unsupported_file', 'This document exceeds the 2 MB public-read limit.', 413)
                    if content_type == 'application/pdf':
                        from io import BytesIO
                        from pypdf import PdfReader
                        reader = PdfReader(BytesIO(bytes(data)))
                        if len(reader.pages) > 100: fail('unsupported_file', 'This PDF has too many pages for one task.', 413)
                        blocks = [{'ref': f'page:{n+1}', 'text': (p.extract_text() or '')[:20000]} for n, p in enumerate(reader.pages)]
                        return Observation(url=url, title='PDF document', document_revision=hashlib.sha256(data).hexdigest(), blocks=blocks, complete=True)
                    if content_type not in {'text/html', 'text/plain', 'text/markdown'}:
                        fail('unsupported_file', 'Use a readable webpage or PDF.', 415)
                    title, body = extract_readable(bytes(data), content_type)
                    if action.tool == 'find' and action.query:
                        index = body.lower().find(action.query.lower())
                        body = body[max(0,index-2000):index+18000] if index >= 0 else 'No matching text in this document.'
                    parser = Links(url); parser.feed(bytes(data).decode('utf-8', errors='replace'))
                    controls = [{'ref': f'e{n}', 'name': html.unescape(' '.join(link['name'].split()))[:300] or link['href'][:300],
                                 'role': 'link', 'href': link['href'][:2048], 'writable': False}
                                for n, link in enumerate(parser.links[:200]) if link['href'].startswith('https:')]
                    blocks = [{'ref': f'b{n}', 'text': body[offset:offset+12000]} for n, offset in enumerate(range(0, min(len(body), 60000), 12000))]
                    return Observation(url=url, title=title[:300], document_revision=hashlib.sha256(data).hexdigest(),
                                       blocks=blocks, controls=controls, truncated=len(body) > 60000, complete=action.tool != 'find' and len(body) <= 60000)
        fail('unsupported_file', 'The website redirected too many times.', 422)
