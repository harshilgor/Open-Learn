"""Owner-scoped resource-intent and read-only connector contracts for In-Class.

The registry describes how a resource can be selected. It deliberately has no
remote write operation: connectors can only offer local library selection or
read/import paths that the learner explicitly chooses.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import Field, field_validator, model_validator
from sqlalchemy import text

from .session_models import ApiModel


ConnectorId = Literal['library', 'upload', 'url', 'drive', 'canvas', 'blackboard', 'moodle']
ResourceIntentStatus = Literal['open', 'resolving', 'resolved', 'closed']
ResourceMediaType = Literal['application/pdf', 'text/plain', 'text/markdown']

DEFAULT_CONNECTOR_ORDER: list[str] = ['library', 'upload', 'url', 'drive', 'canvas']
DEFAULT_ENABLED_CONNECTORS: list[str] = ['library', 'upload', 'url', 'drive', 'canvas']
DEFAULT_CLASS_RESOURCE_UPLOAD_BYTES = 250 * 1024 * 1024
MAX_CLASS_RESOURCE_UPLOAD_BYTES = 500 * 1024 * 1024


class ConnectorField(ApiModel):
    name: str
    required: bool = True
    option: str
    max_length: int | None = None


class ConnectorDescriptor(ApiModel):
    id: ConnectorId
    name: str
    status: Literal['supported', 'stub']
    capabilities: list[Literal['select', 'read', 'import']]
    required_fields: list[str] = Field(default_factory=list)
    options: list[ConnectorField] = Field(default_factory=list)
    requires_connection: bool = False
    external_writes_enabled: Literal[False] = False
    detail: str


class ResourceIntent(ApiModel):
    id: str
    class_id: str
    need_id: str
    course_id: str | None = None
    window_id: str
    kind: str = 'materials'
    prompt: str
    query: str
    required_fields: list[str]
    options: dict[str, Any]
    status: ResourceIntentStatus
    selected_connector: ConnectorId | None = None
    selected_resource: dict[str, Any] | None = None
    material_version_id: str | None = None
    last_error: str | None = None
    created_at: float
    updated_at: float


class CourseResourcePreferences(ApiModel):
    connector_order: list[ConnectorId] = Field(default_factory=lambda: list(DEFAULT_CONNECTOR_ORDER))
    enabled_connectors: list[ConnectorId] = Field(default_factory=lambda: list(DEFAULT_ENABLED_CONNECTORS))
    allow_public_urls: bool = True
    accepted_media_types: list[ResourceMediaType] = Field(
        default_factory=lambda: ['application/pdf', 'text/plain', 'text/markdown']
    )
    max_upload_bytes: int = Field(default=DEFAULT_CLASS_RESOURCE_UPLOAD_BYTES, ge=1, le=MAX_CLASS_RESOURCE_UPLOAD_BYTES)
    require_explicit_selection: Literal[True] = True
    cross_course_library_search: Literal[False] = False

    @field_validator('connector_order', 'enabled_connectors')
    @classmethod
    def unique_connectors(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError('Connector IDs must be unique.')
        return value

    @model_validator(mode='after')
    def selection_order_covers_enabled(self):
        if any(connector not in self.connector_order for connector in self.enabled_connectors):
            raise ValueError('Every enabled connector must appear in connectorOrder.')
        return self


class CourseResourcePreferencesUpdate(CourseResourcePreferences):
    expected_revision: int = Field(alias='expectedRevision', ge=0)


class CourseResourcePreferencesSnapshot(ApiModel):
    course_id: str | None
    revision: int
    preferences: CourseResourcePreferences
    updated_at: float | None = None


class ConnectorRegistry:
    """The stable contract between resource intent and source adapters."""

    _descriptors = (
        ConnectorDescriptor(
            id='library', name='Open Learn library', status='supported', capabilities=['select'],
            required_fields=['versionId'], options=[ConnectorField(name='versionId', option='Ready course-eligible material version ID')],
            detail='Select a ready, owner-owned reference already in the library.',
        ),
        ConnectorDescriptor(
            id='upload', name='Upload a file', status='supported', capabilities=['import'],
            required_fields=['title', 'mediaType', 'byteCount'], options=[
                ConnectorField(name='title', option='Display title', max_length=300),
                ConnectorField(name='mediaType', option='PDF, plain text, or Markdown'),
                ConnectorField(name='byteCount', option='File size in bytes'),
            ], detail='Import a learner-selected file up to the configured course limit.',
        ),
        ConnectorDescriptor(
            id='url', name='Public URL', status='supported', capabilities=['read', 'import'],
            required_fields=['url'], options=[ConnectorField(name='url', option='Public HTTP(S) URL', max_length=2048)],
            detail='Fetch a learner-selected public URL through the bounded material reader.',
        ),
        ConnectorDescriptor(
            id='drive', name='Google Drive', status='supported', capabilities=['read', 'import'],
            required_fields=['connectionId', 'fileId'], options=[
                ConnectorField(name='connectionId', option='Connected Google account ID', max_length=160),
                ConnectorField(name='fileId', option='Selected Drive file ID', max_length=300),
            ], requires_connection=True, detail='Import only the Drive file selected by the learner.',
        ),
        ConnectorDescriptor(
            id='canvas', name='Canvas', status='supported', capabilities=['read', 'import'],
            required_fields=['connectionId', 'entityId'], options=[
                ConnectorField(name='connectionId', option='Paired Canvas connection ID', max_length=160),
                ConnectorField(name='entityId', option='Previously synced course coverage source ID', max_length=160),
            ], requires_connection=True,
            detail='Import previously synced course coverage text; Canvas files and assignments are not currently imported.',
        ),
        ConnectorDescriptor(
            id='blackboard', name='Blackboard', status='stub', capabilities=['read'],
            required_fields=['courseExternalId', 'resourceId'], options=[
                ConnectorField(name='courseExternalId', option='Blackboard course ID', max_length=200),
                ConnectorField(name='resourceId', option='Explicitly selected Blackboard resource ID', max_length=300),
            ], requires_connection=True, detail='Adapter contract only; Blackboard connection and reads are not implemented.',
        ),
        ConnectorDescriptor(
            id='moodle', name='Moodle', status='stub', capabilities=['read'],
            required_fields=['courseExternalId', 'resourceId'], options=[
                ConnectorField(name='courseExternalId', option='Moodle course ID', max_length=200),
                ConnectorField(name='resourceId', option='Explicitly selected Moodle resource ID', max_length=300),
            ], requires_connection=True, detail='Adapter contract only; Moodle connection and reads are not implemented.',
        ),
    )

    @classmethod
    def list(cls) -> list[dict[str, Any]]:
        return [item.model_dump(mode='json', by_alias=True) for item in cls._descriptors]

    @classmethod
    def get(cls, connector_id: str) -> ConnectorDescriptor:
        found = next((item for item in cls._descriptors if item.id == connector_id), None)
        if found is None:
            raise HTTPException(422, {'code': 'unsupported_connector', 'message': 'Choose a supported resource connector.'})
        return found

    @classmethod
    def require_selectable(cls, connector_id: str) -> ConnectorDescriptor:
        descriptor = cls.get(connector_id)
        if descriptor.status != 'supported' or connector_id in {'blackboard', 'moodle'}:
            raise HTTPException(409, {'code': 'connector_not_configured', 'message': f'{descriptor.name} is not connected yet.'})
        return descriptor

    @staticmethod
    def source_kind(source_kind: str) -> ConnectorId:
        if source_kind not in {'upload', 'url', 'drive', 'canvas'}:
            raise HTTPException(422, {'code': 'unsupported_connector', 'message': 'Choose an available material source.'})
        return source_kind  # type: ignore[return-value]


class ResourceIntentService:
    """Persist NeedInfo intent, user selections, and course-level source defaults."""

    def __init__(self, store):
        self.store = store

    @staticmethod
    def _intent_id(owner: str, class_id: str, need_id: str) -> str:
        digest = hashlib.sha256(f'{owner}\0{class_id}\0{need_id}'.encode()).hexdigest()
        return 'resource_intent_' + digest

    @staticmethod
    def _preferences_payload(value: CourseResourcePreferences) -> dict[str, Any]:
        return value.model_dump(mode='json', by_alias=True)

    @staticmethod
    def _validate_course(conn, owner: str, course_id: str, require_active: bool = False) -> None:
        row = conn.execute(text(
            'SELECT archived_at FROM courses WHERE id=:course AND owner_id=:owner'
        ), {'course': course_id, 'owner': owner}).mappings().first()
        if not row or (require_active and row['archived_at'] is not None):
            raise HTTPException(404, {'code': 'course_not_found', 'message': 'This course is unavailable.'})

    @classmethod
    def _preference_row(cls, conn, owner: str, course_id: str):
        cls._validate_course(conn, owner, course_id)
        return conn.execute(text(
            'SELECT revision,payload,updated_at FROM course_resource_preferences '
            'WHERE owner_id=:owner AND course_id=:course'
        ), {'owner': owner, 'course': course_id}).mappings().first()

    @classmethod
    def get_preferences(cls, conn, owner: str, course_id: str | None) -> CourseResourcePreferencesSnapshot:
        if not course_id:
            return CourseResourcePreferencesSnapshot(courseId=None, revision=0, preferences=CourseResourcePreferences())
        row = cls._preference_row(conn, owner, course_id)
        if not row:
            return CourseResourcePreferencesSnapshot(courseId=course_id, revision=0, preferences=CourseResourcePreferences())
        prefs = CourseResourcePreferences.model_validate_json(row['payload'])
        return CourseResourcePreferencesSnapshot(courseId=course_id, revision=row['revision'], preferences=prefs, updatedAt=row['updated_at'])

    @classmethod
    def put_preferences(cls, conn, owner: str, course_id: str, request: CourseResourcePreferencesUpdate) -> CourseResourcePreferencesSnapshot:
        cls._validate_course(conn, owner, course_id, require_active=True)
        current = cls.get_preferences(conn, owner, course_id)
        if current.revision != request.expected_revision:
            raise HTTPException(409, {'code': 'resource_preferences_revision_conflict', 'message': 'Refresh the course resource preferences before saving.'})
        value = CourseResourcePreferences.model_validate(request.model_dump(exclude={'expected_revision'}))
        now = time.time()
        payload = json.dumps(cls._preferences_payload(value), separators=(',', ':'), ensure_ascii=False)
        result = conn.execute(text(
            'INSERT INTO course_resource_preferences(id,owner_id,course_id,revision,payload,created_at,updated_at) '
            'VALUES(:id,:owner,:course,1,:payload,:now,:now) '
            'ON CONFLICT(owner_id,course_id) DO UPDATE SET '
            'revision=course_resource_preferences.revision+1,payload=excluded.payload,updated_at=excluded.updated_at '
            'WHERE course_resource_preferences.revision=:expected'
        ), {'id': 'course_resource_prefs_' + hashlib.sha256(f'{owner}\0{course_id}'.encode()).hexdigest(),
            'owner': owner, 'course': course_id, 'payload': payload, 'now': now, 'expected': request.expected_revision})
        if result.rowcount != 1:
            raise HTTPException(409, {'code': 'resource_preferences_revision_conflict', 'message': 'Refresh the course resource preferences before saving.'})
        return cls.get_preferences(conn, owner, course_id)

    @staticmethod
    def _intent_options(course_id: str | None, need: dict[str, Any], preferences: CourseResourcePreferences) -> dict[str, Any]:
        return {
            'acceptedMediaTypes': list(preferences.accepted_media_types),
            'maxUploadBytes': preferences.max_upload_bytes,
            'allowPublicUrls': preferences.allow_public_urls,
            'enabledConnectors': list(preferences.enabled_connectors),
            'connectorOrder': list(preferences.connector_order),
            'requiresExplicitSelection': True,
            'courseScoped': course_id is not None,
            'externalWritesEnabled': False,
            'selectionOptions': {
                'urlMaxBytes': 2 * 1024 * 1024,
                'driveMaxBytes': 5_000_000,
                'canvasSourceKind': 'synced_course_coverage',
            },
        }

    @classmethod
    def validate_connector_enabled(cls, conn, owner: str, course_id: str | None, connector_id: str) -> CourseResourcePreferences:
        connector = ConnectorRegistry.require_selectable(connector_id)
        preferences = cls.get_preferences(conn, owner, course_id).preferences if course_id else CourseResourcePreferences()
        if connector.id not in preferences.enabled_connectors:
            raise HTTPException(409, {'code': 'connector_disabled_for_course', 'message': 'This source is disabled in the course resource preferences.'})
        return preferences

    @classmethod
    def ensure_need(cls, conn, owner: str, class_id: str, course_id: str | None, need: dict[str, Any]) -> ResourceIntent:
        need_id = str(need['id'])
        identifier = cls._intent_id(owner, class_id, need_id)
        now = time.time()
        prefs = cls.get_preferences(conn, owner, course_id).preferences if course_id else CourseResourcePreferences()
        options = cls._intent_options(course_id, need, prefs)
        required_fields = ['source']
        if course_id:
            required_fields.append('courseId')
        status = 'resolved' if need.get('status') == 'provided' else ('closed' if need.get('status') not in {'open', 'provided'} else 'open')
        selected_connector = 'library' if need.get('status') == 'provided' and need.get('versionId') else None
        selected_resource = ({'kind': 'library', 'versionId': str(need['versionId']), 'selectionMode': 'owner_explicit'}
                             if selected_connector else None)
        material_version_id = str(need['versionId']) if need.get('versionId') else None
        query = str(need.get('query') or '')[:1000]
        prompt = str(need.get('prompt') or '')[:1000]
        window_id = str(need.get('windowId') or '')[:160]
        conn.execute(text(
            'INSERT INTO class_resource_intents('
            'id,owner_id,class_id,need_id,course_id,window_id,kind,prompt,query,required_fields,options,'
            'status,selected_connector,selected_resource,material_version_id,created_at,updated_at) '
            'VALUES(:id,:owner,:class,:need,:course,:window,:kind,:prompt,:query,:required,:options,'
            ':status,:connector,:resource,:version,:now,:now) '
            'ON CONFLICT(owner_id,class_id,need_id) DO UPDATE SET '
            'course_id=excluded.course_id,window_id=excluded.window_id,kind=excluded.kind,prompt=excluded.prompt,'
            'query=excluded.query,required_fields=excluded.required_fields,options=excluded.options,'
            'status=CASE WHEN excluded.status IN (\'resolved\',\'closed\') THEN excluded.status '
            'WHEN class_resource_intents.status IN (\'resolved\',\'closed\') THEN \'open\' ELSE class_resource_intents.status END,'
            'selected_connector=CASE WHEN excluded.status=\'resolved\' AND class_resource_intents.selected_connector IS NOT NULL '
            'AND class_resource_intents.material_version_id=excluded.material_version_id THEN class_resource_intents.selected_connector '
            'WHEN excluded.status=\'resolved\' THEN excluded.selected_connector '
            'WHEN class_resource_intents.status IN (\'resolved\',\'closed\') THEN NULL ELSE class_resource_intents.selected_connector END,'
            'selected_resource=CASE WHEN excluded.status=\'resolved\' AND class_resource_intents.selected_resource IS NOT NULL '
            'AND class_resource_intents.material_version_id=excluded.material_version_id THEN class_resource_intents.selected_resource '
            'WHEN excluded.status=\'resolved\' THEN excluded.selected_resource '
            'WHEN class_resource_intents.status IN (\'resolved\',\'closed\') THEN NULL ELSE class_resource_intents.selected_resource END,'
            'material_version_id=CASE WHEN excluded.status=\'resolved\' THEN excluded.material_version_id '
            'WHEN class_resource_intents.status IN (\'resolved\',\'closed\') THEN NULL ELSE class_resource_intents.material_version_id END,'
            'updated_at=excluded.updated_at'
        ), {'id': identifier, 'owner': owner, 'class': class_id, 'need': need_id, 'course': course_id,
            'window': window_id, 'kind': str(need.get('kind') or 'materials'), 'prompt': prompt, 'query': query,
            'required': json.dumps(required_fields, separators=(',', ':')),
            'options': json.dumps(options, separators=(',', ':'), ensure_ascii=False), 'status': status,
            'connector': selected_connector,
            'resource': json.dumps(selected_resource, separators=(',', ':')) if selected_resource else None,
            'version': material_version_id, 'now': now})
        row = conn.execute(text('SELECT * FROM class_resource_intents WHERE owner_id=:owner AND class_id=:class AND need_id=:need'),
                           {'owner': owner, 'class': class_id, 'need': need_id}).mappings().one()
        return cls._intent(row)

    @staticmethod
    def _intent(row) -> ResourceIntent:
        return ResourceIntent(
            id=row['id'], classId=row['class_id'], needId=row['need_id'], courseId=row['course_id'],
            windowId=row['window_id'], kind=row['kind'], prompt=row['prompt'], query=row['query'],
            requiredFields=json.loads(row['required_fields'] or '[]'), options=json.loads(row['options'] or '{}'),
            status=row['status'], selectedConnector=row['selected_connector'],
            selectedResource=json.loads(row['selected_resource']) if row['selected_resource'] else None,
            materialVersionId=row['material_version_id'], lastError=row['last_error'],
            createdAt=row['created_at'], updatedAt=row['updated_at'],
        )

    @classmethod
    def record_selection(cls, conn, owner: str, class_id: str, course_id: str | None, need: dict[str, Any],
                         connector_id: str, command_id: str, request_hash: str,
                         selected_resource: dict[str, Any] | None = None) -> None:
        connector = ConnectorRegistry.require_selectable(connector_id)
        prefs = cls.validate_connector_enabled(conn, owner, course_id, connector_id)
        resource = dict(selected_resource or {})
        resource['selectionMode'] = 'owner_explicit'
        if connector.id == 'url' and not prefs.allow_public_urls:
            raise HTTPException(409, {'code': 'public_urls_disabled', 'message': 'Public URL imports are disabled in the course resource preferences.'})
        if connector.id == 'upload':
            if resource.get('mediaType') not in prefs.accepted_media_types:
                raise HTTPException(422, {'code': 'unsupported_material_type', 'message': 'This file type is disabled in the course resource preferences.'})
            if int(resource.get('byteCount') or 0) > prefs.max_upload_bytes:
                raise HTTPException(413, {'code': 'material_too_large', 'message': 'This file exceeds the course resource upload limit.'})
        intent = cls.ensure_need(conn, owner, class_id, course_id, need)
        if intent.status == 'resolved':
            raise HTTPException(409, {'code': 'need_info_closed', 'message': 'This class resource request has already been resolved.'})
        resource['requestHash'] = request_hash
        now = time.time()
        changed = conn.execute(text(
            "UPDATE class_resource_intents SET status='resolving',selected_connector=:connector,"
            'selected_resource=:resource,selected_command_id=:command,request_hash=:hash,material_version_id=NULL,'
            'last_error=NULL,updated_at=:now WHERE id=:id AND owner_id=:owner AND status IN (\'open\',\'resolving\') '
            'AND (selected_command_id IS NULL OR selected_command_id=:command OR status=\'open\')'
        ), {'connector': connector.id, 'resource': json.dumps(resource, separators=(',', ':'), ensure_ascii=False),
            'command': command_id, 'hash': request_hash, 'now': now, 'id': intent.id, 'owner': owner}).rowcount
        if changed != 1:
            raise HTTPException(409, {'code': 'resource_intent_conflict', 'message': 'Refresh this class resource request and try again.'})

    @classmethod
    def record_library_attachment(cls, conn, owner: str, class_id: str, course_id: str | None,
                                  need: dict[str, Any]) -> None:
        """Mirror the existing idempotent library attach after it succeeds."""
        version_id = str(need.get('versionId') or '')
        if need.get('status') != 'provided' or not version_id:
            return
        intent = cls.ensure_need(conn, owner, class_id, course_id, need)
        request_hash = hashlib.sha256(f'library\0{version_id}'.encode()).hexdigest()
        command_id = 'library_' + hashlib.sha256(
            f'{owner}\0{class_id}\0{need["id"]}\0{version_id}'.encode()
        ).hexdigest()
        now = time.time()
        conn.execute(text(
            "UPDATE class_resource_intents SET status='resolved',selected_connector='library',"
            'selected_resource=:resource,selected_command_id=:command,request_hash=:hash,'
            'material_version_id=:version,last_error=NULL,updated_at=:now WHERE id=:id AND owner_id=:owner'
        ), {'resource': json.dumps({'kind': 'library', 'versionId': version_id,
                                    'selectionMode': 'owner_explicit', 'requestHash': request_hash},
                                   separators=(',', ':')),
            'command': command_id, 'hash': request_hash, 'version': version_id,
            'now': now, 'id': intent.id, 'owner': owner})

    @classmethod
    def reconcile_intake(cls, conn, owner: str, class_id: str, course_id: str | None,
                         need: dict[str, Any], intake: dict[str, Any] | None) -> ResourceIntent:
        intent = cls.ensure_need(conn, owner, class_id, course_id, need)
        if need.get('status') == 'provided' and need.get('versionId'):
            connector_id = intent.selected_connector or 'library'
            resource = intent.selected_resource or {'kind': 'library', 'versionId': str(need['versionId'])}
            status = 'resolved'
            version_id = str(need['versionId'])
            error = None
        elif intake:
            connector_id = ConnectorRegistry.source_kind(intake.get('source_kind', ''))
            payload = json.loads(intake.get('payload') or '{}')
            existing_resource = intent.selected_resource or {}
            resource = existing_resource if existing_resource.get('requestHash') == payload.get('requestHash') else {
                'kind': connector_id,
                'connectionId': payload.get('connectionId'),
                'fileId': payload.get('fileId'),
                'entityId': payload.get('entityId'),
                'requestHash': payload.get('requestHash'),
            }
            intake_status = str(intake.get('status') or '')
            if intake_status == 'attached':
                status, version_id, error = 'resolved', intake.get('version_id'), None
            elif intake_status == 'failed':
                status, version_id, error = 'open', None, str(intake.get('error') or 'The source could not be added.')[:500]
            elif intake_status in {'queued', 'awaiting_upload', 'fetching', 'uploading', 'processing'}:
                status, version_id, error = 'resolving', None, None
            else:
                status, version_id, error = intent.status, intent.material_version_id, intent.last_error
        else:
            return intent
        conn.execute(text(
            'UPDATE class_resource_intents SET status=:status,selected_connector=:connector,selected_resource=:resource,'
            'material_version_id=:version,last_error=:error,updated_at=:now '
            'WHERE id=:id AND owner_id=:owner'
        ), {'status': status, 'connector': connector_id,
            'resource': json.dumps(resource, separators=(',', ':'), ensure_ascii=False) if resource else None,
            'version': version_id, 'error': error, 'now': time.time(), 'id': intent.id, 'owner': owner})
        row = conn.execute(text('SELECT * FROM class_resource_intents WHERE id=:id AND owner_id=:owner'),
                           {'id': intent.id, 'owner': owner}).mappings().one()
        return cls._intent(row)

    def list_for_class(self, owner: str, class_id: str, after: str | None = None) -> dict[str, Any]:
        from .in_class_service import InClassService
        service = InClassService(self.store)
        with self.store.transaction() as conn:
            item = service.row(conn, owner, class_id)
            preferences = self.get_preferences(conn, owner, item.get('courseId'))
            items = []
            from .class_metadata import list_needs
            page=list_needs(conn,owner,class_id,after=after)
            for need in page['items']:
                intent = self.ensure_need(conn, owner, class_id, item.get('courseId'), need)
                intake = conn.execute(text(
                    'SELECT * FROM class_material_intakes WHERE owner_id=:owner AND class_id=:class AND need_id=:need '
                    'ORDER BY created_at DESC,id DESC LIMIT 1'
                ), {'owner': owner, 'class': class_id, 'need': need['id']}).mappings().first()
                if intake:
                    intent = self.reconcile_intake(conn, owner, class_id, item.get('courseId'), need, dict(intake))
                items.append(intent.model_dump(mode='json', by_alias=True))
            return {
                'items': items,
                'hasMore':page['hasMore'], 'nextCursor':page['nextCursor'],
                'courseId': item.get('courseId'),
                'preferences': preferences.model_dump(mode='json', by_alias=True),
                'connectors': ConnectorRegistry.list(),
            }
