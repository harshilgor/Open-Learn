"""Immutable binary boundary. Callers must authorize entity ownership first.

Keys are owner-relative and opaque; no user-controlled filesystem paths or
provider URLs are accepted. Adapters never issue public or signed URLs.
"""
from __future__ import annotations
import base64
import hashlib
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol


class ObjectConflict(ValueError):
    pass


def object_key(owner: str, key: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", owner) or owner in {".", ".."}:
        raise ValueError("Invalid object owner")
    pieces = key.split("/")
    if not 1 <= len(pieces) <= 5 or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", part) for part in pieces):
        raise ValueError("Invalid object key")
    return owner + "/" + key


def verify(content: bytes, checksum: str) -> bytes:
    if hashlib.sha256(content).hexdigest() != checksum:
        raise ObjectConflict("Object integrity check failed")
    return content


class ImmutableObjects(Protocol):
    def put(self, owner: str, key: str, content: bytes) -> str: ...
    def read(self, owner: str, key: str, checksum: str | None = None) -> bytes: ...
    def delete(self, owner: str, key: str) -> None: ...


class LocalImmutableObjects:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def path(self, owner: str, key: str) -> Path:
        path = (self.root / object_key(owner, key)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Object path escapes storage")
        return path

    def put(self, owner: str, key: str, content: bytes) -> str:
        path = self.path(owner, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        checksum = hashlib.sha256(content).hexdigest()
        temporary = None
        try:
            with NamedTemporaryFile("wb", delete=False, dir=path.parent, prefix=".object-") as output:
                temporary = Path(output.name)
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            try:
                # Windows does not reliably permit hard links in restricted
                # app/workspace directories. Its rename primitive is atomic
                # and fails when the destination already exists; POSIX keeps
                # using link, which has the same no-overwrite property.
                if os.name == "nt":
                    os.rename(temporary, path)
                else:
                    os.link(temporary, path)
            except FileExistsError:
                verify(path.read_bytes(), checksum)
            if os.name != "nt":
                descriptor = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        return checksum

    def read(self, owner: str, key: str, checksum: str | None = None) -> bytes:
        content = self.path(owner, key).read_bytes()
        return verify(content, checksum) if checksum else content

    def delete(self, owner: str, key: str) -> None:
        self.path(owner, key).unlink(missing_ok=True)


class S3ImmutableObjects:
    """Injected maintained SDK client; credentials belong to runtime IAM.

    A 409 remains retryable by the durable caller. A 412 checks existing bytes
    rather than mistaking a key collision for a successful write.
    """
    def __init__(self, client, bucket: str, prefix="openlearn"):
        if not bucket or not re.fullmatch(r"[A-Za-z0-9_-]+", prefix):
            raise ValueError("Invalid S3 configuration")
        self.client, self.bucket, self.prefix = client, bucket, prefix

    def _key(self, owner, key):
        return self.prefix + "/" + object_key(owner, key)

    def put(self, owner: str, key: str, content: bytes) -> str:
        checksum = hashlib.sha256(content).hexdigest()
        remote_key = self._key(owner, key)
        try:
            self.client.put_object(Bucket=self.bucket, Key=remote_key, Body=content, IfNoneMatch="*",
                                   ChecksumSHA256=base64.b64encode(bytes.fromhex(checksum)).decode("ascii"), Metadata={"sha256": checksum})
        except Exception as exc:
            error = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if error not in {"PreconditionFailed", "412"}:
                raise
            self.read(owner, key, checksum)
        return checksum

    def read(self, owner: str, key: str, checksum: str | None = None) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=self._key(owner, key))
        body = response["Body"]
        try:
            content = body.read()
        finally:
            body.close()
        expected = checksum or response.get("Metadata", {}).get("sha256")
        if not expected:
            raise ObjectConflict("Stored checksum is missing")
        return verify(content, expected)

    def delete(self, owner: str, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(owner, key))
