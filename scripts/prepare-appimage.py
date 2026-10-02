"""Prepare the official AppImage plugin for Docker's x86_64 emulation on Mac.

Native x86_64 builders use it unchanged. Some emulators reject its static PIE
loader; in that case run the same verified tool from its extracted AppDir.
"""
import errno
import hashlib
import os
from pathlib import Path
import shlex
import struct
import subprocess
from urllib.request import urlopen

URL = 'https://github.com/linuxdeploy/linuxdeploy-plugin-appimage/releases/download/continuous/linuxdeploy-plugin-appimage-x86_64.AppImage'
SHA256 = '49d6a17160675a6bd1781699aae6bdf7692d98552e02a3671d2183d10547842e'
cache = Path(os.environ.get('XDG_CACHE_HOME', str(Path.home() / '.cache'))) / 'tauri'
cache.mkdir(parents=True, exist_ok=True)
plugin = cache / 'linuxdeploy-plugin-appimage.AppImage'
if not plugin.exists():
    with urlopen(URL, timeout=120) as response:
        payload = response.read()
    if hashlib.sha256(payload).hexdigest() != SHA256:
        raise SystemExit('AppImage plugin checksum changed; review the official release before updating the pin.')
    plugin.write_bytes(payload)
    plugin.chmod(0o755)
try:
    subprocess.run([str(plugin), '--plugin-api-version'], check=True, capture_output=True)
except OSError as error:
    if error.errno != errno.ENOEXEC:
        raise
    payload = plugin.read_bytes()
    if hashlib.sha256(payload).hexdigest() != SHA256:
        raise SystemExit('AppImage plugin checksum mismatch.')
    if payload[:6] != b'\x7fELF\x02\x01':
        raise SystemExit('Expected an ELF64 little-endian AppImage.')
    offset = struct.unpack_from('<Q', payload, 40)[0]
    offset += struct.unpack_from('<H', payload, 58)[0] * struct.unpack_from('<H', payload, 60)[0]
    if payload[offset:offset + 4] != b'hsqs':
        raise SystemExit('Expected the AppImage SquashFS after its ELF section table.')
    extracted = cache / 'dsh-appimage-plugin'
    subprocess.run(['unsquashfs', '-no-progress', '-o', str(offset), '-d', str(extracted), str(plugin)], check=True)
    original = cache / 'dsh-appimage-plugin.bin'
    plugin.rename(original)
    plugin.write_text('#!/bin/sh\nexec ' + shlex.quote(str(extracted / 'AppRun')) + ' "$@"\n')
    plugin.chmod(0o755)
    subprocess.run([str(plugin), '--plugin-api-version'], check=True)
    print('Using the verified AppImage plugin from its extracted AppDir.')
