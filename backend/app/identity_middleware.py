"""ASGI identity context survives streaming; no client header establishes ownership."""
from urllib.parse import unquote
import re
from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from .identity import authenticate, principal_context, fail


class IdentityMiddleware:
    def __init__(self, app, store_provider):
        self.app, self.store_provider = app, store_provider

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('method') == 'OPTIONS' or not scope.get('path', '').startswith('/v1/'):
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope.get('headers', [])}
        token = None
        from .usage.context import current_store
        store_token = current_store.set(self.store_provider())
        try:
            principal = await run_in_threadpool(authenticate, self.store_provider(), headers.get('authorization'), headers.get('x-dev-learner-id'))
            path = scope['path']
            if not path.startswith('/v1/account'):
                from sqlalchemy import text
                def importing():
                    with self.store_provider().engine.connect() as conn:
                        return conn.execute(text("SELECT 1 FROM identity_imports WHERE owner_id=:owner AND status='copying'"), {'owner': principal.owner_id}).first() is not None
                if await run_in_threadpool(importing):
                    fail('profile_import_pending', 'Finish or retry the profile import in Account & devices before opening imported history.', 423)
            canvas_sync=scope.get('method')=='POST' and re.fullmatch(r'/v1/canvas/connections/[A-Za-z0-9_.:-]+/sync',path)
            canvas_disconnect=scope.get('method')=='DELETE' and re.fullmatch(r'/v1/canvas/connections/[A-Za-z0-9_.:-]+',path)
            if principal.kind == 'canvas' and path != '/v1/account' and not (canvas_sync or canvas_disconnect):
                fail('device_scope_denied', 'Canvas grants cannot access learning, settings, or account data.', 403)
            if principal.kind == 'browser' and not (path in {'/v1/browser-devices/commands','/v1/browser-devices/disconnect'} or
                    re.fullmatch(r'/v1/browser-devices/commands/[A-Za-z0-9_.:-]+/result', path) or
                    re.fullmatch(r'/v1/browser-devices/handoffs/[A-Za-z0-9_.:-]+/ack', path)):
                fail('device_scope_denied', 'Browser grants can only receive and acknowledge their scoped commands.', 403)
            if path.startswith('/v1/learners/'):
                owner = unquote(path.split('/')[3])
                if owner != principal.owner_id:
                    fail('owner_scope_mismatch', 'This resource belongs to another account.', 403)
            if principal.kind != 'local' and path.startswith(('/v1/provider-keys', '/v1/provider-settings', '/v1/local-backup')):
                fail('local_only', 'This control is available only to the local installation.', 403)
            # Old header arguments remain API-compatible but receive trusted identity.
            scope['headers'] = [(k, v) for k, v in scope.get('headers', []) if k.lower() != b'x-dev-learner-id'] + [(b'x-dev-learner-id', principal.owner_id.encode())]
            token = principal_context.set(principal)
            await self.app(scope, receive, send)
        except HTTPException as exc:
            await JSONResponse(status_code=exc.status_code, content={'detail': exc.detail})(scope, receive, send)
        finally:
            current_store.reset(store_token)
            if token is not None:
                principal_context.reset(token)
