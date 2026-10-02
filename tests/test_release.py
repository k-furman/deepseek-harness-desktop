"""Release gates must reject inconsistent versions and damaged/foreign artifacts."""
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release', ROOT / 'scripts/ci/release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)
sys.modules['release'] = release
draft_spec = importlib.util.spec_from_file_location('draft_release', ROOT / 'scripts/ci/draft-release.py')
draft = importlib.util.module_from_spec(draft_spec)
draft_spec.loader.exec_module(draft)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dsh-release-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('package.json', 'package-lock.json', 'src-tauri/Cargo.toml',
                     'src-tauri/Cargo.lock', 'src-tauri/tauri.conf.json',
                     '.node-version', 'rust-toolchain.toml'):
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        self.version = release.check_versions(self.root)
        self.assets = self.root / 'assets'
        self.assets.mkdir()

    def packages(self):
        for platform, (target, _, _) in release.PLATFORMS.items():
            names = release.names(platform, self.version)
            for name in names:
                (self.assets / name).write_bytes(b'real fixture bytes\n')
            manifest = {'version': self.version, 'target': target, 'commit': 'a' * 40, 'assets': names}
            (self.assets / ('build-' + target + '.json')).write_text(json.dumps(manifest))
            self.checksums(platform)

    def checksums(self, platform):
        target = release.PLATFORMS[platform][0]
        names = release.names(platform, self.version) + ['build-' + target + '.json']
        (self.assets / ('SHA256SUMS-' + target)).write_text(
            ''.join(release.digest(self.assets / name) + '  ' + name + '\n' for name in names))

    def test_consistent_versions_and_tag(self):
        self.assertEqual(release.check_versions(self.root, 'v' + self.version), self.version)

    def test_version_drift_is_rejected(self):
        path = self.root / 'src-tauri/tauri.conf.json'
        config = json.loads(path.read_text())
        config['version'] = '99.0.0'
        path.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, 'versions differ'):
            release.check_versions(self.root)

    def test_wrong_tag_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Release tag'):
            release.check_versions(self.root, 'v99.0.0')

    def test_semver_validation(self):
        self.assertEqual(release.valid_version('1.2.3-rc.1'), '1.2.3-rc.1')
        for value in ('01.2.3', '1.2', '1.2.3-01', '1.2.3/../x', '1.2.3-'):
            with self.subTest(version=value), self.assertRaises(ValueError):
                release.valid_version(value)

    def test_complete_packages_are_accepted(self):
        self.packages()
        self.assertEqual(len(release.verify_release(self.assets, self.version, 'a' * 40)), 12)

    def test_windows_packages_are_required_even_if_unix_packages_are_complete(self):
        self.packages()
        for path in self.assets.glob('*windows-x86_64*'):
            path.unlink()
        with self.assertRaises(FileNotFoundError):
            release.verify_release(self.assets, self.version)

    def pe_file(self, name, machine=0x8664, magic=0x20b):
        path = self.root / name
        data = bytearray(128)
        data[:2] = b'MZ'
        struct.pack_into('<I', data, 60, 64)
        data[64:68] = b'PE\x00\x00'
        struct.pack_into('<H', data, 68, machine)
        struct.pack_into('<H', data, 88, magic)
        path.write_bytes(data)
        return path

    def test_pe_architecture_and_corrupt_headers(self):
        path = self.pe_file('app.exe')
        self.assertEqual(release.pe_architecture(path), 'x64')
        self.assertEqual(release.pe_architecture(self.pe_file('nsis.exe', 0x14c, 0x10b)), 'x86')
        with self.assertRaisesRegex(ValueError, 'architecture'):
            release.pe_architecture(self.pe_file('arm64.exe', 0xaa64))
        for contents in (b'MZ', b'not a PE', b'MZ' + b'\x00' * 62):
            path.write_bytes(contents)
            with self.subTest(contents=contents), self.assertRaises(ValueError):
                release.pe_architecture(path)

    def test_windows_accepts_x86_bootstrapper_but_requires_x64_payload_and_msi(self):
        binary = self.pe_file('app.exe')
        installer = self.pe_file('setup.exe', 0x14c, 0x10b)
        msi = self.root / 'package.msi'
        msi.write_bytes(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1fixture')
        inspector = self.root / 'inspect.ps1'
        with patch.object(release, 'run', return_value=json.dumps({'version': self.version, 'template': 'x64;1033'})):
            release.check_windows_packages(binary, installer, msi, self.version, inspector)
        for metadata in ({'version': '99.0.0', 'template': 'x64;1033'},
                         {'version': self.version, 'template': 'Intel;1033'}):
            with patch.object(release, 'run', return_value=json.dumps(metadata)), self.assertRaisesRegex(ValueError, 'x64 MSI'):
                release.check_windows_packages(binary, installer, msi, self.version, inspector)
        with self.assertRaisesRegex(ValueError, 'x64 Windows application'):
            release.check_windows_packages(installer, installer, msi, self.version, inspector)
        msi.write_bytes(b'not an MSI')
        with self.assertRaisesRegex(ValueError, 'MSI database'):
            release.check_windows_packages(binary, installer, msi, self.version, inspector)

    def test_windows_collector_preserves_installer_bytes_and_records_checksums(self):
        native = self.root / 'src-tauri/target/release'
        (native / 'bundle/nsis').mkdir(parents=True)
        (native / 'bundle/msi').mkdir()
        shutil.copyfile(self.pe_file('payload.exe'), native / 'deepseek-harness-desktop.exe')
        installer = native / 'bundle/nsis/original-setup.exe'
        shutil.copyfile(self.pe_file('bootstrapper.exe', 0x14c, 0x10b), installer)
        msi = native / 'bundle/msi/original.msi'
        msi.write_bytes(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1fixture')
        with patch.object(release, 'run', return_value=json.dumps({'version': self.version, 'template': 'x64;1033'})):
            output = release.collect('windows', self.root)
        for source, name in zip((installer, msi), release.names('windows', self.version)):
            self.assertEqual(source.read_bytes(), (output / name).read_bytes())
        manifest = release.read_json(output / 'build-windows-x86_64.json')
        self.assertEqual(manifest['assets'], release.names('windows', self.version))
        for line in (output / 'SHA256SUMS-windows-x86_64').read_text().splitlines():
            digest, name = line.split('  ')
            self.assertEqual(digest, release.digest(output / name))
        with self.assertRaisesRegex(ValueError, 'must be empty'):
            release.collect('windows', self.root)

    def test_changed_asset_is_rejected(self):
        self.packages()
        (self.assets / release.names('linux', self.version)[0]).write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError, 'damaged asset'):
            release.verify_release(self.assets, self.version)

    def test_foreign_commit_is_rejected(self):
        self.packages()
        with self.assertRaisesRegex(ValueError, 'different commit'):
            release.verify_release(self.assets, self.version, 'b' * 40)

    def test_foreign_metadata_is_rejected_even_with_valid_checksum(self):
        self.packages()
        path = self.assets / 'build-macos-arm64.json'
        manifest = json.loads(path.read_text())
        manifest['target'] = 'macos-intel'
        path.write_text(json.dumps(manifest))
        self.checksums('macos')
        with self.assertRaisesRegex(ValueError, 'metadata'):
            release.verify_release(self.assets, self.version)

    def test_omitted_asset_is_rejected(self):
        self.packages()
        path = self.assets / 'SHA256SUMS-linux-x86_64'
        path.write_text(path.read_text().splitlines()[0] + '\n')
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            release.verify_release(self.assets, self.version)

    def test_path_traversal_and_duplicate_entries_are_rejected(self):
        self.packages()
        path = self.assets / 'SHA256SUMS-macos-arm64'
        valid = path.read_text()
        for invalid in (valid + '0' * 64 + '  ../outside\n', valid + valid.splitlines()[0] + '\n'):
            path.write_text(invalid)
            with self.assertRaisesRegex(ValueError, 'checksum entry'):
                release.verify_release(self.assets, self.version)

    def test_symlink_is_rejected(self):
        self.packages()
        path = self.assets / release.names('linux', self.version)[0]
        destination = self.root / 'outside'
        path.rename(destination)
        try:
            path.symlink_to(destination)
        except OSError as error:
            if sys.platform == 'win32' and getattr(error, 'winerror', None) == 1314:
                self.skipTest('Real symlink test requires Windows Developer Mode or an elevated terminal; Linux CI always runs it')
            raise
        with self.assertRaisesRegex(ValueError, 'damaged asset'):
            release.verify_release(self.assets, self.version)

    def test_extra_files_are_rejected(self):
        self.packages()
        (self.assets / 'unverified.bin').write_bytes(b'not a release asset')
        with self.assertRaisesRegex(ValueError, 'Unexpected files'):
            release.verify_release(self.assets, self.version)

    def test_new_release_is_always_a_draft(self):
        self.packages()
        with patch.object(draft.subprocess, 'run', return_value=SimpleNamespace(returncode=1)) as gh:
            draft.create_draft(self.assets, 'v' + self.version, 'owner/repo', 'a' * 40, self.root)
        command = gh.call_args[0][0]
        self.assertEqual(command[:3], ['gh', 'release', 'create'])
        self.assertIn('--draft', command)
        self.assertIn('--verify-tag', command)
        self.assertIn('--notes-file', command)
        self.assertEqual(set(command[-12:]),
                         {str(path) for path in release.verify_release(self.assets, self.version, 'a' * 40)})

    def test_rerun_updates_only_a_draft(self):
        self.packages()
        result = SimpleNamespace(returncode=0, stdout='{"isDraft":true}')
        with patch.object(draft.subprocess, 'run', return_value=result) as gh:
            draft.create_draft(self.assets, 'v' + self.version, 'owner/repo', 'a' * 40, self.root)
        self.assertEqual(gh.call_args[0][0][:3], ['gh', 'release', 'upload'])
        self.assertIn('--clobber', gh.call_args[0][0])

    def test_published_release_cannot_be_modified(self):
        self.packages()
        result = SimpleNamespace(returncode=0, stdout='{"isDraft":false}')
        with patch.object(draft.subprocess, 'run', return_value=result) as gh:
            with self.assertRaisesRegex(SystemExit, 'published'):
                draft.create_draft(self.assets, 'v' + self.version, 'owner/repo', 'a' * 40, self.root)
        self.assertEqual(gh.call_count, 1)

    def test_bad_assets_stop_before_any_github_command(self):
        self.packages()
        (self.assets / release.names('linux', self.version)[0]).write_bytes(b'corrupted')
        with patch.object(draft.subprocess, 'run') as gh:
            with self.assertRaises(ValueError):
                draft.create_draft(self.assets, 'v' + self.version, 'owner/repo', 'a' * 40, self.root)
        gh.assert_not_called()


if __name__ == '__main__':
    unittest.main()
