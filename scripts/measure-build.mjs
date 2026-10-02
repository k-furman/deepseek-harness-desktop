// Report shipped files only; dependency caches and compiler output are excluded.
import { existsSync, readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
function bytes(path) {
  return readdirSync(path, { withFileTypes: true }).reduce((total, entry) => {
    const child = join(path, entry.name);
    return total + (entry.isDirectory() ? bytes(child) : entry.isFile() ? statSync(child).size : 0);
  }, 0);
}
const binary = join(root, 'src-tauri/target/release',
  'deepseek-harness-desktop' + (process.platform === 'win32' ? '.exe' : ''));
const app = join(root, 'src-tauri/target/release/bundle/macos/DeepSeek Harness Desktop.app');
const dist = join(root, 'dist');
console.log(JSON.stringify({
  platform: process.platform,
  arch: process.arch,
  frontendBytes: existsSync(dist) ? bytes(dist) : null,
  executableBytes: existsSync(binary) ? statSync(binary).size : null,
  macosAppBytes: process.platform === 'darwin' && existsSync(app) ? bytes(app) : null,
}, null, 2));
