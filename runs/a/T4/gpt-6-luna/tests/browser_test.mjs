import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, cp, rm } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { createServer } from 'node:net';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const children = [];
let tempRoot;

async function freePort() {
  const server = createServer();
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const { port } = server.address();
  await new Promise((resolveClose, reject) => server.close((error) => error ? reject(error) : resolveClose()));
  return port;
}

async function waitFor(url, child, label) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`${label} exited with ${child.exitCode}`);
    try {
      const response = await fetch(url);
      if (response.ok) return response;
    } catch {}
    await delay(100);
  }
  throw new Error(`${label} did not become ready at ${url}`);
}

class CDP {
  constructor(socket) {
    this.socket = socket;
    this.nextId = 1;
    this.pending = new Map();
    socket.addEventListener('message', ({ data }) => {
      const message = JSON.parse(data);
      const entry = this.pending.get(message.id);
      if (!entry) return;
      this.pending.delete(message.id);
      if (message.error) entry.reject(new Error(message.error.message));
      else entry.resolve(message.result);
    });
  }

  static async connect(url) {
    const socket = new WebSocket(url);
    await new Promise((resolveOpen, reject) => {
      socket.addEventListener('open', resolveOpen, { once: true });
      socket.addEventListener('error', reject, { once: true });
    });
    return new CDP(socket);
  }

  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      const message = { id, method, params };
      if (this.sessionId) message.sessionId = this.sessionId;
      this.socket.send(JSON.stringify(message));
    });
  }

  async evaluate(expression) {
    const response = await this.send('Runtime.evaluate', {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (response.exceptionDetails) {
      throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text);
    }
    return response.result.value;
  }

  close() {
    this.socket.close();
  }
}

async function run() {
  tempRoot = await mkdtemp(join(root, '.adminui-test-'));
  await cp(join(root, 'public'), join(tempRoot, 'public'), { recursive: true });
  await cp(join(root, 'server.py'), join(tempRoot, 'server.py'));
  const appPort = await freePort();
  const cdpPort = await freePort();
  const app = spawn('python3', ['server.py', String(appPort)], { cwd: tempRoot, stdio: 'ignore' });
  children.push(app);
  await waitFor(`http://127.0.0.1:${appPort}/api/users`, app, 'mock API');

  const browser = spawn('lightpanda', [
    'serve', '--host', '127.0.0.1', '--port', String(cdpPort), '--load-resources', 'stylesheet',
  ], { stdio: 'ignore' });
  children.push(browser);
  const versionResponse = await waitFor(`http://127.0.0.1:${cdpPort}/json/version`, browser, 'Lightpanda CDP');
  const version = await versionResponse.json();
  const cdp = await CDP.connect(version.webSocketDebuggerUrl);
  try {
    const target = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const attached = await cdp.send('Target.attachToTarget', { targetId: target.targetId, flatten: true });
    cdp.sessionId = attached.sessionId;
    await cdp.send('Page.enable');
    await cdp.send('Runtime.enable');
    await cdp.send('Page.navigate', { url: `http://127.0.0.1:${appPort}/` });
    await cdp.evaluate(`(async () => {
      for (let i = 0; i < 100; i++) {
        if (document.querySelector('#role-u1')) return true;
        await new Promise(resolve => setTimeout(resolve, 20));
      }
      throw new Error('users did not render');
    })()`);

    const audit = async () => (await (await fetch(`http://127.0.0.1:${appPort}/api/audit`)).json()).writes;
    const stage = async (id, role) => cdp.evaluate(`(() => {
      const select = document.querySelector('#role-${id}');
      select.value = ${JSON.stringify(role)};
      select.dispatchEvent(new Event('change', { bubbles: true }));
      return true;
    })()`);
    const click = async (selector) => cdp.evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
    const state = async (expression) => cdp.evaluate(expression);

    assert.equal(await state(`document.querySelector('#status').getAttribute('aria-live')`), 'polite');
    assert.equal(await state(`document.querySelector('#error').getAttribute('aria-live')`), 'assertive');
    assert.equal(await state(`document.querySelector('#role-u1').getAttribute('aria-label')`), 'Access level for ana@example.test');

    await stage('u1', 'analyst');
    assert.equal((await audit()).length, 0, 'changing a select does not submit');
    assert.equal(await state(`document.querySelector('#pending-u1')?.textContent`), 'Pending: analyst');
    assert.equal(await state(`document.querySelector('#save-u1').disabled`), false);
    await click('#cancel-u1');
    assert.equal(await state(`document.querySelector('#pending-u1')`), null, 'discard removes the staged change');
    assert.equal(await state(`document.querySelector('#role-u1').value`), 'viewer');
    assert.equal((await audit()).length, 0, 'discard does not submit');

    await stage('u1', 'admin');
    assert.equal(await state(`!!document.querySelector('#confirm-u1')`), true, 'admin grant requires confirmation');
    assert.equal(await state(`document.querySelector('#save-u1').disabled`), true, 'apply is disabled until confirmation');
    await click('#confirm-action-u1');
    assert.equal(await state(`document.querySelector('#confirm-action-u1').dataset.confirm`), 'yes');
    assert.equal(await state(`document.querySelector('#save-u1').disabled`), false);

    await cdp.evaluate(`(() => {
      const originalFetch = window.fetch.bind(window);
      window.fetch = (input, init = {}) => {
        if (String(input).includes('/api/users/u1/role')) {
          return new Promise(resolve => setTimeout(() => resolve(originalFetch(input, init)), 250));
        }
        return originalFetch(input, init);
      };
    })()`);
    await click('#save-u1');
    assert.equal(await state(`!!document.querySelector('#loading-u1')`), true, 'loading is visible in flight');
    assert.equal(await state(`document.querySelector('#save-u1').disabled`), true, 'apply is disabled in flight');
    await click('#save-u1');
    await state(`(async () => {
      for (let i = 0; i < 100; i++) {
        if (document.querySelector('#status').textContent.includes('saved')) return true;
        await new Promise(resolve => setTimeout(resolve, 20));
      }
      throw new Error('successful save was not reported');
    })()`);
    assert.equal((await audit()).length, 1, 'duplicate activation submits only once');
    assert.equal(await state(`document.querySelector('#pending-u1')`), null);
    assert.equal(await state(`document.querySelector('#error').textContent`), '');

    await stage('u1', 'analyst');
    assert.equal(await state(`!!document.querySelector('#confirm-u1')`), true, 'admin removal requires confirmation');
    await click('#confirm-action-u1');
    await click('#save-u1');
    await state(`(async () => {
      for (let i = 0; i < 100; i++) {
        if (document.querySelector('#status').textContent.includes('saved')) return true;
        await new Promise(resolve => setTimeout(resolve, 20));
      }
      throw new Error('admin removal was not saved');
    })()`);
    assert.equal((await audit()).length, 2);

    await stage('u2', 'viewer');
    await cdp.send('Network.enable');
    await cdp.send('Network.setExtraHTTPHeaders', { headers: { 'X-Test-Fail': '1' } });
    await click('#save-u2');
    await state(`(async () => {
      for (let i = 0; i < 100; i++) {
        if (document.querySelector('#error').textContent.includes('HTTP 500')) return true;
        await new Promise(resolve => setTimeout(resolve, 20));
      }
      throw new Error('failure was not reported');
    })()`);
    assert.equal(await state(`document.querySelector('#status').textContent`), '', 'failure never claims success');
    assert.equal(await state(`document.querySelector('#pending-u2').textContent`), 'Pending: viewer', 'failure preserves staged change');
    await cdp.send('Network.setExtraHTTPHeaders', { headers: {} });

    const externalChange = await fetch(`http://127.0.0.1:${appPort}/api/users/u2/role`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role: 'analyst', version: 1 }),
    });
    assert.equal(externalChange.status, 200, 'test creates a concurrent update');
    await click('#save-u2');
    await state(`(async () => {
      for (let i = 0; i < 100; i++) {
        if (document.querySelector('#error').textContent.includes('stale version')) return true;
        await new Promise(resolve => setTimeout(resolve, 20));
      }
      throw new Error('409 conflict was not surfaced');
    })()`);
    assert.equal(await state(`document.querySelector('#pending-u2').textContent`), 'Pending: viewer', 'conflict preserves staged change');

    await cdp.send('Emulation.setDeviceMetricsOverride', {
      width: 390, height: 844, deviceScaleFactor: 1, mobile: true,
    });
    const mobile = await state(`(async () => ({ viewport: innerWidth, media: matchMedia('(max-width: 480px)').matches, tableDisplay: getComputedStyle(document.querySelector('#users-table')).display, css: await (await fetch('/styles.css')).text() }))()`);
    assert.equal(mobile.viewport, 390);
    assert.equal(mobile.media, true, '390px viewport activates the compact layout');
    assert.equal(mobile.tableDisplay, 'block');
    assert.match(mobile.css, /table\s*\{[^}]*width:\s*100%/s);
    assert.match(mobile.css, /tbody tr\s*\{[^}]*width:\s*100%/s);
    assert.match(mobile.css, /overflow-wrap:\s*anywhere/);
    assert.match(mobile.css, /select\s*\{[^}]*max-width:\s*100%/s);
    assert.ok((await audit()).length === 5, 'audit includes four UI requests and one concurrent test write');
    console.log('PASS browser interaction, confirmation, loading/duplicate guard, failure, 409 conflict, accessibility, and 390px responsive layout');
  } finally {
    cdp.close();
  }
}

try {
  await run();
} finally {
  for (const child of children.reverse()) {
    child.kill('SIGTERM');
  }
  await Promise.all(children.map((child) => new Promise((resolveChild) => {
    if (child.exitCode !== null) return resolveChild();
    const timer = setTimeout(() => { child.kill('SIGKILL'); resolveChild(); }, 2000);
    child.once('exit', () => { clearTimeout(timer); resolveChild(); });
  })));
  if (tempRoot) await rm(tempRoot, { recursive: true, force: true });
}
