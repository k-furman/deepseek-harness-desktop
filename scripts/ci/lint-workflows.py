#!/usr/bin/env python3
"""Download the pinned official actionlint binary, verify it, then lint workflows."""
import hashlib
import io
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile
from urllib.request import urlopen

VERSION = '1.7.12'
CHECKSUMS = {
    ('Linux', 'x86_64'): ('linux_amd64', '8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8'),
    ('Darwin', 'arm64'): ('darwin_arm64', 'aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f'),
}
target, checksum = CHECKSUMS[(platform.system(), platform.machine())]
url = f'https://github.com/rhysd/actionlint/releases/download/v{VERSION}/actionlint_{VERSION}_{target}.tar.gz'
with urlopen(url, timeout=60) as response:
    payload = response.read()
if hashlib.sha256(payload).hexdigest() != checksum:
    raise SystemExit('actionlint checksum mismatch')
with tempfile.TemporaryDirectory(prefix='dsh-actionlint-') as directory:
    binary = Path(directory) / 'actionlint'
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
        member = archive.getmember('actionlint')
        if not member.isfile():
            raise SystemExit('Expected actionlint executable')
        with archive.extractfile(member) as stream:
            binary.write_bytes(stream.read())
    binary.chmod(0o755)
    root = Path(__file__).resolve().parents[2]
    workflows = sorted((root / '.github/workflows').glob('*.yml'))
    # Explicit paths also work before a Git repository has been created locally.
    subprocess.run([str(binary), '-color', *map(str, workflows)], cwd=root, check=True)
