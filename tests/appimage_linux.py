"""Validate the packaged AppDir even when static PIE cannot run in emulation."""
import argparse
import os
from pathlib import Path
import struct
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', action='store_true', help='Launch the original AppImage on native x86_64')
    args = parser.parse_args()
    packages = list(Path('artifacts/linux').glob('*.AppImage'))
    assert len(packages) == 1, 'Expected one AppImage'
    package = packages[0].resolve()
    if args.runtime:
        env = os.environ.copy()
        env.update(DSH_TEST_BINARY=str(package), APPIMAGE_EXTRACT_AND_RUN='1')
        subprocess.run(['dbus-run-session', '--', 'xvfb-run', '-a', 'python3',
                        'tests/download_linux.py'], env=env, check=True)
        print('PASS original AppImage runtime: startup, authentication, native Save/Cancel and file content', flush=True)
        return
    with package.open('rb') as stream:
        header = stream.read(64)
        assert header[:6] == b'\x7fELF\x02\x01', 'Expected ELF64 little endian'
        section_table = struct.unpack_from('<Q', header, 40)[0]
        section_size, section_count = struct.unpack_from('<HH', header, 58)
        offset = section_table + section_size * section_count
        stream.seek(offset)
        assert stream.read(4) == b'hsqs', 'Expected AppImage SquashFS payload'
    with tempfile.TemporaryDirectory(prefix='dsh-appimage-') as directory:
        appdir = Path(directory) / 'AppDir'
        subprocess.run(['unsquashfs', '-o', str(offset), '-d', str(appdir), str(package)],
            check=True, stdout=subprocess.DEVNULL)
        env = os.environ.copy()
        env.update(DSH_TEST_BINARY=str(appdir / 'AppRun'), DSH_TEST_PROCESS=str(appdir))
        subprocess.run(['dbus-run-session', '--', 'xvfb-run', '-a', 'python3',
            'tests/download_linux.py'], env=env, check=True)
    print('PASS packaged AppImage AppRun: startup, authentication, native Save/Cancel and file content', flush=True)


if __name__ == '__main__':
    main()
