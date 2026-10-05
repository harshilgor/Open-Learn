"""Optional Daytona SDK 0.220 adapter. All execution is remote and bounded.

No ambient credentials, package installation, user commands or public URLs
are passed into the isolated runtime. Reconciliation uses creation labels.
"""
from dataclasses import dataclass
import math


class SandboxError(RuntimeError):
    def __init__(self, code, retryable=False):
        self.code,self.retryable=code,retryable
        super().__init__(code)


@dataclass(frozen=True)
class RemoteFile:
    size: int
    regular: bool


class DaytonaAdapter:
    runtime='daytona'
    runtime_version='daytona-python-0.220.0'
    def __init__(self, client=None):
        if client is None:
            try:
                from daytona import Daytona, DaytonaConfig
                client=Daytona(DaytonaConfig(otel_enabled=False))
            except Exception as exc:raise SandboxError('daytona_setup_required') from exc
        self.client=client

    def reconcile(self, creation_key):
        from daytona import ListSandboxesQuery
        try:
            matches=list(self.client.list(ListSandboxesQuery(labels={'openlearn_creation':creation_key}),request_timeout=10))
        except Exception as exc:raise SandboxError('sandbox_reconciliation_unavailable',True) from exc
        if len(matches)>1:raise SandboxError('sandbox_ambiguous_resources')
        return matches[0].id if matches else None

    def create(self, creation_key, policy):
        from daytona import CreateSandboxFromSnapshotParams
        params=CreateSandboxFromSnapshotParams(name=creation_key,snapshot=policy.snapshot,language='python',
            labels={'openlearn_creation':creation_key,'openlearn_managed':'true'},
            public=False,network_block_all=True,env_vars={},auto_stop_interval=2,
            auto_delete_interval=0,ttl_minutes=math.ceil(policy.lifetime_seconds/60))
        try:return self.client.create(params,timeout=policy.timeout_seconds).id
        except Exception as exc:
            # Timeout is not proof that provider creation failed.
            raise SandboxError('sandbox_creation_unknown',True) from exc

    def _get(self, identifier):
        try:return self.client.get(identifier,request_timeout=10)
        except Exception as exc:raise SandboxError('sandbox_unavailable',True) from exc

    def stage(self, identifier, files):
        sandbox=self._get(identifier)
        try:
            response=sandbox.process.exec('mkdir -p /workspace/uploads /workspace/working /workspace/outputs',timeout=10)
            if response.exit_code!=0:raise SandboxError('sandbox_stage_failed')
            for path,content in files.items():sandbox.fs.upload_file(content,path)
        except SandboxError:raise
        except Exception as exc:raise SandboxError('sandbox_stage_failed',True) from exc

    def execute(self, identifier, timeout):
        try:
            result=self._get(identifier).process.exec('python3 /workspace/working/runner.py',timeout=timeout)
            if result.exit_code!=0:raise SandboxError('sandbox_execution_failed')
        except SandboxError:raise
        except Exception as exc:raise SandboxError('sandbox_execution_unknown',True) from exc

    def download(self, identifier, path, maximum):
        sandbox=self._get(identifier)
        try:
            info=sandbox.fs.get_file_info(path)
            # lstat -type disallows symlinks; fixed path cannot contain quoting.
            result=sandbox.process.exec(f'test -f {path} && test ! -L {path}',timeout=5)
            if result.exit_code!=0 or int(info.size)>maximum:raise SandboxError('sandbox_output_invalid')
            content=sandbox.fs.download_file(path)
            if not isinstance(content,bytes) or len(content)>maximum:raise SandboxError('sandbox_output_invalid')
            return content
        except SandboxError:raise
        except Exception as exc:raise SandboxError('sandbox_output_unavailable',True) from exc

    def release(self, identifier):
        try:self.client.delete(self._get(identifier),timeout=30,wait=True)
        except SandboxError:
            # A resource absent from label listing is already gone.
            raise
        except Exception as exc:raise SandboxError('sandbox_cleanup_pending',True) from exc
