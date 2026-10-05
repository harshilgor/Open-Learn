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
    def put_file(self, key: str, path: Path, *, byte_count: int, sha256: str) -> str: ...
    def read(self, key: str) -> bytes: ...
    def stream_to(self, key: str, output) -> int: ...
    def download_to_file(self, key: str, destination: Path) -> int: ...
    def iter_bytes(self, key: str, chunk_size: int = 65536): ...
    def iter_range(self, key: str, start: int, end: int, chunk_size: int = 65536): ...
    def delete(self, key: str) -> None: ...


def _file_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


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

    def put_file(self, key, path, *, byte_count, sha256):
        source_path = Path(path)
        actual_size, actual_digest = _file_digest(source_path)
        if actual_size != byte_count or actual_digest != sha256:
            raise ValueError("Upload changed before it reached object storage")
        destination = self.path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=destination.parent, prefix=".upload-", delete=False) as output:
            temporary = Path(output.name)
            with source_path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        try:
            try:
                os.link(temporary, destination)
            except FileExistsError:
                existing_size, existing_digest = _file_digest(destination)
                if existing_size != byte_count or existing_digest != sha256:
                    raise ValueError("An immutable object already occupies this key")
        finally:
            temporary.unlink(missing_ok=True)
        return sha256

    def read(self, key):
        return self.path(key).read_bytes()

    def stream_to(self, key, output):
        size = 0
        with self.path(key).open('rb') as source:
            while chunk := source.read(1024 * 1024):
                output.write(chunk)
                size += len(chunk)
        return size

    def download_to_file(self, key, destination):
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('wb') as output:
            return self.stream_to(key, output)

    def iter_bytes(self, key, chunk_size=65536):
        with self.path(key).open('rb') as source:
            while chunk := source.read(chunk_size):
                yield chunk

    def iter_range(self, key, start, end, chunk_size=65536):
        if start < 0 or end < start:
            raise ValueError("Invalid object byte range")
        remaining = end - start + 1
        with self.path(key).open('rb') as source:
            source.seek(start)
            while remaining:
                chunk = source.read(min(chunk_size, remaining))
                if not chunk:
                    raise OSError("Object ended before the requested byte range")
                remaining -= len(chunk)
                yield chunk

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

    def put_file(self, key, path, *, byte_count, sha256):
        source_path = Path(path)
        actual_size, actual_digest = _file_digest(source_path)
        if actual_size != byte_count or actual_digest != sha256:
            raise ValueError("Upload changed before it reached object storage")
        try:
            with source_path.open("rb") as source:
                self.client.put_object(Bucket=self.bucket, Key=self.key(key), Body=source,
                                       ContentLength=byte_count, IfNoneMatch="*",
                                       Metadata={"sha256": sha256})
        except Exception as exc:
            code = getattr(exc, "response", {}).get("Error", {}).get("Code")
            if code not in {"PreconditionFailed", "412"}:
                raise
            try:
                existing = self.client.head_object(Bucket=self.bucket, Key=self.key(key))
                metadata = existing.get("Metadata", {})
                if int(existing.get("ContentLength", -1)) != byte_count or metadata.get("sha256") != sha256:
                    raise ValueError("An immutable object already occupies this key") from exc
            except AttributeError:
                if hashlib.sha256(self.read(key)).hexdigest() != sha256:
                    raise ValueError("An immutable object already occupies this key") from exc
        return sha256

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

    def stream_to(self, key, output):
        response = self.client.get_object(Bucket=self.bucket, Key=self.key(key))
        body = response['Body']
        digest = hashlib.sha256()
        size = 0
        try:
            while chunk := body.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        finally:
            body.close()
        expected = response.get('Metadata', {}).get('sha256')
        if expected and digest.hexdigest() != expected:
            raise OSError('Object integrity check failed')
        if response.get('ContentLength') is not None and size != response['ContentLength']:
            raise OSError('Object length check failed')
        return size

    def download_to_file(self, key, destination):
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('wb') as output:
            return self.stream_to(key, output)

    def iter_bytes(self, key, chunk_size=65536):
        response = self.client.get_object(Bucket=self.bucket, Key=self.key(key))
        body = response['Body']
        digest = hashlib.sha256()
        size = 0
        try:
            while chunk := body.read(chunk_size):
                digest.update(chunk)
                size += len(chunk)
                yield chunk
        finally:
            body.close()
        expected = response.get('Metadata', {}).get('sha256')
        if expected and digest.hexdigest() != expected:
            raise OSError('Object integrity check failed')
        if response.get('ContentLength') is not None and size != response['ContentLength']:
            raise OSError('Object length check failed')

    def iter_range(self, key, start, end, chunk_size=65536):
        if start < 0 or end < start:
            raise ValueError("Invalid object byte range")
        expected_size = end - start + 1
        response = self.client.get_object(Bucket=self.bucket, Key=self.key(key), Range=f"bytes={start}-{end}")
        body = response['Body']
        size = 0
        try:
            while chunk := body.read(min(chunk_size, expected_size - size)):
                size += len(chunk)
                yield chunk
        finally:
            body.close()
        if size != expected_size or (response.get('ContentLength') is not None and size != response['ContentLength']):
            raise OSError('Object range length check failed')

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
