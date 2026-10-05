import hashlib
from io import BytesIO
from ..contracts import Observation
from ...identity import fail


def document_observation(url, data, content_type):
    if len(data) > 8_000_000: fail('unsupported_file', 'Document exceeds 8 MB.', 413)
    digest = hashlib.sha256(data).hexdigest()
    if 'pdf' in content_type:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted or len(reader.pages) > 100: fail('unsupported_file', 'Use an unencrypted PDF with at most 100 pages.', 422)
        blocks = [{'ref': 'page:' + str(n+1), 'text': (page.extract_text() or '')[:20000]} for n, page in enumerate(reader.pages)]
        return Observation(url=url, document_revision=digest, title='Course document', blocks=blocks,
                           complete=all(b['text'].strip() for b in blocks), status='completed' if any(b['text'] for b in blocks) else 'unsupported')
    if content_type.startswith('text/'):
        return Observation(url=url, document_revision=digest, blocks=[{'ref': 'b0', 'text': data.decode('utf-8', errors='replace')[:20000]}], truncated=len(data)>20000)
    if content_type.startswith('image/'):
        import base64
        if len(data) > 2_000_000: fail('unsupported_file', 'Image exceeds 2 MB.', 413)
        mime = content_type.split(';')[0].strip()
        if mime not in {'image/png','image/jpeg','image/webp'}: fail('unsupported_file','Use a PNG, JPEG or WebP image.',415)
        return Observation(url=url, document_revision=digest, title='Image document', screenshot=base64.b64encode(data).decode(), image_mime=mime, status='partial')
    fail('unsupported_file', 'This document format is unsupported.', 415)
