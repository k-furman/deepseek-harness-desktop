#!/usr/bin/env python3
"""Create/update a draft only, using the assets from this workflow run."""
import json
import os
from pathlib import Path
import subprocess

from release import ROOT, check_versions, verify_release

def create_draft(directory, tag, repo, commit, root=ROOT):
    version = check_versions(root, tag=tag)
    files = verify_release(directory, version, commit)
    notes = directory.parent / 'release-notes.md'
    notes.write_text('''macOS 14+ (Apple Silicon): `.dmg` or extract `.app.tar.gz`.
Linux x86_64 (Ubuntu 22.04+ / Debian 12+): `.deb` or `.AppImage`.
Windows 10/11 x64: `-setup.exe` (per-user, English/Russian) or `.msi` (English).
Windows installers include the WebView2 bootstrapper; first installation needs internet if the runtime is missing/outdated.

Build metadata and SHA-256 are attached for all three platforms.
macOS uses ad-hoc signing, without Apple Developer ID or notarization.
Windows installers have no Authenticode signature; Windows may show an unknown-publisher warning.
macOS/Windows GUI and real DeepSeek Harness connections require manual verification before publication.
Linux fixture tests run under X11/Xvfb; Wayland and Debian 12 require manual verification.
''', encoding='utf-8')
    existing = subprocess.run(['gh', 'release', 'view', tag, '--repo', repo, '--json', 'isDraft'],
                              capture_output=True, text=True)
    if existing.returncode == 0:
        if not json.loads(existing.stdout)['isDraft']:
            raise SystemExit('Refusing to change an already published release')
        subprocess.run(['gh', 'release', 'upload', tag, '--repo', repo, '--clobber',
                        *map(str, files)], check=True)
    else:
        command = ['gh', 'release', 'create', tag, '--repo', repo, '--draft', '--verify-tag',
                   '--title', 'DeepSeek Harness Desktop ' + version, '--notes-file', str(notes)]
        if '-' in version:
            command.append('--prerelease')
        subprocess.run([*command, *map(str, files)], check=True)


if __name__ == '__main__':
    create_draft(Path('artifacts/release'), os.environ['RELEASE_TAG'],
                 os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_SHA'])
