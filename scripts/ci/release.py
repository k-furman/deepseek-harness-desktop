#!/usr/bin/env python3
"""Check version alignment, collect native packages and validate release assets.

Standard library only, including on Ubuntu 22.04's Python 3.10.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import struct
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
SEMVER = re.compile(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?')
PLATFORMS = {'macos': ('macos-arm64', ('.app.tar.gz', '.dmg'), 'macOS 14+'),
             'linux': ('linux-x86_64', ('.deb', '.AppImage'), 'Ubuntu 22.04+ / Debian 12+'),
             'windows': ('windows-x86_64', ('-setup.exe', '.msi'), 'Windows 10 / 11 x64; WebView2 110+')}


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def toml_field(section, field):
    # Only read quoted package name/version and the toolchain channel; not a TOML parser.
    match = re.search(r'^' + re.escape(field) + r'\s*=\s*"([^"\n]+)"\s*$', section, re.M)
    if not match:
        raise ValueError('Missing or unsupported TOML field: ' + field)
    return match[1]


def valid_version(version):
    match = SEMVER.fullmatch(version) if isinstance(version, str) else None
    if not match or (match[4] and any(part.isdigit() and len(part) > 1 and part[0] == '0'
                                     for part in match[4].split('.'))):
        raise ValueError('Expected a semantic version such as 0.1.0 or 0.2.0-rc.1')
    return version


def check_versions(root=ROOT, tag=None):
    package = read_json(root / 'package.json')
    lock = read_json(root / 'package-lock.json')
    cargo = (root / 'src-tauri/Cargo.toml').read_text(encoding='utf-8')
    section = cargo.split('[package]', 1)[1].split('\n[', 1)[0]
    rust_name = toml_field(section, 'name')
    locked = (root / 'src-tauri/Cargo.lock').read_text(encoding='utf-8').split('[[package]]')
    rust_versions = [toml_field(block, 'version') for block in locked[1:]
                     if toml_field(block, 'name') == rust_name]
    if len(rust_versions) != 1:
        raise ValueError('Cargo.lock must contain exactly one application package')
    versions = {'package.json': package['version'], 'package-lock.json': lock['version'],
                'package-lock.json root': lock['packages']['']['version'],
                'Cargo.toml': toml_field(section, 'version'), 'Cargo.lock': rust_versions[0],
                'tauri.conf.json': read_json(root / 'src-tauri/tauri.conf.json')['version']}
    version = valid_version(package['version'])
    if set(versions.values()) != {version}:
        raise ValueError('Application versions differ: ' + json.dumps(versions, sort_keys=True))
    if tag is not None and tag != 'v' + version:
        raise ValueError('Release tag must be v' + version)
    return version


def digest(path):
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()


def one(directory, pattern):
    files = list(directory.glob(pattern))
    if len(files) != 1:
        raise ValueError('Expected exactly one ' + pattern + ' in ' + str(directory))
    return files[0]


def run(*command):
    return subprocess.check_output(command, text=True).strip()


def names(platform, version):
    target, extensions, _ = PLATFORMS[platform]
    return ['DeepSeek-Harness-Desktop_' + version + '_' + target + ext for ext in extensions]


def pe_architecture(path):
    with path.open('rb') as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b'MZ':
            raise ValueError('Expected a Windows PE executable')
        offset = struct.unpack_from('<I', header, 60)[0]
        if offset < 64 or offset > path.stat().st_size - 26:
            raise ValueError('Invalid Windows PE header offset')
        stream.seek(offset)
        pe = stream.read(26)
    if pe[:4] != b'PE\x00\x00':
        raise ValueError('Invalid Windows PE signature')
    machine = struct.unpack_from('<H', pe, 4)[0]
    magic = struct.unpack_from('<H', pe, 24)[0]
    if (machine, magic) not in ((0x8664, 0x20b), (0x14c, 0x10b)):
        raise ValueError('Unsupported Windows PE architecture')
    return 'x64' if machine == 0x8664 else 'x86'


def check_windows_packages(binary, installer, msi, version, inspector):
    if pe_architecture(binary) != 'x64':
        raise ValueError('Expected an x64 Windows application')
    # NSIS uses a 32-bit bootstrapper even when its application payload is x64.
    pe_architecture(installer)
    with msi.open('rb') as stream:
        if stream.read(8) != b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
            raise ValueError('Expected a Windows Installer MSI database')
    metadata = json.loads(run('powershell.exe', '-NoProfile', '-NonInteractive',
                              '-ExecutionPolicy', 'Bypass', '-File', str(inspector), '-Path', str(msi)))
    # WiX maps SemVer prereleases to a fourth numeric MSI version component.
    base = version.split('-')[0]
    if metadata['template'].split(';')[0] != 'x64' or not re.fullmatch(
            re.escape(base) + r'(?:\.\d+)?', metadata['version']):
        raise ValueError('Expected an x64 MSI with the application version')


def collect(platform, root=ROOT):
    version = check_versions(root)
    target, _, minimum = PLATFORMS[platform]
    bundle = root / 'src-tauri/target/release/bundle'
    output = root / 'artifacts' / ('release-' + target)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('Release output must be empty: ' + str(output))
    assets = names(platform, version)
    if platform == 'macos':
        app = one(bundle / 'macos', '*.app')
        with (app / 'Contents/Info.plist').open('rb') as stream:
            info = plistlib.load(stream)
        if info['CFBundleShortVersionString'] != version or info['LSMinimumSystemVersion'] != '14.0':
            raise ValueError('macOS bundle has an unexpected version or deployment target')
        binary = app / 'Contents/MacOS' / info['CFBundleExecutable']
        if run('lipo', '-archs', str(binary)) != 'arm64':
            raise ValueError('Expected an Apple Silicon app')
        subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
        dmg = one(bundle / 'dmg', '*.dmg')
        subprocess.run(['hdiutil', 'verify', str(dmg)], check=True)
        with tarfile.open(output / assets[0], 'w:gz') as archive:
            archive.add(app, arcname=app.name)
        shutil.copy2(dmg, output / assets[1])
    elif platform == 'linux':
        deb = one(bundle / 'deb', '*.deb')
        if run('dpkg-deb', '-f', str(deb), 'Version') != version or run('dpkg-deb', '-f', str(deb), 'Architecture') != 'amd64':
            raise ValueError('Expected an amd64 DEB with the application version')
        image = one(bundle / 'appimage', '*.AppImage')
        with image.open('rb') as stream:
            header = stream.read(64)
        if header[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', header, 18)[0] != 62:
            raise ValueError('Expected an x86_64 AppImage')
        shutil.copy2(deb, output / assets[0])
        shutil.copy2(image, output / assets[1])
    else:
        installer = one(bundle / 'nsis', '*-setup.exe')
        msi = one(bundle / 'msi', '*.msi')
        check_windows_packages(root / 'src-tauri/target/release/deepseek-harness-desktop.exe',
                               installer, msi, version, root / 'scripts/ci/inspect-msi.ps1')
        shutil.copy2(installer, output / assets[0])
        shutil.copy2(msi, output / assets[1])
    manifest_name = 'build-' + target + '.json'
    manifest = {'version': version, 'target': target, 'minimum_os': minimum,
                'commit': os.environ.get('GITHUB_SHA'), 'run_id': os.environ.get('GITHUB_RUN_ID'),
                'node': (root / '.node-version').read_text().strip(),
                'rust': toml_field((root / 'rust-toolchain.toml').read_text(), 'channel'),
                'assets': assets,
                'native_verification': {
                    'macos': 'manual GUI verification required',
                    'linux': 'X11 / Xvfb fixture tests; see workflow logs',
                    'windows': ('MSI/NSIS install, window startup, close and uninstall; GUI fixture verification required'
                                if os.environ.get('DSH_WINDOWS_INSTALLER_VERIFIED') == '1'
                                else 'manual installation and GUI verification required'),
                }[platform]}
    (output / manifest_name).write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    files = sorted(assets + [manifest_name])
    (output / ('SHA256SUMS-' + target)).write_text(
        ''.join(digest(output / name) + '  ' + name + '\n' for name in files), encoding='utf-8')
    print('Collected packages: ' + str(output))
    return output


def verify_release(directory, version, commit=None):
    valid_version(version)
    expected_all = set()
    for platform, (target, _, _) in PLATFORMS.items():
        expected = set(names(platform, version) + ['build-' + target + '.json'])
        checksum_name = 'SHA256SUMS-' + target
        expected_all.update(expected | {checksum_name})
        seen = set()
        lines = (directory / checksum_name).read_text(encoding='utf-8').splitlines()
        for line in lines:
            match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9._+-]+)', line)
            if not match or match[2] not in expected or match[2] in seen:
                raise ValueError('Invalid, unexpected or duplicate checksum entry')
            path = directory / match[2]
            if not path.is_file() or path.is_symlink() or path.stat().st_size == 0 or digest(path) != match[1]:
                raise ValueError('Missing, empty or damaged asset: ' + match[2])
            seen.add(match[2])
        if seen != expected:
            raise ValueError('Incomplete package checksums for ' + target)
        manifest = read_json(directory / ('build-' + target + '.json'))
        if manifest['version'] != version or manifest['target'] != target or manifest['assets'] != names(platform, version):
            raise ValueError('Unexpected build metadata for ' + target)
        if commit is not None and manifest['commit'] != commit:
            raise ValueError('Packages were built from a different commit')
    if {p.name for p in directory.iterdir()} != expected_all:
        raise ValueError('Unexpected files in release directory')
    return sorted(directory / name for name in expected_all)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    versions = sub.add_parser('versions')
    versions.add_argument('--tag')
    collector = sub.add_parser('collect')
    collector.add_argument('--platform', choices=PLATFORMS, required=True)
    verifier = sub.add_parser('verify')
    verifier.add_argument('--directory', type=Path, required=True)
    verifier.add_argument('--tag', required=True)
    verifier.add_argument('--commit')
    args = parser.parse_args()
    try:
        if args.command == 'versions':
            print(check_versions(tag=args.tag))
        elif args.command == 'collect':
            collect(args.platform)
        else:
            version = check_versions(tag=args.tag)
            assets = verify_release(args.directory, version, args.commit)
            print('Verified ' + str(len(assets)) + ' release assets')
    except (ValueError, KeyError, IndexError, OSError) as error:
        parser.exit(1, 'Release validation failed: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
