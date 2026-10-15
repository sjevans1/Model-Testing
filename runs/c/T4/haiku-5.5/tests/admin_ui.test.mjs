// Browser-driven tests for the users-and-access screen.
//
// Starts the mock API (server.py) and a headless Lightpanda browser, then drives the
// real page over the DevTools protocol. Each test gets a fresh API server so the
// in-memory user state and writes.log start clean.
//
// Run: node tests/admin_ui.test.mjs   (or sh run_checks.sh)

import { describe, it, before, after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

async function waitFor(fn, what, timeoutMs = 15000) {
  const deadline = Date.now() + timeoutMs;
  let lastErr;
  while (Date.now() < deadline) {
    try {
      const v = await fn();
      if (v) return v;
    } catch (err) {
      lastErr = err;
    }
    await new Promise((r) => setTimeout(r, 50));
  }
  throw new Error(`timed out waiting for ${what}${lastErr ? `: ${lastErr.message}` : ''}`);
}

// ---------- API server ----------

async function startApi() {
  const port = await freePort();
  const proc = spawn('python3', ['server.py', String(port)], { cwd: ROOT, stdio: 'ignore' });
  const base = `http://127.0.0.1:${port}`;
  await waitFor(() => fetch(`${base}/api/users`).then((r) => r.ok), 'api server');
  return { base, port, stop: () => proc.kill() };
}

async function getJson(url) {
  return (await fetch(url)).json();
}

async function audit(api) {
  return (await getJson(`${api.base}/api/audit`)).writes;
}

async function apiPost(api, id, body, headers = {}) {
  return fetch(`${api.base}/api/users/${id}/role`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  });
}

// ---------- Lightpanda + minimal CDP client ----------

let browserProc;
let cdpUrl;

async function startBrowser() {
  const port = await freePort();
  browserProc = spawn('lightpanda', ['serve', '--host', '127.0.0.1', '--port', String(port)], {
    stdio: ['ignore', 'ignore', 'pipe'],
  });
  browserProc.stderr.resume();
  await waitFor(() => fetch(`http://127.0.0.1:${port}/json/version`).then((r) => r.ok), 'lightpanda');
  cdpUrl = `ws://127.0.0.1:${port}/`;
}

class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.nextId = 1;
    this.pending = new Map();
    this.listeners = [];
    ws.onmessage = (ev) => {
      const msg = JSON.parse(typeof ev.data === 'string' ? ev.data : ev.data.toString());
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(`${msg.error.message}`));
        else resolve(msg.result);
      } else if (msg.method) {
        for (const fn of this.listeners) fn(msg);
      }
    };
  }

  static connect(url) {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(url);
      ws.onopen = () => resolve(new Cdp(ws));
      ws.onerror = () => reject(new Error(`cannot connect to ${url}`));
    });
  }

  send(method, params = {}, sessionId) {
    const id = this.nextId++;
    const payload = { id, method, params };
    if (sessionId) payload.sessionId = sessionId;
    this.ws.send(JSON.stringify(payload));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }

  close() {
    this.ws.close();
  }
}

class Page {
  constructor(cdp, sessionId) {
    this.cdp = cdp;
    this.sid = sessionId;
  }

  static async open(cdp, url) {
    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
    const page = new Page(cdp, sessionId);
    page.targetId = targetId;
    await page.send('Page.enable');
    await page.send('Runtime.enable');
    await page.send('Page.navigate', { url });
    await waitFor(() => page.eval('document.readyState === "complete" && !!document.querySelector("#users-table tbody tr")'), 'page render');
    return page;
  }

  send(method, params) {
    return this.cdp.send(method, params, this.sid);
  }

  async eval(expression) {
    const res = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (res.exceptionDetails) {
      throw new Error(`page eval failed: ${res.exceptionDetails.exception?.description || res.exceptionDetails.text}`);
    }
    return res.result.value;
  }

  // Click via the DOM, the same as an activation by a user (dispatches click events).
  click(id) {
    return this.eval(`(() => { const el = document.getElementById(${JSON.stringify(id)}); if (!el) throw new Error('no #${id}'); el.click(); return true; })()`);
  }

  // Pick a role in the <select> and dispatch the change event a user would produce.
  choose(id, value) {
    return this.eval(`(() => { const el = document.getElementById(${JSON.stringify(id)}); el.value = ${JSON.stringify(value)}; el.dispatchEvent(new Event('change', { bubbles: true })); return true; })()`);
  }

  // Read the state of an element by id.
  info(id) {
    return this.eval(`(() => {
      const el = document.getElementById(${JSON.stringify(id)});
      if (!el) return null;
      const cs = getComputedStyle(el);
      const visible = !el.hidden && cs.display !== 'none' && cs.visibility !== 'hidden';
      return { visible, disabled: !!el.disabled, text: el.textContent, value: el.value,
               label: el.getAttribute('aria-label'), role: el.getAttribute('role'),
               live: el.getAttribute('aria-live') };
    })()`);
  }

  // Install a fetch wrapper that changes outgoing POSTs (used to inject a delay or a
  // failure header; the page itself is otherwise unmodified).
  wrapPostFetch({ delayMs = 0, failHeader = false } = {}) {
    return this.eval(`(() => {
      const real = window.fetch.bind(window);
      window.__postCount = 0;
      window.fetch = async (url, opts = {}) => {
        if (opts.method === 'POST') {
          window.__postCount++;
          if (${failHeader}) opts = { ...opts, headers: { ...opts.headers, 'X-Test-Fail': '1' } };
          if (${delayMs} > 0) await new Promise((r) => setTimeout(r, ${delayMs}));
        }
        return real(url, opts);
      };
      return true;
    })()`);
  }

  postCount() {
    return this.eval('window.__postCount || 0');
  }

  async waitForText(id, pattern) {
    return waitFor(async () => {
      const t = await this.eval(`document.getElementById(${JSON.stringify(id)}).textContent`);
      return pattern.test(t) ? t : null;
    }, `#${id} to match ${pattern}`);
  }

  async waitForHidden(id) {
    return waitFor(async () => {
      const i = await this.info(id);
      return i && !i.visible;
    }, `#${id} hidden`);
  }

  async waitForVisible(id) {
    return waitFor(async () => {
      const i = await this.info(id);
      return i && i.visible;
    }, `#${id} visible`);
  }

  async close() {
    await this.cdp.send('Target.closeTarget', { targetId: this.targetId }).catch(() => {});
  }
}

// ---------- tests ----------

describe('users and access screen', () => {
  let cdp;
  let api;
  let page;

  before(async () => {
    await startBrowser();
    cdp = await Cdp.connect(cdpUrl);
  });

  after(() => {
    cdp?.close();
    browserProc?.kill();
  });

  beforeEach(async () => {
    api?.stop();
    api = await startApi();
    page = await Page.open(cdp, `${api.base}/`);
  });

  it('staging a change sends nothing and shows the pending change', async () => {
    await page.choose('role-u2', 'viewer');
    await page.waitForVisible('pending-u2');
    assert.match(await page.waitForText('pending-u2', /viewer/), /Not saved yet/);
    assert.equal((await page.info('save-u2')).disabled, false, 'Save enabled for staged change');
    assert.equal((await page.info('cancel-u2')).disabled, false, 'Discard enabled for staged change');
    assert.equal(await page.eval('document.querySelector("tr[data-user-id=\\"u2\\"]").classList.contains("is-pending")'), true);
    assert.deepEqual(await audit(api), [], 'no write reached the API');
    assert.equal(await page.eval('document.getElementById("status").textContent'), '');
  });

  it('Discard drops the staged change without a write', async () => {
    await page.choose('role-u2', 'viewer');
    await page.waitForVisible('pending-u2');
    await page.click('cancel-u2');
    await page.waitForHidden('pending-u2');
    assert.equal((await page.info('role-u2')).value, 'analyst', 'select reverts to committed role');
    assert.equal((await page.info('save-u2')).disabled, true);
    assert.deepEqual(await audit(api), []);
  });

  it('Save commits a non-privileged change and reports success', async () => {
    await page.choose('role-u2', 'viewer');
    await page.click('save-u2');
    assert.match(await page.waitForText('status', /Saved/), /bo@example\.test is now viewer/);
    await page.waitForHidden('pending-u2');
    assert.equal(await page.eval('document.getElementById("error").textContent'), '');
    const writes = await audit(api);
    assert.equal(writes.length, 1);
    assert.deepEqual([writes[0].user_id, writes[0].role, writes[0].version, writes[0].fail_header],
      ['u2', 'viewer', 1, false]);
    const users = await getJson(`${api.base}/api/users`);
    assert.equal(users.users.find((u) => u.id === 'u2').role, 'viewer');
  });

  it('confirmation is hidden for non-admin changes', async () => {
    await page.choose('role-u2', 'viewer');
    await page.waitForVisible('pending-u2');
    assert.equal((await page.info('confirm-u2')).visible, false);
  });

  it('granting admin requires an in-page confirmation before anything is sent', async () => {
    await page.choose('role-u1', 'admin');
    await page.waitForVisible('confirm-u1');
    assert.match(await page.eval('document.getElementById("confirm-text-u1").textContent'), /grants admin/);
    await page.click('save-u1');
    await page.waitForText('error', /Confirm/);
    assert.deepEqual(await audit(api), [], 'Save alone does not apply a privilege change');
    const yes = await page.eval('document.querySelector("#confirm-u1 [data-confirm=\\"yes\\"]") !== null');
    assert.equal(yes, true, 'confirm control carries data-confirm="yes"');
    await page.eval('document.querySelector("#confirm-u1 [data-confirm=\\"yes\\"]").click(), true');
    await page.waitForText('status', /Saved/);
    const writes = await audit(api);
    assert.equal(writes.length, 1);
    assert.equal(writes[0].role, 'admin');
  });

  it('removing admin is also privilege sensitive and can be backed out', async () => {
    await page.choose('role-u3', 'viewer');
    await page.waitForVisible('confirm-u3');
    assert.match(await page.eval('document.getElementById("confirm-text-u3").textContent'), /removes admin/);
    await page.click('cancel-u3');
    await page.waitForHidden('confirm-u3');
    assert.equal((await page.info('role-u3')).value, 'admin');
    assert.deepEqual(await audit(api), []);
  });

  it('in-flight submission shows loading, disables Save, and cannot be re-submitted', async () => {
    await page.wrapPostFetch({ delayMs: 900 });
    await page.choose('role-u2', 'viewer');
    await page.click('save-u2');
    await page.waitForVisible('loading-u2');
    const save = await page.info('save-u2');
    assert.equal(save.disabled, true, 'Save disabled while in flight');
    assert.equal((await page.info('role-u2')).disabled, true, 'select disabled while in flight');
    await page.click('save-u2'); // activation while disabled must do nothing
    await page.eval('document.getElementById("save-u2").click(), true');
    await page.waitForText('status', /Saved/);
    await page.waitForHidden('loading-u2');
    assert.equal(await page.postCount(), 1, 'only one POST was sent');
    assert.equal((await audit(api)).length, 1, 'only one write reached the API');
  });

  it('a failed save says so, keeps the staged change, and never claims success', async () => {
    await page.wrapPostFetch({ failHeader: true });
    await page.choose('role-u2', 'viewer');
    await page.click('save-u2');
    const err = await page.waitForText('error', /Save failed/);
    assert.match(err, /HTTP 500/);
    assert.match(err, /Nothing was changed/);
    assert.equal(await page.eval('document.getElementById("status").textContent'), '', 'no success text');
    assert.equal((await page.info('pending-u2')).visible, true, 'staged change still shown');
    assert.equal((await page.info('role-u2')).value, 'viewer', 'staged value still selected');
    assert.equal((await page.info('save-u2')).disabled, false, 'can retry');
    const writes = await audit(api);
    assert.equal(writes.length, 1);
    assert.equal(writes[0].fail_header, true);
    const users = await getJson(`${api.base}/api/users`);
    assert.equal(users.users.find((u) => u.id === 'u2').role, 'analyst', 'server state unchanged');
  });

  it('a stale version (HTTP 409) is surfaced and the change is not silently applied', async () => {
    await page.choose('role-u2', 'viewer');
    // Another administrator changes u2 after this page loaded (version 1 -> 2).
    const other = await apiPost(api, 'u2', { role: 'analyst', version: 1 });
    assert.equal(other.status, 200);
    await page.click('save-u2');
    const err = await page.waitForText('error', /Conflict/);
    assert.match(err, /NOT applied/);
    assert.equal(await page.eval('document.getElementById("status").textContent'), '');
    const writes = await audit(api);
    assert.equal(writes.length, 2);
    assert.equal(writes[1].version, 1);
    const users = await getJson(`${api.base}/api/users`);
    const u2 = users.users.find((u) => u.id === 'u2');
    assert.equal(u2.role, 'analyst');
    assert.equal(u2.version, 2);
    // A retry now uses the refreshed version and succeeds.
    await page.click('save-u2');
    await page.waitForText('status', /Saved/);
    assert.equal((await getJson(`${api.base}/api/users`)).users.find((u) => u.id === 'u2').role, 'viewer');
  });

  it('controls have accessible names and the status regions are live', async () => {
    const save = await page.info('save-u2');
    assert.match(save.label, /Save access level change for bo@example\.test/);
    const cancel = await page.info('cancel-u2');
    assert.match(cancel.label, /Discard access level change/);
    const select = await page.info('role-u2');
    assert.equal(select.label, 'Access level for bo@example.test');
    const status = await page.info('status');
    assert.equal(status.role, 'status');
    assert.equal(status.live, 'polite');
    const error = await page.info('error');
    assert.equal(error.role, 'alert');
    assert.ok(error.live, 'error region is live');
  });

  it('layout does not overflow a 390px viewport', async () => {
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true }, page.sid);
    await page.choose('role-u1', 'admin'); // exercise the widest state: pending + confirm
    await page.waitForVisible('confirm-u1');
    const over = await page.eval(`(() => {
      const vw = 390;
      const doc = document.documentElement;
      const offenders = [];
      for (const el of document.querySelectorAll('.wrap, .wrap *')) {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.right > vw + 0.5) offenders.push(el.tagName + (el.id ? '#' + el.id : ''));
      }
      return { scrollWidth: doc.scrollWidth, offenders };
    })()`);
    assert.ok(over.scrollWidth <= 390, `document scrollWidth ${over.scrollWidth} > 390`);
    assert.deepEqual(over.offenders, [], 'no element extends past 390px');
  });
});
