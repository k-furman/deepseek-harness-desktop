import { existsSync } from 'node:fs';
import { delimiter, join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const env = { ...process.env };
const cargo = process.platform === 'win32' ? 'cargo.exe' : 'cargo';
const localCargo = join(root, '.tools', 'cargo');
if (existsSync(join(localCargo, 'bin', cargo))) {
  env.CARGO_HOME = localCargo;
  env.RUSTUP_HOME = join(root, '.tools', 'rustup');
  const pathKey = Object.keys(env).find(key => key.toLowerCase() === 'path') ?? 'PATH';
  env[pathKey] = join(localCargo, 'bin') + delimiter + (env[pathKey] ?? '');
}

function run(command, args) {
  const result = spawnSync(command, args, { cwd: root, env, stdio: 'inherit', shell: false });
  if (result.error) {
    console.error(`Cannot start ${command}: ${result.error.message}`);
    process.exit(1);
  }
  if (result.status !== 0) process.exit(result.status ?? 1);
}

const [action = 'tauri', ...args] = process.argv.slice(2);
if (action === 'cargo') {
  run(cargo, args);
} else if (action === 'check') {
  run(cargo, ['fmt', '--manifest-path', 'src-tauri/Cargo.toml', '--check']);
  run(cargo, ['clippy', '--locked', '--manifest-path', 'src-tauri/Cargo.toml', '--all-targets', '--', '-D', 'warnings']);
  run(cargo, ['test', '--locked', '--manifest-path', 'src-tauri/Cargo.toml']);
} else if (action === 'tauri') {
  run(process.execPath, [join(root, 'node_modules', '@tauri-apps', 'cli', 'tauri.js'), ...args]);
} else {
  console.error(`Unknown Rust tool action: ${action}`);
  process.exit(1);
}
