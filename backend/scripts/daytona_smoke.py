"""Run the requested Daytona hello-world in a disposable sandbox.

Set DAYTONA_API_KEY in the backend process environment. This is an operator
smoke check, not an agent tool or a route exposed to users.
"""
import os
import sys

from daytona import CreateSandboxFromSnapshotParams, Daytona, DaytonaConfig


def main() -> int:
    api_key = os.environ.get("DAYTONA_API_KEY")
    if not api_key:
        print("Set DAYTONA_API_KEY in the backend environment before running.")
        return 2
    client = Daytona(DaytonaConfig(api_key=api_key))
    sandbox = None
    result_code = 1
    try:
        sandbox = client.create(
            CreateSandboxFromSnapshotParams(
                public=False,
                auto_stop_interval=5,
                auto_delete_interval=10,
                network_block_all=True,
            ),
            timeout=60,
        )
        result = sandbox.process.code_run('print("Hello World from code!")')
        if result.exit_code == 0:
            print(result.result)
            result_code = 0
        else:
            print(f"Sandbox code failed with exit code {result.exit_code}.")
    except Exception as error:
        # SDK exception messages can contain provider details. Do not log them.
        print(f"Daytona request failed ({type(error).__name__}).")
    finally:
        if sandbox is not None:
            try:
                client.delete(sandbox, timeout=60, wait=True)
            except Exception as error:
                print(f"Cleanup requires operator review ({type(error).__name__}).")
                result_code = 1
    return result_code


if __name__ == "__main__":
    sys.exit(main())
