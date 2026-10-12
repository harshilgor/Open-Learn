"""Run pinned, checksum-verified actionlint on platform workflows locally or in CI."""
from io import BytesIO
import hashlib
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import zipfile

import httpx

ROOT = Path(__file__).resolve().parents[2]
VERSION = "1.7.12"
# Digests published for these assets by the official rhysd/actionlint release.
ASSETS = {
    "Windows": ("windows_amd64.zip", "6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9", "actionlint.exe"),
    "Linux": ("linux_amd64.tar.gz", "8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8", "actionlint"),
}


def main():
    system = platform.system()
    if system not in ASSETS or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("Use a supported x86_64 Windows or Linux environment for this pinned validator.")
    asset, expected, binary = ASSETS[system]
    folder = ROOT / "outputs/tools" / ("actionlint-" + VERSION)
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / ("actionlint_" + VERSION + "_" + asset)
    if archive.exists() and hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise SystemExit("Cached actionlint archive checksum mismatch; do not execute it.")
    if not archive.exists():
        url = "https://github.com/rhysd/actionlint/releases/download/v" + VERSION + "/" + archive.name
        response = httpx.get(url, timeout=30, follow_redirects=True)
        response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest() != expected:
            raise SystemExit("Downloaded actionlint archive checksum mismatch; do not execute it.")
        archive.write_bytes(response.content)
    # Read only the known executable; do not extract arbitrary archive paths.
    data = archive.read_bytes()
    if system == "Windows":
        with zipfile.ZipFile(BytesIO(data)) as package:
            payload = package.read(binary)
    else:
        with tarfile.open(fileobj=BytesIO(data), mode="r:gz") as package:
            entry = package.extractfile(binary)
            if entry is None:
                raise SystemExit("Pinned archive lacks its validator.")
            payload = entry.read()
    executable = folder / binary
    executable.write_bytes(payload)
    if os.name != "nt":
        executable.chmod(0o755)
    files = ["platform-quality.yml", "platform-release.yml", "platform-release-validation.yml"]
    command = [str(executable), "-shellcheck=", "-pyflakes="] + [str(ROOT / ".github/workflows" / name) for name in files]
    result = subprocess.run(command, cwd=ROOT, check=False, timeout=30)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
