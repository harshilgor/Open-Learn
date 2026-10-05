"""Spool streamed material request bodies without retaining the file in RAM."""
from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
import tempfile

from fastapi import HTTPException, Request


@asynccontextmanager
async def request_upload_file(request: Request, max_bytes: int):
    descriptor, name = tempfile.mkstemp(prefix="openlearn-upload-")
    path = Path(name)
    size = 0
    try:
        with os.fdopen(descriptor, "wb") as output:
            async for part in request.stream():
                size += len(part)
                if size > max_bytes:
                    raise HTTPException(413, {"code": "upload_too_large", "message": "Upload exceeds the declared size."})
                output.write(part)
        yield path, size
    finally:
        path.unlink(missing_ok=True)
