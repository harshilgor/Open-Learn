"""Immutable-source material index. Document text is evidence, never instructions.

Postings bound retrieval memory; OCR claims settle one page at a time under a
lease and source hash. Physical page numbers and printed labels are distinct.
"""
from __future__ import annotations
from collections import Counter
from contextlib import nullcontext
import hashlib
import json
import math
import re
import tempfile
import time
from pathlib import Path
from uuid import uuid4
from types import SimpleNamespace
from sqlalchemy import text, bindparam

INDEX_VERSION = 2
CUE_KINDS = {'physical_page', 'page_label', 'chapter', 'section', 'slide', 'figure', 'equation'}

class FitzReader:
    """Plain-text compatibility adapter if the configured pypdf is unavailable."""
    def __init__(self, document):
        self.document = document
        self.is_encrypted = document.needs_pass
        self.pages = [FitzPage(document, index) for index in range(len(document))]
        self.page_labels = [document[index].get_label() or str(index+1) for index in range(len(document))]
        self.outline = [SimpleNamespace(title=title, index=page-1) for _,title,page in document.get_toc()[:500]]
    def get_page_number(self, item):
        return item.index

class FitzPage:
    def __init__(self, document, index):
        self.document, self.index = document, index
    def get_contents(self):
        return None
    def extract_text(self, **kwargs):
        return self.document[self.index].get_text('text')

def pack(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))

def terms(value):
    return Counter(word[:80] for word in re.findall(r'\w{2,}', value.casefold()))

def stable(*parts):
    return 'idx_' + hashlib.sha256('|'.join(map(str, parts)).encode()).hexdigest()[:48]

def pdf_layout(path, page_index, document=None):
    """Page-local measured quads in crop-relative, unrotated PDF points.

    The matrix maps these points into the rendered/rotated viewport. Extraction
    failures return no geometry; callers may keep explicitly estimated hints.
    """
    try:
        import fitz
        with (nullcontext(document) if document is not None else fitz.open(path)) as doc:
            page = doc[page_index]
            metadata = {'coordinateSpace': 'pdf_crop_unrotated_top_left',
                        'cropBox': list(page.cropbox), 'mediaBox': list(page.mediabox),
                        'rotation': page.rotation, 'renderTransform': list(page.rotation_matrix),
                        'width': page.rect.width, 'height': page.rect.height,
                        'geometryStatus': 'measured', 'confidence': 1.0}
            fragments = []
            for block in page.get_text('dict')['blocks']:
                for line in block.get('lines', []):
                    for span in line.get('spans', []):
                        value = span.get('text', '')
                        if not value.strip():
                            continue
                        quad = fitz.recover_quad(line['dir'], span)
                        points = [[point.x, point.y] for point in (quad.ul, quad.ur, quad.lr, quad.ll)]
                        rotated = [fitz.Point(*point) * page.rotation_matrix for point in points]
                        xs, ys = [p.x for p in rotated], [p.y for p in rotated]
                        fragments.append({'text': value, 'quad': points,
                            'box': {'x': max(0, min(xs)/page.rect.width), 'y': max(0, min(ys)/page.rect.height),
                                    'width': min(1, (max(xs)-min(xs))/page.rect.width),
                                    'height': min(1, (max(ys)-min(ys))/page.rect.height)}})
                        if len(fragments) >= 10000:
                            return metadata, fragments
            return metadata, fragments
    except (ImportError, RuntimeError, ValueError, KeyError, IndexError, ZeroDivisionError):
        return {'geometryStatus': 'unavailable'}, []

class MaterialIndexService:
    def __init__(self, store):
        self.store = store

    def publish(self, conn, version, page_texts, labels, outline, ocr, layout=None):
        """Called in ingestion settlement transaction after canonical blocks exist."""
        vid, revision = version['id'], version['sha256']
        self.erase(conn, vid)
        blocks = conn.execute(text('SELECT * FROM material_blocks WHERE version_id=:v ORDER BY ordinal'), {'v': vid}).mappings().all()
        by_page = {}
        for block in blocks:
            by_page.setdefault(block['page_index'], []).append(block)
            self.postings(conn, block['id'], block['text'])
        for index, content in enumerate(page_texts):
            state = (ocr[index] if index < len(ocr) else None) or {}
            info = (layout[index] if layout and index < len(layout) else {})
            status = state.get('status', 'text' if content.strip() else 'pending')
            conn.execute(text('INSERT INTO material_index_pages(version_id,page_index,source_revision,index_version,page_label,status,payload) VALUES(:v,:p,:r,2,:l,:s,:payload)'),
                {'v': vid, 'p': index, 'r': revision, 'l': labels[index] if index < len(labels) else str(index+1), 's': status,
                 'payload': pack({**info, 'ocr': state, 'textChars': len(content), 'blockCount': len(by_page.get(index, []))})})
            for block in by_page.get(index, []):
                self.discover(conn, vid, index, block['text'], block['id'])
            if status in {'skipped_budget', 'failed', 'timeout', 'unavailable', 'pending'}:
                conn.execute(text("INSERT INTO material_ocr_work(version_id,page_index,owner_id,source_revision,status,payload) VALUES(:v,:p,:o,:r,'queued','{}')"),
                    {'v': vid, 'p': index, 'o': version['owner_id'], 'r': revision})
        for entry in outline[:500]:
            title = entry['title']
            matched = re.search(r'\b(chapter|ch\.?|section|sec\.?)\s*([\w.-]+)', title, re.I)
            kind = 'chapter' if matched and matched[1].lower().startswith('ch') else 'section'
            label = matched[2] if matched else title
            self.cue(conn, vid, entry['pageIndex'], kind, label, {'title': title, 'provenance': 'pdf_outline'})

    def erase(self, conn, vid):
        conn.execute(text('DELETE FROM material_index_terms WHERE block_id IN (SELECT id FROM material_blocks WHERE version_id=:v)'), {'v': vid})
        for table in ('material_index_cues', 'material_index_pages', 'material_ocr_work', 'material_extract_pages'):
            conn.execute(text(f'DELETE FROM {table} WHERE version_id=:v'), {'v': vid})

    def postings(self, conn, block_id, content):
        rows = [{'term': term, 'block': block_id, 'count': count} for term, count in terms(content).items()]
        if rows:
            conn.execute(text('INSERT INTO material_index_terms(term,block_id,frequency) VALUES(:term,:block,:count)'), rows)

    def checkpoint(self, version, page, payload=None, job=None):
        """Source-fenced durable extraction page; retries skip settled pages."""
        if payload is None:
            with self.store.engine.connect() as conn:
                saved=conn.execute(text('SELECT payload FROM material_extract_pages WHERE version_id=:v AND page_index=:p AND source_revision=:r'),
                    {'v':version['id'],'p':page,'r':version['sha256']}).scalar_one_or_none()
            return json.loads(saved) if saved else None
        with self.store.transaction() as conn:
            active=conn.execute(text("SELECT id FROM material_jobs WHERE id=:id AND lease=:l AND status='running' AND expires>:now"),
                {'id':job['id'],'l':job['lease'],'now':time.time()}).scalar_one_or_none()
            if active:
                conn.execute(text('INSERT INTO material_extract_pages(version_id,page_index,source_revision,payload) VALUES(:v,:p,:r,:payload) ON CONFLICT(version_id,page_index) DO UPDATE SET source_revision=excluded.source_revision,payload=excluded.payload'),
                    {'v':version['id'],'p':page,'r':version['sha256'],'payload':pack(payload)})

    def cue(self, conn, vid, page, kind, label, payload):
        label = str(label).casefold().strip()[:160]
        identifier = stable(vid, page, kind, label)
        conn.execute(text('INSERT INTO material_index_cues(id,version_id,page_index,kind,label,payload) VALUES(:id,:v,:p,:k,:l,:payload) ON CONFLICT(id) DO NOTHING'),
            {'id': identifier, 'v': vid, 'p': page, 'k': kind, 'l': label, 'payload': pack(payload)})

    def discover(self, conn, vid, page, content, block_id):
        patterns = [('figure', r'\b(?:figure|fig\.?)\s*([\d]+(?:[.-]\d+)*[a-z]?)'),
                    ('equation', r'\b(?:equation|eq\.?)\s*([\d]+(?:[.-]\d+)*[a-z]?)'),
                    ('chapter', r'(?im)^\s*(?:chapter|ch\.?)\s*([\w.-]+)'),
                    ('section', r'(?im)^\s*(?:section|sec\.?)\s*([\w.-]+)')]
        for kind, pattern in patterns:
            for match in list(re.finditer(pattern, content, re.I))[:50]:
                self.cue(conn, vid, page, kind, match[1], {'spanId': block_id,
                    'caption': content[max(0, match.start()-100):match.end()+400], 'provenance': 'extracted_text_label',
                    'confidence': 'label_detected_not_visual_verified'})

    def lookup(self, owner, course_id, query='', cue=None, session_id=None, limit=8):
        from .material_service import MaterialService, problem
        svc = MaterialService(self.store)
        if session_id:
            session = svc.session(owner, session_id)
            if getattr(session, 'course_id', None) != course_id:
                problem('source_outside_course', 'The requested course does not match this class.', 409)
        limit = max(1, min(12, limit))
        cue = cue or {}
        kind, value = cue.get('kind'), str(cue.get('value', '')).casefold().strip()
        if kind and (kind not in CUE_KINDS or not value or len(value) > 160):
            problem('invalid_reference_cue', 'Choose a supported cue and label.')
        scope = 'm.course_id=:course' if course_id else 'm.course_id IS NULL AND EXISTS (SELECT 1 FROM material_attachments a WHERE a.version_id=v.id AND a.session_id=:session)'
        params = {'owner': owner, 'course': course_id, 'session': session_id, 'limit': 33}
        where = "m.owner_id=:owner AND m.deleted=false AND m.role NOT IN ('answer_key','sample_paper') AND b.kind!='private_solution' AND v.status IN ('ready','partially_ready') AND " + scope
        select = 'SELECT b.*,m.title,v.sha256,v.payload AS version_payload FROM material_blocks b JOIN material_versions v ON v.id=b.version_id JOIN materials m ON m.id=v.material_id '
        if kind in {'physical_page', 'slide'}:
            try:
                number = int(value)
                if number < 1: raise ValueError()
            except ValueError:
                problem('invalid_reference_cue', 'Physical pages and slides use positive whole numbers.')
            where += ' AND b.page_index=:page'
            params['page'] = number-1
        elif kind == 'page_label':
            select += 'JOIN material_index_pages p ON p.version_id=v.id AND p.page_index=b.page_index AND p.source_revision=v.sha256 '
            where += ' AND lower(p.page_label)=:label'
            params['label'] = value
        elif kind:
            select += 'JOIN material_index_cues q ON q.version_id=v.id AND q.page_index=b.page_index '
            where += ' AND q.kind=:kind AND q.label=:label'
            params.update(kind=kind, label=value)
        query_terms = list(terms(query))[:12]
        if query_terms:
            where += ' AND (EXISTS (SELECT 1 FROM material_index_terms t WHERE t.block_id=b.id AND t.term IN :terms) OR lower(m.title) LIKE :phrase)'
            params.update(terms=query_terms, phrase='%'+query.casefold().replace('%','').replace('_','')[:200]+'%')
        if not kind and not query_terms:
            return {'candidates': [], 'ambiguous': False, 'hasMore': False, 'indexVersion': 2}
        ordering = '(SELECT COALESCE(SUM(t.frequency),0) FROM material_index_terms t WHERE t.block_id=b.id AND t.term IN :terms) DESC,' if query_terms else ''
        statement = text(select+'WHERE '+where+' ORDER BY '+ordering+'m.title,v.id,b.page_index,b.ordinal LIMIT :limit')
        if query_terms:
            statement = statement.bindparams(bindparam('terms', expanding=True))
        with self.store.engine.connect() as conn:
            rows = conn.execute(statement, params).mappings().all()
        # Dedup page candidates for exact cues, passage candidates for free text.
        unique = {}
        for row in rows:
            unique.setdefault((row['version_id'], row['page_index']) if kind else row['id'], row)
        ranked = []
        for row in unique.values():
            score = sum(1+math.log1p(terms(row['text']).get(term,0)) for term in query_terms if term in terms(row['text']))
            if query and query.casefold() in row['title'].casefold(): score += 4
            ranked.append((score, row))
        mode = 'lexical'
        if not kind and query and ranked:
            from .semantic_retrieval import configured_model, similarity_scores
            model = configured_model()
            if model:
                try:
                    semantic = similarity_scores(self.store, query, [{'id': r['id'], 'text': r['text']} for _,r in ranked[:32]], model)
                    ranked = [(score+3*semantic.get(row['id'],0),row) for score,row in ranked]
                    mode = 'hybrid_embedding'
                except Exception:
                    pass # Optional external ranking must preserve lexical availability.
        ranked.sort(key=lambda item:(-item[0],item[1]['version_id'],item[1]['page_index'],item[1]['ordinal']))
        candidates = []
        for score, row in ranked[:limit]:
            # Access/source revision is checked again after optional external work.
            try:
                current = svc.version(owner, row['version_id'])
            except Exception:
                continue
            if current['sha256'] != row['sha256'] or current['status'] not in {'ready','partially_ready'} or current['course_id'] != course_id or current['role'] in {'answer_key','sample_paper'}:
                continue
            if not course_id and row['version_id'] not in svc.attachments(owner, session_id): continue
            payload = json.loads(row['payload'])
            candidates.append({'spanId': row['id'], 'versionId': row['version_id'], 'title': row['title'], 'text': row['text'][:3500],
                'pageIndex': row['page_index'], 'pageLabel': payload.get('pageLabel'), 'geometry': payload.get('geometry'),
                'extractionStatus': payload.get('extractionStatus'), 'ocrConfidence': payload.get('ocrConfidence'),
                'sourceRevision': row['sha256'], 'provenance': 'authorized_course_library', 'retrieval': mode, 'score': round(score,4)})
        return {'candidates': candidates, 'ambiguous': len(candidates)>1 and (bool(kind) or len(ranked)>1 and ranked[0][0]==ranked[1][0]),
                'hasMore': len(rows)==33 or len(ranked)>limit, 'indexVersion': 2}

    def progress(self, owner, vid):
        from .material_service import MaterialService
        MaterialService(self.store).version(owner, vid)
        with self.store.engine.connect() as conn:
            rows = conn.execute(text('SELECT status,count(*) AS n FROM material_index_pages WHERE version_id=:v GROUP BY status'), {'v':vid}).mappings().all()
            work = conn.execute(text('SELECT status,count(*) AS n FROM material_ocr_work WHERE version_id=:v GROUP BY status'), {'v':vid}).mappings().all()
        return {'indexVersion':2, 'pages': {r['status']:r['n'] for r in rows}, 'ocrWork':{r['status']:r['n'] for r in work}}

    def pages(self, owner, vid, after=-1, limit=50):
        from .material_service import MaterialService
        version=MaterialService(self.store).version(owner,vid)
        with self.store.engine.connect() as conn:
            rows=conn.execute(text('SELECT * FROM material_index_pages WHERE version_id=:v AND source_revision=:r AND page_index>:p ORDER BY page_index LIMIT :n'),
                {'v':vid,'r':version['sha256'],'p':after,'n':max(1,min(100,limit))+1}).mappings().all()
        more=len(rows)>limit
        rows=rows[:limit]
        return {'items':[{'pageIndex':r['page_index'],'pageLabel':r['page_label'],'status':r['status'],'sourceRevision':r['source_revision'],**json.loads(r['payload'])} for r in rows],
                'hasMore':more,'nextCursor':rows[-1]['page_index'] if more else None,'indexVersion':2}

    def retry_ocr(self, owner, vid, page):
        from .material_service import MaterialService,problem
        MaterialService(self.store).version(owner,vid)
        with self.store.transaction() as conn:
            changed=conn.execute(text("UPDATE material_ocr_work SET status='queued',lease=NULL,expires=NULL WHERE version_id=:v AND page_index=:p AND owner_id=:o AND status IN ('failed','timeout','unavailable') AND attempt<3"),
                {'v':vid,'p':page,'o':owner}).rowcount
            if not changed:problem('ocr_not_retryable','This page has no retryable OCR work or exhausted its three attempts.',409)
        return self.progress(owner,vid)

    def process_one(self):
        """One leased OCR page, bounded raster and deterministic canonical spans."""
        from .material_service import MaterialService, _ocr_pdf_pages
        now, lease = time.time(), uuid4().hex
        with self.store.transaction() as conn:
            conn.execute(text("UPDATE material_ocr_work SET status='failed',payload=:payload WHERE status='running' AND expires<:now AND attempt>=3"),
                {'now':now,'payload':pack({'error':'lease_attempts_exhausted'})})
            suffix = ' FOR UPDATE SKIP LOCKED' if conn.dialect.name=='postgresql' else ''
            row = conn.execute(text("SELECT * FROM material_ocr_work WHERE attempt<3 AND (status='queued' OR (status='running' AND expires<:now)) ORDER BY version_id,page_index LIMIT 1"+suffix), {'now':now}).mappings().first()
            if not row: return False
            changed = conn.execute(text("UPDATE material_ocr_work SET status='running',attempt=attempt+1,lease=:l,expires=:e WHERE version_id=:v AND page_index=:p AND (status='queued' OR (status='running' AND expires<:now))"),
                {'l':lease,'e':now+120,'v':row['version_id'],'p':row['page_index'],'now':now}).rowcount
            if not changed: return True
        svc = MaterialService(self.store)
        result = {'status':'failed'}
        try:
            version = svc.version(row['owner_id'],row['version_id'])
            if version['sha256']!=row['source_revision']: raise ValueError('source_changed')
            with tempfile.NamedTemporaryFile(prefix='openlearn-ocr-',delete=False) as temporary:
                path=Path(temporary.name)
            try:
                svc.objects.download_to_file(version['object_key'],path)
                if svc.digest_file(path)!=row['source_revision']: raise ValueError('source_changed')
                result = _ocr_pdf_pages(path,[row['page_index']]).get(row['page_index'],result)
            finally:
                path.unlink(missing_ok=True)
        except Exception:
            pass
        with self.store.transaction() as conn:
            current = conn.execute(text('SELECT v.sha256,v.status,m.deleted,m.role FROM material_versions v JOIN materials m ON m.id=v.material_id WHERE v.id=:v AND m.owner_id=:o'), {'v':row['version_id'],'o':row['owner_id']}).mappings().first()
            if not current or current['deleted'] or current['sha256']!=row['source_revision']: return True
            status=result.get('status','failed')
            changed=conn.execute(text("UPDATE material_ocr_work SET status=:s,payload=:payload WHERE version_id=:v AND page_index=:p AND lease=:l AND status='running' AND expires>:now"),
                {'s':status,'payload':pack({'confidence':result.get('confidence'),'recognizedChars':len(result.get('text',''))}), 'v':row['version_id'],'p':row['page_index'],'l':lease,'now':time.time()}).rowcount
            if not changed: return True
            page=conn.execute(text('SELECT * FROM material_index_pages WHERE version_id=:v AND page_index=:p'), {'v':row['version_id'],'p':row['page_index']}).mappings().first()
            if page:
                payload=json.loads(page['payload']);payload['ocr']={'status':status,'confidence':result.get('confidence')};payload['textChars']=len(result.get('text',''))
                conn.execute(text('UPDATE material_index_pages SET status=:s,payload=:payload WHERE version_id=:v AND page_index=:p'), {'s':status,'payload':pack(payload),'v':row['version_id'],'p':row['page_index']})
            if status=='completed' and result.get('text','').strip():
                indexed_chars=conn.execute(text('SELECT COALESCE(SUM(length(text)),0) FROM material_blocks WHERE version_id=:v'),{'v':row['version_id']}).scalar_one()
                existing_ocr_chars=conn.execute(text('SELECT COALESCE(SUM(length(text)),0) FROM material_blocks WHERE version_id=:v AND page_index=:p AND ordinal>=1000000'),{'v':row['version_id'],'p':row['page_index']}).scalar_one()
                if indexed_chars+max(0,min(200000,len(result['text']))-existing_ocr_chars)>5_000_000:
                    conn.execute(text("UPDATE material_ocr_work SET status='budget_exhausted' WHERE version_id=:v AND page_index=:p"),{'v':row['version_id'],'p':row['page_index']})
                    return True
                content=result['text'][:200000]
                for ordinal, offset in enumerate(range(0,len(content),3500)):
                    passage=content[offset:offset+3500];identifier=stable(row['version_id'],row['page_index'],'ocr',ordinal)
                    payload={'pageLabel':page['page_label'] if page else str(row['page_index']+1), 'extractionStatus':'ocr_extracted_estimated','ocrConfidence':result.get('confidence'), 'textHash':hashlib.sha256(passage.encode()).hexdigest(), 'geometry':{'status':'unavailable','regions':[]}}
                    conn.execute(text("INSERT INTO material_blocks(id,version_id,page_index,ordinal,kind,text,payload) VALUES(:id,:v,:p,:n,:kind,:t,:payload) ON CONFLICT(id) DO NOTHING"), {'id':identifier,'v':row['version_id'],'p':row['page_index'],'n':1000000+row['page_index']*100+ordinal,'kind':'private_solution' if current['role']=='answer_key' else 'passage','t':passage,'payload':pack(payload)})
                    # A repeated OCR attempt may return different wording. The
                    # immutable canonical passage owns its search/cue evidence.
                    canonical=conn.execute(text('SELECT text FROM material_blocks WHERE id=:id'),{'id':identifier}).scalar_one()
                    conn.execute(text('DELETE FROM material_index_terms WHERE block_id=:b'), {'b':identifier})
                    self.postings(conn,identifier,canonical);self.discover(conn,row['version_id'],row['page_index'],canonical,identifier)
                latest=conn.execute(text('SELECT payload FROM material_versions WHERE id=:v'),{'v':row['version_id']}).scalar_one()
                summary=json.loads(latest);summary['blockCount']=conn.execute(text('SELECT count(*) FROM material_blocks WHERE version_id=:v'),{'v':row['version_id']}).scalar_one()
                remaining=conn.execute(text("SELECT count(*) FROM material_ocr_work WHERE version_id=:v AND status IN ('queued','running')"),{'v':row['version_id']}).scalar_one()
                summary['ocrDeferredPageCount']=remaining;summary['ocrStatus']='partial' if remaining else 'complete'
                conn.execute(text("UPDATE material_versions SET status='partially_ready',payload=:payload WHERE id=:v AND status IN ('needs_attention','ready','partially_ready')"),{'v':row['version_id'],'payload':pack(summary)})
        return True
