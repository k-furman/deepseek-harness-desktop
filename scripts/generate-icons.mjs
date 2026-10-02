import { copyFileSync, mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const temporary = mkdtempSync(join(tmpdir(), 'dsh-icons-'));
const cli = join(root, 'node_modules', '@tauri-apps', 'cli', 'tauri.js');
const source = join(root, 'assets', 'app-icon.svg');
const destination = join(root, 'src-tauri', 'icons');

function generate(output, options = []) {
  const result = spawnSync(process.execPath, [cli, 'icon', source, '--output', output, ...options], {
    cwd: root,
    stdio: 'inherit',
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`Tauri icon generation failed (${result.status ?? result.signal})`);
}

try {
  generate(temporary);
  mkdirSync(destination, { recursive: true });
  for (const name of ['32x32.png', '64x64.png', '128x128.png', '128x128@2x.png', 'icon.png', 'icon.icns', 'icon.ico']) {
    copyFileSync(join(temporary, name), join(destination, name));
  }
} finally {
  rmSync(temporary, { recursive: true, force: true });
}
