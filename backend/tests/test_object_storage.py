import io
from concurrent.futures import ThreadPoolExecutor
import pytest
from backend.app.object_storage import LocalImmutableObjects, S3ImmutableObjects, ObjectConflict


def test_local_concurrent_immutable_write_and_owner_isolation(tmp_path):
    objects = LocalImmutableObjects(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        hashes = list(pool.map(lambda _: objects.put("alice", "recording/chunk", b"original"), range(4)))
    assert len(set(hashes)) == 1
    with pytest.raises(ObjectConflict):
        objects.put("alice", "recording/chunk", b"replacement")
    assert objects.read("alice", "recording/chunk", hashes[0]) == b"original"
    with pytest.raises(FileNotFoundError):
        objects.read("bob", "recording/chunk")
    objects.delete("bob", "recording/chunk")
    assert objects.read("alice", "recording/chunk") == b"original"
    assert not list(tmp_path.rglob(".object-*"))


def test_local_corruption_and_path_escape(tmp_path):
    objects = LocalImmutableObjects(tmp_path)
    digest = objects.put("alice", "recording/chunk", b"original")
    objects.path("alice", "recording/chunk").write_bytes(b"corrupted")
    with pytest.raises(ObjectConflict):
        objects.read("alice", "recording/chunk", digest)
    for owner, key in [("..", "chunk"), ("alice", "../chunk"), ("alice", "/chunk"), ("alice", "recording/../../chunk")]:
        with pytest.raises(ValueError):
            objects.put(owner, key, b"bad")
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    try:
        (tmp_path / "symlink").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Creating symlinks requires the Windows Developer Mode privilege.")
        raise
    with pytest.raises(ValueError):
        objects.put("symlink", "chunk", b"bad")


class PreconditionFailed(Exception):
    response = {"Error": {"Code": "PreconditionFailed"}}


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.last_put = None
    def put_object(self, **kwargs):
        self.last_put = kwargs
        assert kwargs["IfNoneMatch"] == "*"
        key = (kwargs["Bucket"], kwargs["Key"])
        if key in self.objects:
            raise PreconditionFailed()
        self.objects[key] = {"content": kwargs["Body"], "metadata": kwargs["Metadata"]}
    def get_object(self, **kwargs):
        item = self.objects[(kwargs["Bucket"], kwargs["Key"])]
        return {"Body": io.BytesIO(item["content"]), "Metadata": item["metadata"]}
    def delete_object(self, **kwargs):
        self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)


def test_s3_lost_ack_idempotency_collision_and_corruption():
    client = FakeS3()
    objects = S3ImmutableObjects(client, "private-test")
    digest = objects.put("alice", "recording/chunk", b"original")
    assert objects.put("alice", "recording/chunk", b"original") == digest
    with pytest.raises(ObjectConflict):
        objects.put("alice", "recording/chunk", b"replacement")
    objects.delete("bob", "recording/chunk")
    assert objects.read("alice", "recording/chunk", digest) == b"original"
    client.objects[("private-test", "openlearn/alice/recording/chunk")]["content"] = b"corrupted"
    with pytest.raises(ObjectConflict):
        objects.read("alice", "recording/chunk")


def test_s3_provider_error_is_not_acknowledged():
    class Unavailable(FakeS3):
        def put_object(self, **kwargs):
            raise TimeoutError("provider unavailable")
    with pytest.raises(TimeoutError):
        S3ImmutableObjects(Unavailable(), "private-test").put("alice", "chunk", b"content")
