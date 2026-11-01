import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadEnv } from 'vite';

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const root = path.resolve(frontend, '..');
const python = directory => path.join(directory, process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const children = [];
let stopping = false;

function listening(host, port) {
  return new Promise(resolve => {
    const socket = net.createConnection({ host, port });
    const finish = value => { socket.destroy(); resolve(value); };
    socket.setTimeout(400);
    socket.once('connect', () => finish(true));
    socket.once('error', () => finish(false));
    socket.once('timeout', () => finish(false));
  });
}
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  for (const child of children) child.kill();
  process.exitCode = code;
  setTimeout(() => process.exit(code), 300).unref();
}
process.once('SIGINT', () => stop());
process.once('SIGTERM', () => stop());

function worker(name, command, args, cwd, environment = {}) {
  if (!existsSync(command)) throw new Error(`${name}: runtime missing at ${command}`);
  console.log(`Starting ${name}`);
  const child = spawn(command, args, { cwd, stdio: 'inherit', windowsHide: true, env: { ...process.env, ...environment, PYTHONUNBUFFERED: '1' } });
  children.push(child);
  child.once('error', error => { console.error(`${name}: ${error.message}`); stop(1); });
  child.once('exit', code => { if (!stopping) { console.error(`${name} stopped (exit ${code}).`); stop(1); } });
}

async function start(name, command, args, cwd, host, port, environment = {}) {
  if (await listening(host, port)) {
    console.log(`${name}: reusing the process already listening on ${host}:${port}`);
    return false;
  }
  if (!existsSync(command)) throw new Error(`${name}: required runtime not found at ${command}`);
  console.log(`Starting ${name} on ${host}:${port}`);
  const child = spawn(command, args, { cwd, stdio: 'inherit', windowsHide: true, env: { ...process.env, ...environment, PYTHONUNBUFFERED: '1' } });
  children.push(child);
  child.once('error', error => { console.error(`${name}: ${error.message}`); stop(1); });
  child.once('exit', code => {
    if (!stopping) { console.error(`${name} stopped (exit ${code}). Stopping processes started by this command.`); stop(1); }
  });
  for (let attempt = 0; attempt < 100 && !stopping; attempt++) {
    if (await listening(host, port)) return true;
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  if (!stopping) throw new Error(`${name} did not become ready. Check its startup output above.`);
}

try {
  console.log('Starting the local forum: Identity 8000, Discussion 8001, Realtime 8002, Search 8003, frontend 5173.');
  console.log('PostgreSQL and Redis must already be running. Press Ctrl+C to stop processes started here.');
  const identity = path.join(root, 'services/identity');
  // Reuse Identity's existing development registration in child-process memory.
  // Never copy service credentials into frontend files or browser variables.
  const serviceKeys = JSON.parse(loadEnv('development', root, '').SERVICE_API_KEYS || '{}');
  const discussionEnvironment = serviceKeys.discussion ? { IDENTITY_SERVICE_KEY: serviceKeys.discussion } : {};
  await start('Identity', python(path.join(identity, '.venv')), ['manage.py', 'runserver', '127.0.0.1:8000', '--noreload'], identity, '127.0.0.1', 8000);
  if (!stopping) worker('Identity outbox relay', python(path.join(identity, '.venv')), ['manage.py', 'run_outbox_relay'], identity);
  if (!stopping) worker('Identity activity consumer', python(path.join(identity, '.venv')), ['manage.py', 'consume_events'], identity);
  if (!stopping) {
    const discussion = path.join(root, 'services/discussion');
    const started = await start('Discussion', python(path.join(root, '.venv')), ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8001'], discussion, '127.0.0.1', 8001, discussionEnvironment);
    // An existing server may predate the lifespan relay. Its advisory lock
    // makes this compatibility worker safe even when that server has a relay.
    if (!started && !stopping) worker('Discussion outbox relay', python(path.join(root, '.venv')), ['-c', 'import asyncio; from app.outbox.relay import run_outbox_relay; asyncio.run(run_outbox_relay())'], discussion, discussionEnvironment);
  }
  if (!stopping) await start('Realtime', python(path.join(root, '.venv')), ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8002'], path.join(root, 'services/notification_realtime'), '127.0.0.1', 8002);
  if (!stopping) await start('Search', python(path.join(root, '.venv')), ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8003'], path.join(root, 'services/search'), '127.0.0.1', 8003);
  if (!stopping) await start('Frontend', process.execPath, [path.join(frontend, 'node_modules/vite/bin/vite.js'), '--host', 'localhost'], frontend, 'localhost', 5173);
  if (!stopping) console.log('Forum ready: http://localhost:5173');
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  stop(1);
}
