"""Durable intake of Drive files, public URLs, and bounded uploads for class NeedInfo."""
from __future__ import annotations

import json
import hashlib
import tempfile
import time
from pathlib import Path
from threading import Lock
from uuid import uuid4
from urllib.parse import urlsplit

from fastapi import HTTPException
from sqlalchemy import text

from .in_class_models import ClassMaterialAttach
from .material_models import UploadRequest
from .material_service import MaterialService, encoded, problem
from .resource_intents import ConnectorRegistry, ResourceIntentService


class _StaleIntakeLease(Exception):
    pass


class MaterialOrchestrator:
    """Resolve class resource requests without running work in the note pipeline.

    The class worker calls ``tick`` with its bounded executor. URL and Drive
    acquisition plus material parsing run there; HTTP handlers admit/recover uploads.
    """

    def __init__(self, store):
        self.store = store
        self.materials = MaterialService(store)
        self._active_lock = Lock()
        self._active_urls: set[str] = set()
        self._processor_running = False
        self._max_active_intakes = 2

    def _class(self, conn, owner, class_id, lock=False):
        from .in_class_service import InClassService
        service = InClassService(self.store)
        item = service.row(conn, owner, class_id, lock)
        return item

    @staticmethod
    def _need(conn, item, need_id):
        from .class_metadata import get_need
        need = get_need(conn, item['owner'], item['id'], need_id)
        if need is None:
            problem('need_info_not_found', 'This material request is no longer available.', 404)
        return need

    def _canvas_source(self, conn, owner, course_id, connection_id, entity_id):
        """Resolve a synced Canvas coverage entity through its immutable facts."""
        from .academic_planning import AcademicPlanningService
        academics = AcademicPlanningService(self.store)
        self._class_course(conn, owner, course_id)
        entity = next((value for value in academics.rows(conn, 'academic_entities', owner, course_id)
                       if value['id'] == entity_id and value.get('kind') == 'coverage'), None)
        if entity is None:
            raise HTTPException(404, {'code': 'canvas_source_unavailable', 'message': 'This Canvas course source is unavailable.'})
        connection = next((value for value in academics.rows(conn, 'canvas_connections', owner)
                           if value.get('id') == connection_id), None)
        if (not connection or connection.get('status') != 'paired'
                or float(connection.get('expiresAt') or 0) <= time.time()):
            raise HTTPException(409, {'code': 'canvas_connection_unavailable', 'message': 'Reconnect Canvas before importing this source.'})
        observation_rows = academics.rows(conn, 'academic_observations', owner, course_id)
        observations = {value['id']: value for value in observation_rows}
        chosen = {}
        for field_name in ('title', 'instructions'):
            fact = entity.get('facts', {}).get(field_name) or {}
            observation = observations.get(fact.get('observationId'))
            if (not observation or observation.get('origin') != 'canvas'
                    or observation.get('entityId') != entity_id
                    or observation.get('field') != field_name
                    or observation.get('value') != fact.get('value')):
                raise HTTPException(404, {'code': 'canvas_source_unavailable', 'message': 'This Canvas course source is unavailable.'})
            source = observation.get('source') or {}
            if source.get('connectionId') != connection_id:
                raise HTTPException(404, {'code': 'canvas_source_unavailable', 'message': 'This Canvas course source is unavailable.'})
            locator = source.get('locator')
            parsed = urlsplit(locator or '')
            origin = connection.get('origin')
            if (not isinstance(locator, str) or len(locator) > 2048
                    or parsed.scheme != 'https' or not parsed.netloc or parsed.username or parsed.password
                    or f'{parsed.scheme}://{parsed.netloc}' != origin):
                raise HTTPException(404, {'code': 'canvas_source_unavailable', 'message': 'This Canvas course source is unavailable.'})
            segments = [segment for segment in parsed.path.split('/') if segment]
            external_courses = [str(external) for external, internal in (connection.get('courses') or {}).items()
                                if str(internal) == str(course_id)]
            external_course = next((external for external in external_courses
                                    if len(segments) >= 2 and segments[0] == 'courses' and segments[1] == external), None)
            if (not external_course or not source.get('revision') or len(str(source['revision'])) > 160
                    or not isinstance(fact.get('value'), str)):
                raise HTTPException(404, {'code': 'canvas_source_unavailable', 'message': 'This Canvas course source is unavailable.'})
            chosen[field_name] = {'value': fact['value'], 'source': source}
        title = chosen['title']['value'].strip()
        instructions = chosen['instructions']['value'].strip()
        title_source, instructions_source = chosen['title']['source'], chosen['instructions']['source']
        if (not title or len(title) > 500 or not instructions or len(instructions) > 20_000
                or title_source.get('locator') != instructions_source.get('locator')
                or title_source.get('revision') != instructions_source.get('revision')):
            raise HTTPException(404, {'code': 'canvas_source_unavailable', 'message': 'This Canvas course source is unavailable.'})
        source_revision = str(instructions_source['revision'])
        content_hash = hashlib.sha256(encoded({'title': title, 'instructions': instructions}).encode()).hexdigest()
        preview = ' '.join(instructions.split())[:240]
        return {'entityId': entity_id, 'entityRevision': entity.get('revision'),
                'connectionId': connection_id, 'sourceRevision': source_revision,
                'contentHash': content_hash, 'title': title, 'instructions': instructions,
                'preview': preview, 'lastSuccessfulSync': connection.get('lastSuccessfulSync')}

    def _class_course(self, conn, owner, course_id):
        if not conn.execute(text('SELECT id FROM courses WHERE id=:course AND owner_id=:owner AND archived_at IS NULL'),
                            {'course': course_id, 'owner': owner}).first():
            raise HTTPException(404, {'code': 'class_not_found', 'message': 'This class is unavailable.'})

    def canvas_sources(self, owner, class_id):
        from .academic_planning import AcademicPlanningService
        with self.store.engine.connect() as conn:
            item = self._class(conn, owner, class_id)
            if not item.get('courseId'):
                return {'items': []}
            academics = AcademicPlanningService(self.store)
            candidates = academics.rows(conn, 'academic_entities', owner, item['courseId'])
            rows = []
            for entity in candidates:
                if entity.get('kind') != 'coverage':
                    continue
                for connection in academics.rows(conn, 'canvas_connections', owner):
                    try:
                        source = self._canvas_source(conn, owner, item['courseId'], connection.get('id'), entity['id'])
                    except HTTPException:
                        continue
                    rows.append({key: source[key] for key in ('entityId', 'connectionId', 'title', 'preview', 'sourceRevision', 'lastSuccessfulSync')})
                    break
        rows.sort(key=lambda value: (value.get('title', '').casefold(), value['entityId']))
        return {'items': rows[:200]}

    def start(self, owner, class_id, need_id, command):
        now = time.time()
        request_data = command.model_dump(by_alias=True, mode='json')
        request_data.pop('expectedRevision', None)
        request_hash = hashlib.sha256(encoded(request_data).encode()).hexdigest()
        with self.store.transaction() as conn:
            item = self._class(conn, owner, class_id, True)
            existing = conn.execute(text(
                'SELECT * FROM class_material_intakes WHERE owner_id=:owner AND class_id=:class '
                'AND need_id=:need AND command_id=:command'
            ), {'owner': owner, 'class': class_id, 'need': need_id, 'command': command.command_id}).mappings().first()
            if existing:
                if json.loads(existing['payload'] or '{}').get('requestHash') != request_hash:
                    raise HTTPException(409, {'code': 'idempotency_conflict', 'message': 'This command ID was already used for a different source request.'})
                return self._receipt(dict(existing))
            if item['revision'] != command.expected_revision:
                raise HTTPException(409, {'code': 'revision_conflict', 'message': 'Refresh this class session before adding a source.'})
            if item.get('cancelled'):
                raise HTTPException(409, {'code': 'class_paused', 'message': 'Resume class processing before adding a source.'})
            if not item.get('policy', {}).get('materials', False):
                raise HTTPException(409, {'code': 'materials_disabled', 'message': 'Enable related course materials before adding a source.'})
            need = self._need(conn, item, need_id)
            if need['status'] != 'open':
                raise HTTPException(409, {'code': 'need_info_closed', 'message': 'This material request has already been resolved.'})
            # Materialize the existing NeedInfo record into the stable resource
            # contract. Reconcile an earlier failed intake before admitting a
            # new explicitly selected source.
            ResourceIntentService.ensure_need(conn, owner, class_id, item.get('courseId'), need)
            prior_intake = conn.execute(text(
                'SELECT * FROM class_material_intakes WHERE owner_id=:owner AND class_id=:class AND need_id=:need '
                'ORDER BY created_at DESC,id DESC LIMIT 1'
            ), {'owner': owner, 'class': class_id, 'need': need_id}).mappings().first()
            if prior_intake:
                ResourceIntentService.reconcile_intake(
                    conn, owner, class_id, item.get('courseId'), need, dict(prior_intake)
                )
            active = conn.execute(text(
                "SELECT id FROM class_material_intakes WHERE owner_id=:owner AND class_id=:class "
                "AND need_id=:need AND status NOT IN ('attached','failed') LIMIT 1"
            ), {'owner': owner, 'class': class_id, 'need': need_id}).first()
            if active:
                raise HTTPException(409, {'code': 'need_info_in_progress', 'message': 'A source is already being added for this class request.'})

            material_id = version_id = None
            status = 'queued'
            payload = {}
            if command.source_kind == 'url':
                if not command.url or command.title or command.media_type or command.byte_count or command.connection_id or command.file_id or command.entity_id:
                    problem('invalid_material_intake', 'Provide a URL for URL imports.')
                payload = {'url': command.url, 'requestHash': request_hash}
            elif command.source_kind == 'upload':
                if command.url or command.connection_id or command.file_id or command.entity_id or not command.title or not command.media_type or not command.byte_count:
                    problem('invalid_material_intake', 'Provide a title, supported media type, and byte count for uploads.')
                created = self.materials.create(owner, UploadRequest(
                    title=command.title, media_type=command.media_type,
                    byte_count=command.byte_count, role='reference', course_id=item['courseId'],
                ), connection=conn)
                material_id, version_id = created['materialId'], created['versionId']
                status = 'awaiting_upload'
                payload = {'requestHash': request_hash}
            elif command.source_kind == 'drive':
                if command.url or command.title or command.media_type or command.byte_count or command.entity_id or not command.connection_id or not command.file_id:
                    problem('invalid_material_intake', 'Provide a connected Drive source and file ID for Drive imports.')
                # Admission is owner-scoped and local: verify the saved connection
                # and granted capability without fetching provider data here.
                from .agent_execution.google_connector import GoogleConnections, enabled as connectors_enabled
                if not connectors_enabled():
                    raise HTTPException(409, {'code': 'drive_unavailable', 'message': 'Google Drive imports are unavailable right now.'})
                connection = GoogleConnections(self.store).row(conn, owner, command.connection_id)
                connection_payload = json.loads(connection.get('payload') or '{}')
                if connection_payload.get('provider') != 'google' or connection.get('status') != 'connected' or 'drive_read' not in connection_payload.get('capabilities', []):
                    raise HTTPException(403, {'code': 'drive_access_denied', 'message': 'This connection does not have Google Drive read access.'})
                payload = {'connectionId': command.connection_id, 'fileId': command.file_id, 'requestHash': request_hash}
            else:
                if (command.url or command.title or command.media_type or command.byte_count
                        or command.file_id or not command.connection_id or not command.entity_id):
                    problem('invalid_material_intake', 'Provide a synced Canvas source for Canvas imports.')
                source = self._canvas_source(conn, owner, item['courseId'], command.connection_id, command.entity_id)
                payload = {'connectionId': command.connection_id, 'entityId': command.entity_id,
                           'entityRevision': source['entityRevision'], 'sourceRevision': source['sourceRevision'],
                           'contentHash': source['contentHash'], 'requestHash': request_hash}

            intake_id = 'class_intake_' + uuid4().hex
            conn.execute(text(
                'INSERT INTO class_material_intakes(id,owner_id,class_id,need_id,command_id,source_kind,status,'
                'material_id,version_id,attempt,payload,created_at,updated_at) '
                'VALUES(:id,:owner,:class,:need,:command,:kind,:status,:material,:version,0,:payload,:now,:now)'
            ), {'id': intake_id, 'owner': owner, 'class': class_id, 'need': need_id,
                'command': command.command_id, 'kind': command.source_kind, 'status': status,
                'material': material_id, 'version': version_id, 'payload': encoded(payload), 'now': now})
            if command.source_kind == 'url':
                selected_resource = {
                    'kind': 'url',
                    'host': (urlsplit(command.url).hostname or '')[:255],
                    'urlHash': hashlib.sha256(command.url.encode()).hexdigest(),
                }
            elif command.source_kind == 'upload':
                selected_resource = {
                    'kind': 'upload', 'materialId': material_id, 'versionId': version_id,
                    'mediaType': command.media_type, 'byteCount': command.byte_count,
                }
            elif command.source_kind == 'drive':
                selected_resource = {'kind': 'drive', 'connectionId': command.connection_id, 'fileId': command.file_id}
            else:
                selected_resource = {
                    'kind': 'canvas', 'connectionId': command.connection_id, 'entityId': command.entity_id,
                    'sourceRevision': payload.get('sourceRevision'), 'contentHash': payload.get('contentHash'),
                }
            ResourceIntentService.record_selection(
                conn, owner, class_id, item.get('courseId'), need, ConnectorRegistry.source_kind(command.source_kind),
                command.command_id, request_hash, selected_resource,
            )
            row = conn.execute(text('SELECT * FROM class_material_intakes WHERE id=:id'), {'id': intake_id}).mappings().one()
            return self._receipt(dict(row))

    @staticmethod
    def _receipt(row):
        receipt = {'intakeId': row['id'], 'classId': row['class_id'], 'needId': row['need_id'],
                   'commandId': row['command_id'], 'sourceKind': row['source_kind'], 'status': row['status'],
                   'materialId': row['material_id'], 'versionId': row['version_id'],
                   'error': row['error']}
        if row['source_kind'] == 'drive':
            payload = json.loads(row.get('payload') or '{}')
            if payload.get('connectionId') and payload.get('fileId'):
                receipt['connectionId'] = payload['connectionId']
                receipt['fileId'] = payload['fileId']
        if row['source_kind'] == 'canvas':
            payload = json.loads(row.get('payload') or '{}')
            for key in ('connectionId', 'entityId', 'sourceRevision'):
                if payload.get(key):
                    receipt[key] = payload[key]
        if row['status'] == 'awaiting_upload' and row['material_id'] and row['version_id']:
            receipt['uploadPath'] = f"/v1/class-sessions/{row['class_id']}/material-intakes/{row['id']}/content"
            receipt['resumableUploadPath'] = f"/v1/class-sessions/{row['class_id']}/material-intakes/{row['id']}/uploads"
        return receipt

    def upload_context(self, owner, class_id, intake_id, upload_id=None):
        with self.store.transaction() as conn:
            suffix = ' FOR UPDATE' if conn.dialect.name == 'postgresql' else ''
            row = conn.execute(text(
                'SELECT * FROM class_material_intakes WHERE id=:id AND class_id=:class AND owner_id=:owner' + suffix
            ), {'id': intake_id, 'class': class_id, 'owner': owner}).mappings().first()
            if not row:
                problem('material_intake_not_found', 'This material intake is unavailable.', 404)
            row = dict(row)
            if row['status'] not in {'awaiting_upload', 'processing'}:
                problem('material_intake_state', 'This upload is no longer accepting bytes.', 409)
            item = self._class(conn, owner, class_id, True)
            need = self._need(conn, item, row['need_id'])
            if item.get('cancelled') or not item.get('policy', {}).get('materials') or need['status'] != 'open':
                problem('need_info_closed', 'This class material request is no longer active.', 409)
            if upload_id:
                session = conn.execute(text(
                    'SELECT version_id,class_id,intake_id FROM material_upload_sessions WHERE id=:id AND owner_id=:owner'
                ), {'id': upload_id, 'owner': owner}).mappings().first()
                if (not session or session['version_id'] != row['version_id']
                        or session['class_id'] != class_id or session['intake_id'] != intake_id):
                    problem('upload_not_found', 'This upload is unavailable.', 404)
            return row

    def upload(self, owner, class_id, intake_id, content):
        with tempfile.NamedTemporaryFile(prefix='openlearn-class-material-', delete=False) as output:
            path = Path(output.name)
            output.write(content)
        try:
            return self.upload_file(owner, class_id, intake_id, path)
        finally:
            path.unlink(missing_ok=True)

    def upload_file(self, owner, class_id, intake_id, path):
        with self.store.engine.connect() as conn:
            row = conn.execute(text('SELECT * FROM class_material_intakes WHERE id=:id AND class_id=:class AND owner_id=:owner'),
                               {'id': intake_id, 'class': class_id, 'owner': owner}).mappings().first()
        if not row:
            problem('material_intake_not_found', 'This material intake is unavailable.', 404)
        row = dict(row)
        if row['source_kind'] != 'upload':
            problem('invalid_material_intake', 'This intake does not accept file bytes.', 409)
        if row['status'] not in {'awaiting_upload', 'processing', 'attached'}:
            problem('material_intake_state', 'This upload is no longer accepting bytes.', 409)
        if row['status'] == 'attached':
            version = self.materials.version(owner, row['version_id'])
            if version['sha256'] != self.materials.digest_file(path):
                problem('upload_conflict', 'Upload already completed with different bytes.', 409)
            return self.get(owner, class_id, intake_id)
        row = self.upload_context(owner, class_id, intake_id)
        try:
            self.materials.upload_file(owner, row['material_id'], row['version_id'], path)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            code = detail.get('code')
            if code in {'upload_size_mismatch', 'invalid_pdf', 'invalid_image', 'invalid_text', 'image_too_large', 'immutable_version'}:
                message = str(detail.get('message') or 'This file could not be used. Please choose another source.')[:500]
                with self.store.transaction() as conn:
                    conn.execute(text(
                        "UPDATE class_material_intakes SET status='failed',error=:error,updated_at=:now "
                        "WHERE id=:id AND owner_id=:owner AND status IN ('awaiting_upload','processing')"
                    ), {'error': message, 'now': time.time(), 'id': intake_id, 'owner': owner})
                self.materials.delete(owner, row['material_id'])
            raise
        stale = False
        with self.store.transaction() as conn:
            current = conn.execute(text(
                'SELECT status FROM class_material_intakes WHERE id=:id AND class_id=:class AND owner_id=:owner'
                + (' FOR UPDATE' if conn.dialect.name == 'postgresql' else '')
            ), {'id': intake_id, 'class': class_id, 'owner': owner}).mappings().first()
            item = self._class(conn, owner, class_id, True)
            need = self._need(conn, item, row['need_id'])
            if (not current or current['status'] not in {'awaiting_upload', 'processing'}
                    or item.get('cancelled') or not item.get('policy', {}).get('materials')
                    or need['status'] != 'open'):
                if current:
                    conn.execute(text(
                        "UPDATE class_material_intakes SET status='failed',error=:error,updated_at=:now "
                        "WHERE id=:id AND owner_id=:owner AND status IN ('awaiting_upload','processing')"
                    ), {'error': 'The class material request closed before this upload finished.',
                        'now': time.time(), 'id': intake_id, 'owner': owner})
                stale = True
            else:
                conn.execute(text(
                    "UPDATE class_material_intakes SET status='processing',updated_at=:now "
                    "WHERE id=:id AND owner_id=:owner AND status='awaiting_upload'"
                ), {'now': time.time(), 'id': intake_id, 'owner': owner})
        if stale:
            self.materials.delete(owner, row['material_id'])
            problem('need_info_closed', 'This class material request is no longer active.', 409)
        return self.get(owner, class_id, intake_id)

    def get(self, owner, class_id, intake_id):
        with self.store.engine.connect() as conn:
            row = conn.execute(text('SELECT * FROM class_material_intakes WHERE id=:id AND class_id=:class AND owner_id=:owner'),
                               {'id': intake_id, 'class': class_id, 'owner': owner}).mappings().first()
        if not row:
            problem('material_intake_not_found', 'This material intake is unavailable.', 404)
        return self._receipt(dict(row))

    def list_for_class(self, owner, class_id, need_id=None):
        with self.store.engine.connect() as conn:
            item = self._class(conn, owner, class_id)
            from .class_metadata import get_need
            if need_id is not None and get_need(conn, owner, class_id, need_id) is None:
                problem('need_info_not_found', 'This material request is unavailable.', 404)
            sql = 'SELECT * FROM class_material_intakes WHERE owner_id=:owner AND class_id=:class'
            params = {'owner': owner, 'class': class_id}
            if need_id is not None:
                sql += ' AND need_id=:need'; params['need'] = need_id
            sql += ' ORDER BY created_at DESC LIMIT 100'
            rows = conn.execute(text(sql), params).mappings().all()
        return {'intakes': [self._receipt(dict(row)) for row in rows]}

    def _claim_urls(self, limit=2):
        now = time.time()
        claimed = []
        with self.store.transaction() as conn:
            rows = conn.execute(text(
                "SELECT id FROM class_material_intakes WHERE status='queued' OR "
                "(status='fetching' AND lease_expires<:now) ORDER BY created_at LIMIT :limit"
            ), {'now': now, 'limit': limit}).scalars().all()
            for intake_id in rows:
                with self._active_lock:
                    if len(self._active_urls) >= self._max_active_intakes:
                        break
                    if intake_id in self._active_urls:
                        continue
                    self._active_urls.add(intake_id)
                token = uuid4().hex
                changed = conn.execute(text(
                    "UPDATE class_material_intakes SET status='fetching',lease_token=:token,lease_expires=:expires,"
                    "attempt=attempt+1,updated_at=:now WHERE id=:id AND (status='queued' OR (status='fetching' AND lease_expires<:now))"
                ), {'token': token, 'expires': now + 90, 'now': now, 'id': intake_id}).rowcount
                if changed:
                    claimed.append((intake_id, token))
                else:
                    self._forget_url(intake_id)
        return claimed

    def _claim_uploads(self, limit=2):
        now = time.time()
        claimed = []
        with self.store.transaction() as conn:
            rows = conn.execute(text("SELECT id FROM class_material_intakes WHERE status='uploading' AND (lease_expires IS NULL OR lease_expires<:now) ORDER BY updated_at LIMIT :limit"),
                                {'now': now, 'limit': limit}).scalars().all()
            for intake_id in rows:
                with self._active_lock:
                    if len(self._active_urls) >= self._max_active_intakes:
                        break
                    if intake_id in self._active_urls:
                        continue
                    self._active_urls.add(intake_id)
                token = uuid4().hex
                changed = conn.execute(text("UPDATE class_material_intakes SET lease_token=:token,lease_expires=:expires,updated_at=:now WHERE id=:id AND status='uploading' AND (lease_expires IS NULL OR lease_expires<:now)"),
                                       {'token': token, 'expires': now + 90, 'now': now, 'id': intake_id}).rowcount
                if changed:
                    claimed.append((intake_id, token))
                else:
                    self._forget_url(intake_id)
        return claimed

    def _lease_row(self, conn, *, intake_id, owner, class_id, token, status):
        suffix = ' FOR UPDATE' if conn.dialect.name == 'postgresql' else ''
        return conn.execute(text("SELECT id FROM class_material_intakes WHERE id=:id AND owner_id=:owner AND class_id=:class AND status=:status AND lease_token=:token AND lease_expires>:now" + suffix),
                            {'id': intake_id, 'owner': owner, 'class': class_id, 'status': status,
                             'token': token, 'now': time.time()}).first()

    def _fetch_url(self, intake_id, token):
        from .url_ingestion import fetch_public_page
        with self.store.engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM class_material_intakes WHERE id=:id AND status='fetching' AND lease_token=:token AND lease_expires>:now"),
                               {'id': intake_id, 'token': token, 'now': time.time()}).mappings().first()
        if not row:
            return
        row = dict(row)
        if row['source_kind'] == 'drive':
            return self._fetch_drive(row, token)
        if row['source_kind'] == 'canvas':
            return self._fetch_canvas(row, token)
        try:
            page = fetch_public_page(json.loads(row['payload'])['url'])
            content = page['text'].encode('utf-8')
            with self.store.transaction() as conn:
                item = self._class(conn, row['owner_id'], row['class_id'], True)
                if not self._lease_row(conn, intake_id=intake_id, owner=row['owner_id'], class_id=row['class_id'], token=token, status='fetching'):
                    raise _StaleIntakeLease()
                need = self._need(conn, item, row['need_id'])
                if item.get('cancelled') or not item.get('policy', {}).get('materials') or need['status'] != 'open':
                    raise HTTPException(409, {'code': 'need_info_closed', 'message': 'The class material request is no longer active.'})
                created = self.materials.create(row['owner_id'], UploadRequest(
                    title=page['title'], media_type='text/plain', byte_count=len(content),
                    role='reference', course_id=item['courseId'],
                ), connection=conn)
                original_payload = json.loads(row['payload'] or '{}')
                changed = conn.execute(text("UPDATE class_material_intakes SET status='uploading',material_id=:material,version_id=:version,payload=:payload,lease_expires=:expires,updated_at=:now WHERE id=:id AND owner_id=:owner AND class_id=:class AND status='fetching' AND lease_token=:token AND lease_expires>:now"),
                             {'material': created['materialId'], 'version': created['versionId'],
                              'payload': encoded({'url': page['url'], 'title': page['title'], 'text': page['text'], 'requestHash': original_payload.get('requestHash')}),
                              'expires': time.time() + 90, 'now': time.time(), 'id': intake_id,
                              'owner': row['owner_id'], 'class': row['class_id'], 'token': token}).rowcount
                if changed != 1:
                    raise _StaleIntakeLease()
            self._finish_url_upload(intake_id, token)
        except _StaleIntakeLease:
            return
        except Exception as exc:
            detail = getattr(exc, 'detail', None)
            message = detail.get('message') if isinstance(detail, dict) else None
            safe_message = message or 'The page could not be imported. Check the URL and try another source.'
            with self.store.transaction() as conn:
                conn.execute(text("UPDATE class_material_intakes SET status='failed',error=:error,lease_token=NULL,lease_expires=NULL,updated_at=:now WHERE id=:id AND owner_id=:owner AND class_id=:class AND lease_token=:token AND lease_expires>:now AND status='fetching'"),
                             {'error': safe_message[:500], 'now': time.time(), 'id': intake_id,
                              'owner': row['owner_id'], 'class': row['class_id'], 'token': token})

    def _fetch_drive(self, row, token):
        """Import a Drive file through the connector ledger, then await indexing."""
        try:
            payload = json.loads(row['payload'] or '{}')
            connection_id, file_id = payload.get('connectionId'), payload.get('fileId')
            if not connection_id or not file_id:
                raise ValueError('missing Drive source')
            # Recheck the mutable class/NeedInfo boundary after the worker claim.
            with self.store.transaction() as conn:
                item = self._class(conn, row['owner_id'], row['class_id'], True)
                if not self._lease_row(conn, intake_id=row['id'], owner=row['owner_id'], class_id=row['class_id'], token=token, status='fetching'):
                    raise _StaleIntakeLease()
                need = self._need(conn, item, row['need_id'])
                if item.get('cancelled') or not item.get('policy', {}).get('materials') or need['status'] != 'open':
                    raise HTTPException(409, {'code': 'need_info_closed', 'message': 'The class material request is no longer active.'})

            from .agent_execution.connector_intake import ConnectorIntake
            imported = ConnectorIntake(self.store).drive(
                row['owner_id'], connection_id, file_id,
                f"class-material-intake:{row['id']}",
            )
            # Drive material creation is independently idempotent. A stale
            # lease may finish its read, but cannot advance or attach the intake.
            with self.store.transaction() as conn:
                item = self._class(conn, row['owner_id'], row['class_id'], True)
                if not self._lease_row(conn, intake_id=row['id'], owner=row['owner_id'], class_id=row['class_id'], token=token, status='fetching'):
                    raise _StaleIntakeLease()
                need = self._need(conn, item, row['need_id'])
                if need['status'] != 'open':
                    raise HTTPException(409, {'code': 'need_info_closed', 'message': 'The class material request is no longer active.'})
                version = self.materials.version(row['owner_id'], imported['versionId'], conn)
                if (version.get('course_id') not in {None, item['courseId']}
                        or version.get('role') in {'answer_key', 'sample_paper'}
                        or version.get('media_type') not in {'application/pdf', 'text/plain', 'text/markdown'}
                        or version.get('byte_count', 0) > 5_000_000):
                    raise HTTPException(409, {'code': 'material_ineligible', 'message': 'This Drive file is not eligible for this class request.'})
                changed = conn.execute(text(
                    "UPDATE class_material_intakes SET status='processing',material_id=:material,version_id=:version,"
                    "payload=:payload,lease_token=NULL,lease_expires=NULL,error=NULL,updated_at=:now "
                    "WHERE id=:id AND owner_id=:owner AND class_id=:class AND status='fetching' AND lease_token=:token AND lease_expires>:now"
                ), {'material': imported['materialId'], 'version': imported['versionId'],
                    'payload': encoded({'connectionId': connection_id, 'fileId': file_id,
                                        'requestHash': payload.get('requestHash'),
                                        'provenance': imported.get('provenance')}),
                    'now': time.time(), 'id': row['id'], 'owner': row['owner_id'], 'class': row['class_id'], 'token': token}).rowcount
                if changed != 1:
                    raise _StaleIntakeLease()
        except _StaleIntakeLease:
            return
        except Exception:
            # Connector/provider exception text can contain sensitive details;
            # persist a stable, user-safe message only.
            with self.store.transaction() as conn:
                conn.execute(text(
                    "UPDATE class_material_intakes SET status='failed',error=:error,lease_token=NULL,lease_expires=NULL,updated_at=:now "
                    "WHERE id=:id AND owner_id=:owner AND class_id=:class AND status='fetching' AND lease_token=:token AND lease_expires>:now"
                ), {'error': 'The Drive file could not be imported. Check the connection and file access, then try again.',
                    'now': time.time(), 'id': row['id'], 'owner': row['owner_id'], 'class': row['class_id'], 'token': token})

    def _fetch_canvas(self, row, token):
        """Materialize only the currently synced text revision from Canvas."""
        payload = json.loads(row['payload'] or '{}')
        try:
            with self.store.transaction() as conn:
                item = self._class(conn, row['owner_id'], row['class_id'], True)
                if not self._lease_row(conn, intake_id=row['id'], owner=row['owner_id'], class_id=row['class_id'], token=token, status='fetching'):
                    raise _StaleIntakeLease()
                need = self._need(conn, item, row['need_id'])
                if item.get('cancelled') or not item.get('policy', {}).get('materials') or need['status'] != 'open':
                    raise HTTPException(409, {'code': 'need_info_closed', 'message': 'The class material request is no longer active.'})
                source = self._canvas_source(conn, row['owner_id'], item['courseId'], payload['connectionId'], payload['entityId'])
                if (source['sourceRevision'] != payload.get('sourceRevision')
                        or source['contentHash'] != payload.get('contentHash')):
                    raise HTTPException(409, {'code': 'canvas_source_changed', 'message': 'This Canvas source changed. Refresh the course sources and try again.'})
                content = (source['title'] + '\n\n' + source['instructions']).encode('utf-8')
                created = self.materials.create(row['owner_id'], UploadRequest(
                    title=source['title'][:300], media_type='text/plain', byte_count=len(content),
                    role='reference', course_id=item['courseId'],
                ), connection=conn)
                pinned_payload = {key: payload[key] for key in
                                  ('connectionId', 'entityId', 'entityRevision', 'sourceRevision', 'contentHash', 'requestHash')}
                changed = conn.execute(text(
                    "UPDATE class_material_intakes SET status='uploading',material_id=:material,version_id=:version,"
                    "payload=:payload,lease_expires=:expires,updated_at=:now "
                    "WHERE id=:id AND owner_id=:owner AND class_id=:class AND status='fetching' AND lease_token=:token AND lease_expires>:now"
                ), {'material': created['materialId'], 'version': created['versionId'], 'payload': encoded(pinned_payload),
                    'expires': time.time() + 90, 'now': time.time(), 'id': row['id'], 'owner': row['owner_id'],
                    'class': row['class_id'], 'token': token}).rowcount
                if changed != 1:
                    raise _StaleIntakeLease()
            self._finish_canvas_upload(row['id'], token)
        except _StaleIntakeLease:
            return
        except Exception:
            with self.store.transaction() as conn:
                conn.execute(text(
                    "UPDATE class_material_intakes SET status='failed',error=:error,lease_token=NULL,lease_expires=NULL,updated_at=:now "
                    "WHERE id=:id AND owner_id=:owner AND class_id=:class AND status='fetching' AND lease_token=:token AND lease_expires>:now"
                ), {'error': 'The Canvas source could not be imported. Refresh the course sources and try again.',
                    'now': time.time(), 'id': row['id'], 'owner': row['owner_id'], 'class': row['class_id'], 'token': token})

    def _finish_url_upload(self, intake_id, token):
        with self.store.engine.connect() as conn:
            row = conn.execute(text("SELECT * FROM class_material_intakes WHERE id=:id AND status='uploading' AND lease_token=:token AND lease_expires>:now"),
                               {'id': intake_id, 'token': token, 'now': time.time()}).mappings().first()
        if not row:
            return
        row = dict(row)
        if row['source_kind'] == 'canvas':
            return self._finish_canvas_upload(intake_id, token, row)
        content = json.loads(row['payload']).get('text', '').encode('utf-8')
        try:
            self.materials.upload(row['owner_id'], row['material_id'], row['version_id'], content)
            with self.store.transaction() as conn:
                self._class(conn, row['owner_id'], row['class_id'], True)
                if not self._lease_row(conn, intake_id=intake_id, owner=row['owner_id'], class_id=row['class_id'], token=token, status='uploading'):
                    raise _StaleIntakeLease()
                saved_payload = json.loads(row['payload'] or '{}')
                changed = conn.execute(text("UPDATE class_material_intakes SET status='processing',payload=:payload,lease_token=NULL,lease_expires=NULL,updated_at=:now WHERE id=:id AND owner_id=:owner AND class_id=:class AND status='uploading' AND lease_token=:token AND lease_expires>:now"),
                             {'payload': encoded({'url': saved_payload.get('url'), 'title': saved_payload.get('title'), 'requestHash': saved_payload.get('requestHash')}),
                              'now': time.time(), 'id': intake_id, 'owner': row['owner_id'], 'class': row['class_id'], 'token': token}).rowcount
                if changed != 1:
                    raise _StaleIntakeLease()
        except _StaleIntakeLease:
            return
        except Exception as exc:
            detail = getattr(exc, 'detail', None)
            message = detail.get('message') if isinstance(detail, dict) else None
            with self.store.transaction() as conn:
                self._class(conn, row['owner_id'], row['class_id'], True)
                if not self._lease_row(conn, intake_id=intake_id, owner=row['owner_id'], class_id=row['class_id'], token=token, status='uploading'):
                    return
                changed = conn.execute(text("UPDATE class_material_intakes SET status='failed',error=:error,lease_token=NULL,lease_expires=NULL,updated_at=:now WHERE id=:id AND owner_id=:owner AND class_id=:class AND status='uploading' AND lease_token=:token AND lease_expires>:now"),
                             {'error': (message or 'The page text could not be saved.')[:500], 'now': time.time(), 'id': intake_id,
                              'owner': row['owner_id'], 'class': row['class_id'], 'token': token}).rowcount
                if changed != 1:
                    raise _StaleIntakeLease()

    def _finish_canvas_upload(self, intake_id, token, row=None):
        if row is None:
            with self.store.engine.connect() as conn:
                row = conn.execute(text("SELECT * FROM class_material_intakes WHERE id=:id AND status='uploading' AND lease_token=:token AND lease_expires>:now"),
                                   {'id': intake_id, 'token': token, 'now': time.time()}).mappings().first()
            if not row:
                return
        row = dict(row)
        payload = json.loads(row['payload'] or '{}')
        try:
            with self.store.transaction() as conn:
                item = self._class(conn, row['owner_id'], row['class_id'], True)
                if not self._lease_row(conn, intake_id=intake_id, owner=row['owner_id'], class_id=row['class_id'], token=token, status='uploading'):
                    raise _StaleIntakeLease()
                need = self._need(conn, item, row['need_id'])
                if item.get('cancelled') or not item.get('policy', {}).get('materials') or need['status'] != 'open':
                    raise HTTPException(409, {'code': 'need_info_closed', 'message': 'The class material request is no longer active.'})
                source = self._canvas_source(conn, row['owner_id'], item['courseId'], payload['connectionId'], payload['entityId'])
                if (source['sourceRevision'] != payload.get('sourceRevision')
                        or source['contentHash'] != payload.get('contentHash')):
                    raise HTTPException(409, {'code': 'canvas_source_changed', 'message': 'This Canvas source changed during import.'})
            content = (source['title'] + '\n\n' + source['instructions']).encode('utf-8')
            self.materials.upload(row['owner_id'], row['material_id'], row['version_id'], content)
            with self.store.transaction() as conn:
                item = self._class(conn, row['owner_id'], row['class_id'], True)
                if not self._lease_row(conn, intake_id=intake_id, owner=row['owner_id'], class_id=row['class_id'], token=token, status='uploading'):
                    raise _StaleIntakeLease()
                need = self._need(conn, item, row['need_id'])
                if need['status'] != 'open':
                    raise HTTPException(409, {'code': 'need_info_closed', 'message': 'The class material request is no longer active.'})
                current = self._canvas_source(conn, row['owner_id'], item['courseId'], payload['connectionId'], payload['entityId'])
                if (current['sourceRevision'] != payload.get('sourceRevision')
                        or current['contentHash'] != payload.get('contentHash')):
                    raise HTTPException(409, {'code': 'canvas_source_changed', 'message': 'This Canvas source changed during import.'})
                changed = conn.execute(text(
                    "UPDATE class_material_intakes SET status='processing',lease_token=NULL,lease_expires=NULL,error=NULL,updated_at=:now "
                    "WHERE id=:id AND owner_id=:owner AND class_id=:class AND status='uploading' AND lease_token=:token AND lease_expires>:now"
                ), {'now': time.time(), 'id': intake_id, 'owner': row['owner_id'], 'class': row['class_id'], 'token': token}).rowcount
                if changed != 1:
                    raise _StaleIntakeLease()
        except _StaleIntakeLease:
            return
        except Exception:
            cleanup_material = False
            with self.store.transaction() as conn:
                failed = conn.execute(text(
                    "UPDATE class_material_intakes SET status='failed',error=:error,material_id=NULL,version_id=NULL,lease_token=NULL,lease_expires=NULL,updated_at=:now "
                    "WHERE id=:id AND owner_id=:owner AND class_id=:class AND status='uploading' AND lease_token=:token AND lease_expires>:now"
                ), {'error': 'The Canvas source could not be saved because its course connection or revision changed.',
                    'now': time.time(), 'id': intake_id, 'owner': row['owner_id'], 'class': row['class_id'], 'token': token})
                cleanup_material = failed.rowcount == 1
            # Only the current lease holder can fail this intake. Its unique,
            # unattached material is then safe to remove from the course library.
            if cleanup_material and row.get('material_id'):
                try:
                    self.materials.delete(row['owner_id'], row['material_id'])
                except Exception:
                    pass

    def _attach_ready(self, row):
        from .in_class_service import InClassService
        from .in_class_models import ClassMaterialAttach
        service = InClassService(self.store)
        try:
            with self.store.engine.connect() as conn:
                item = service.row(conn, row['owner_id'], row['class_id'])
                version = self.materials.version(row['owner_id'], row['version_id'], conn)
                preferences = ResourceIntentService.get_preferences(conn, row['owner_id'], item.get('courseId')).preferences
                if version['media_type'] not in preferences.accepted_media_types:
                    raise HTTPException(422, {'code': 'unsupported_material_type', 'message': 'This file type is disabled in the course resource preferences.'})
                if row['source_kind'] == 'canvas':
                    pinned = json.loads(row['payload'] or '{}')
                    current = self._canvas_source(conn, row['owner_id'], item['courseId'],
                                                  pinned['connectionId'], pinned['entityId'])
                    if (current['sourceRevision'] != pinned.get('sourceRevision')
                            or current['contentHash'] != pinned.get('contentHash')):
                        raise HTTPException(409, {'code': 'canvas_source_changed', 'message': 'This Canvas source changed before it could be attached. Import the refreshed course source.'})
            need = self._need(conn, item, row['need_id'])
            if item.get('cancelled'):
                raise HTTPException(409, {'code': 'class_paused', 'message': 'Resume class processing before attaching this source.'})
            if not item.get('policy', {}).get('materials', False):
                raise HTTPException(409, {'code': 'materials_disabled', 'message': 'Enable related course materials before attaching this source.'})
            if need['status'] == 'provided' and need.get('versionId') == row['version_id']:
                pass
            elif need['status'] != 'open':
                raise HTTPException(409, {'code': 'need_info_closed', 'message': 'This class material request is no longer open.'})
            else:
                service.attach_material(row['owner_id'], row['class_id'], ClassMaterialAttach(
                    expectedRevision=item['revision'], needId=row['need_id'], versionId=row['version_id']))
            with self.store.transaction() as conn:
                payload = json.loads(row['payload'] or '{}')
                conn.execute(text("UPDATE class_material_intakes SET status='attached',error=NULL,payload=:payload,updated_at=:now WHERE id=:id AND owner_id=:owner AND status IN ('processing','attached')"),
                             {'payload': encoded(payload), 'now': time.time(), 'id': row['id'], 'owner': row['owner_id']})
                item = self._class(conn, row['owner_id'], row['class_id'])
                need = self._need(conn, item, row['need_id'])
                ResourceIntentService.reconcile_intake(
                    conn, row['owner_id'], row['class_id'], item.get('courseId'), need,
                    {**row, 'status': 'attached'},
                )
        except HTTPException as exc:
            if exc.status_code in {409} and isinstance(exc.detail, dict) and exc.detail.get('code') in {'class_paused', 'materials_disabled', 'revision_conflict'}:
                with self.store.transaction() as conn:
                    conn.execute(text("UPDATE class_material_intakes SET updated_at=:retry WHERE id=:id AND owner_id=:owner AND status='processing'"),
                                 {'retry': time.time() + 5, 'id': row['id'], 'owner': row['owner_id']})
                return
            cleanup_material = False
            error_code = exc.detail.get('code') if isinstance(exc.detail, dict) else None
            clear_canvas_material = row['source_kind'] == 'canvas' and error_code in {
                'canvas_source_changed', 'canvas_source_unavailable', 'canvas_connection_unavailable',
                'need_info_closed', 'need_info_not_found',
            }
            with self.store.transaction() as conn:
                failed = conn.execute(text("UPDATE class_material_intakes SET status='failed',error=:error,material_id=CASE WHEN :clear THEN NULL ELSE material_id END,version_id=CASE WHEN :clear THEN NULL ELSE version_id END,updated_at=:now WHERE id=:id AND owner_id=:owner AND status='processing'"),
                                      {'error': (exc.detail.get('message') if isinstance(exc.detail, dict) else 'The material request is no longer available.')[:500],
                                       'clear': clear_canvas_material, 'now': time.time(), 'id': row['id'], 'owner': row['owner_id']})
                cleanup_material = clear_canvas_material and failed.rowcount == 1
                if failed.rowcount == 1:
                    item = self._class(conn, row['owner_id'], row['class_id'])
                    from .class_metadata import get_need
                    need = get_need(conn, row['owner_id'], row['class_id'], row['need_id'])
                    if need:
                        ResourceIntentService.reconcile_intake(
                            conn, row['owner_id'], row['class_id'], item.get('courseId'), need,
                            {**row, 'status': 'failed', 'error': exc.detail.get('message') if isinstance(exc.detail, dict) else None},
                        )
            if cleanup_material and row.get('material_id'):
                try:
                    self.materials.delete(row['owner_id'], row['material_id'])
                except Exception:
                    pass

    def tick(self, executor):
        """Schedule bounded acquisition/indexing tasks and cheaply reconcile results."""
        did_work = 0
        for intake_id, token in self._claim_urls():
            future = executor.submit(self._fetch_url, intake_id, token)
            future.add_done_callback(lambda _future, key=intake_id: self._forget_url(key))
            did_work += 1

        uploads = self._claim_uploads()
        with self.store.engine.connect() as conn:
            processing = conn.execute(text("SELECT * FROM class_material_intakes WHERE status='processing' AND updated_at<=:now ORDER BY updated_at LIMIT 20"),
                                       {'now': time.time()}).mappings().all()
            has_ingest = conn.execute(text("SELECT 1 FROM material_jobs WHERE status IN ('queued','running') LIMIT 1")).first() is not None
            if not has_ingest:
                has_ingest=conn.execute(text("SELECT 1 FROM material_ocr_work WHERE attempt<3 AND (status='queued' OR (status='running' AND expires<:now)) LIMIT 1"),{'now':time.time()}).first() is not None
        for intake_id, token in uploads:
            future = executor.submit(self._finish_url_upload, intake_id, token)
            future.add_done_callback(lambda _future, key=intake_id: self._forget_url(key))
            did_work += 1
        # A client can lose the PUT response after MaterialService commits its
        # immutable hash/job but before the intake state advances. Recover that
        # boundary from the authoritative material version row.
        with self.store.transaction() as conn:
            recovered = conn.execute(text(
                "UPDATE class_material_intakes SET status='processing',updated_at=:now "
                "WHERE status='awaiting_upload' AND EXISTS (SELECT 1 FROM material_versions v "
                "JOIN materials m ON m.id=v.material_id WHERE v.id=class_material_intakes.version_id "
                "AND m.owner_id=class_material_intakes.owner_id AND m.deleted=false AND v.sha256 IS NOT NULL)"
            ), {'now': time.time()}).rowcount
        did_work += recovered
        for row in processing:
            try:
                version = self.materials.version(row['owner_id'], row['version_id'])
            except HTTPException:
                version = None
            if version is None:
                with self.store.transaction() as conn:
                    conn.execute(text("UPDATE class_material_intakes SET status='failed',error=:error,updated_at=:now WHERE id=:id AND status='processing'"),
                                 {'error': 'This source is no longer available. Choose another source.', 'now': time.time(), 'id': row['id']})
                did_work += 1
                continue
            if version['status'] in {'ready', 'partially_ready'}:
                self._attach_ready(dict(row)); did_work += 1
            elif version['status'] in {'failed', 'needs_attention', 'deleted'}:
                with self.store.transaction() as conn:
                    conn.execute(text("UPDATE class_material_intakes SET status='failed',error=:error,updated_at=:now WHERE id=:id AND status='processing'"),
                                 {'error': 'This source could not be read. Try another file or URL.', 'now': time.time(), 'id': row['id']})
                did_work += 1

        with self._active_lock:
            processor_busy = self._processor_running
            if has_ingest and not processor_busy:
                self._processor_running = True
        if has_ingest and not processor_busy:
            future = executor.submit(self.materials.process_one)
            future.add_done_callback(self._processor_finished)
            did_work += 1
        return did_work

    def _forget_url(self, intake_id):
        with self._active_lock:
            self._active_urls.discard(intake_id)

    def _processor_finished(self, _future):
        with self._active_lock:
            self._processor_running = False
