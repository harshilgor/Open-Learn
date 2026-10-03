"""Immutable binary objects; callers authorize owners before accessing keys."""
from __future__ import annotations
import hashlib
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol


def valid_key(key: str) -> str:
    if not key or len(key) > 900 or any(not re.fullmatch(r"[A-Za-z0-9_:.\-]+", part) or part in {".", ".."} for part in key.split("/")):
        raise ValueError("Invalid object key")
    return key


class ObjectStore(Protocol):
    def put(self, key: str, content: bytes) -> str: ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class LocalObjectStore:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def path(self, key):
        path = (self.root / valid_key(key)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Object key escapes storage")
        return path

    def put(self, key, content):
        destination = self.path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=destination.parent, prefix=".upload-", delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        try:
            try:
                # Atomic create-without-overwrite; readers never see a partial file.
                os.link(temporary, destination)
            except FileExistsError:
                if destination.read_bytes() != content:
                    raise ValueError("An immutable object already occupies this key")
        finally:
            temporary.unlink(missing_ok=True)
        return hashlib.sha256(content).hexdigest()

    def read(self, key):
        return self.path(key).read_bytes()

    def delete(self, key):
        self.path(key).unlink(missing_ok=True)


class S3ObjectStore:
    def __init__(self, client, bucket, prefix=""):
        if not bucket:
            raise ValueError("OPENLEARN_OBJECT_BUCKET is required")
        self.client, self.bucket = client, bucket
        self.prefix = prefix.strip("/")
        if self.prefix:
            valid_key(self.prefix)

    def key(self, key):
        return "/".join(part for part in (self.prefix, valid_key(key)) if part)

    def put(self, key, content):
        digest = hashlib.sha256(content).hexdigest()
        try:
            self.client.put_object(Bucket=self.bucket, Key=self.key(key), Body=content,
                                   IfNoneMatch="*", Metadata={"sha256": digest})
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if code not in {"PreconditionFailed", "412"}:
                raise
            if self.read(key) != content:
                raise ValueError("An immutable object already occupies this key") from exc
        return digest

    def read(self, key):
        response = self.client.get_object(Bucket=self.bucket, Key=self.key(key))
        body = response["Body"]
        try:
            content = body.read()
        finally:
            body.close()
        expected = response.get("Metadata", {}).get("sha256")
        if expected and hashlib.sha256(content).hexdigest() != expected:
            raise OSError("Object integrity check failed")
        return content

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=self.key(key))


def configured_objects(local_root: Path) -> ObjectStore:
    backend = os.getenv("OPENLEARN_OBJECT_BACKEND", "local")
    if backend == "local":
        return LocalObjectStore(local_root)
    if backend != "s3":
        raise ValueError("Unsupported OPENLEARN_OBJECT_BACKEND")
    import boto3
    return S3ObjectStore(boto3.client("s3", endpoint_url=os.getenv("OPENLEARN_OBJECT_ENDPOINT") or None),
                         os.getenv("OPENLEARN_OBJECT_BUCKET"), os.getenv("OPENLEARN_OBJECT_PREFIX", "openlearn"))
