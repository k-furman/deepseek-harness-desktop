import { spawnSync } from 'node:child_process';

// Python's official Windows installer exposes python.exe; Unix exposes python3.
const command = process.platform === 'win32' ? 'python' : 'python3';
const result = spawnSync(command, process.argv.slice(2), { stdio: 'inherit', shell: false });
if (result.error) console.error(`Cannot start ${command}: ${result.error.message}`);
process.exit(result.status ?? 1);
