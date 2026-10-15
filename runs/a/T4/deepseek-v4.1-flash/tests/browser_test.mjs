#!/usr/bin/env node
// Browser-driven acceptance tests for the users-and-access screen.
//
// The screen is served by the real mock API (server.py) and driven inside lightpanda
// (headless Chromium-compatible browser exposing CDP) the way an administrator would:
// changing the dropdown, pressing Apply, confirming a privilege change, cancelling.
//
// The screen is loaded from the running server, so this exercises the delivered files
// (public/index.html, public/app.js, public/styles.css) exactly as shipped.
//
// Run: node tests/browser_test.mjs      (run_checks.sh runs it too)
// Exit code 0 = all checks passed.

import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import process from 'node:process';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// ------------------------------------------------------------------ plumbing --

async function freePort() {
  return await new Promise((resolve, reject) => {
    const srv = createServer();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

async function waitForHttp(url, { timeout = 10000, label = url } = {}) {
  const start = Date.now();
  let lastError = 'no attempt';
  while (Date.now() - start < timeout) {
    try {
      const response = await fetch(url);
      if (response.ok) return response;
      lastError = `HTTP ${response.status}`;
    } catch (err) {
      lastError = err.message;
    }
    await sleep(50);
  }
  throw new Error(`timed out waiting for ${label}: ${lastError}`);
}

class CDP {
  constructor(ws) {
    this.ws = ws;
    this.nextId = 0;
    this.pending = new Map();
    this.sessionId = null;
    ws.addEventListener('message', (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        if (msg.error) reject(new Error(`${msg.method || ''} ${JSON.stringify(msg.error)}`));
        else resolve(msg.result);
      }
    });
    ws.addEventListener('error', () => {
      for (const { reject } of this.pending.values()) reject(new Error('CDP socket error'));
      this.pending.clear();
    });
  }

  send(method, params = {}, sessionId = this.sessionId) {
    const id = ++this.nextId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      const message = { id, method, params };
      if (sessionId) message.sessionId = sessionId;
      this.ws.send(JSON.stringify(message));
    });
  }

  async evaluate(expression) {
    const result = await this.send('Runtime.evaluate', {
      expression,
      returnByValue: true,
      awaitPromise: true,
    });
    if (result.exceptionDetails) {
      throw new Error(`page threw: ${JSON.stringify(result.exceptionDetails).slice(0, 400)}`);
    }
    return result.result ? result.result.value : undefined;
  }

  close() {
    try { this.ws.close(); } catch (err) { /* already closed */ }
  }
}

async function connectCDP(cdpHttpUrl) {
  const version = await (await fetch(`${cdpHttpUrl}/json/version`)).json();
  const ws = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    ws.addEventListener('open', resolve, { once: true });
    ws.addEventListener('error', () => reject(new Error('cannot connect to lightpanda CDP')), { once: true });
  });
  const cdp = new CDP(ws);
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  const { sessionId } = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
  cdp.sessionId = sessionId;
  await cdp.send('Runtime.enable');
  await cdp.send('Page.enable');
  return cdp;
}

// ------------------------------------------------------------- page helpers ---

let cdp;
let APP = 'http://127.0.0.1:0';

const evaluate = (expression) => cdp.evaluate(expression);

async function until(expression, { timeout = 6000, interval = 40, label } = {}) {
  const start = Date.now();
  let last;
  while (Date.now() - start < timeout) {
    last = await evaluate(expression);
    if (last) return last;
    await sleep(interval);
  }
  throw new Error(`timed out waiting for ${label || expression} (last value: ${JSON.stringify(last)})`);
}

async function reload() {
  await cdp.send('Page.navigate', { url: `${APP}/` });
  await until(`document.querySelectorAll('#users-table tbody tr').length > 0`, { label: 'rows after load' });
  await evaluate(`document.readyState === 'complete' || true`);
}

const $ = (id) => `document.getElementById(${JSON.stringify(id)})`;

async function stageRole(userId, role) {
  return await evaluate(`(() => {
    const select = document.getElementById('role-${userId}');
    if (!select) throw new Error('no select for ${userId}');
    select.value = ${JSON.stringify(role)};
    select.dispatchEvent(new Event('change', { bubbles: true }));
    return select.value;
  })()`);
}

async function click(selector) {
  return await evaluate(`(() => {
    const el = document.querySelector(${JSON.stringify(selector)});
    if (!el) throw new Error('missing element ' + ${JSON.stringify(selector)});
    el.click();
    return true;
  })()`);
}

// Snapshot of everything one assertion group needs, collected in a single page call.
async function snapshot(userId) {
  return await evaluate(`(() => {
    const vis = (el) => !!el && getComputedStyle(el).display !== 'none' && el.hidden !== true
      && el.getAttribute('aria-hidden') !== 'true';
    const byId = (id) => document.getElementById(id);
    const pending = byId('pending-${userId}');
    const loading = byId('loading-${userId}');
    const confirm = byId('confirm-${userId}');
    const confirmYes = document.querySelector('#confirm-${userId} [data-confirm="yes"]');
    const select = byId('role-${userId}');
    const save = byId('save-${userId}');
    const cancel = byId('cancel-${userId}');
    return {
      selectValue: select ? select.value : null,
      selectLabel: select ? select.getAttribute('aria-label') : null,
      selectOptions: select ? Array.from(select.options).map((o) => o.value) : null,
      selectDisabled: select ? select.disabled : null,
      pending: pending ? { present: true, visible: vis(pending), text: pending.textContent } : { present: false },
      loading: loading ? { present: true, visible: vis(loading), text: loading.textContent } : { present: false },
      confirm: confirm ? { present: true, visible: vis(confirm), text: confirm.textContent } : { present: false },
      confirmYes: confirmYes ? { present: true, label: confirmYes.getAttribute('aria-label') } : { present: false },
      save: save ? { present: true, disabled: save.disabled, ariaDisabled: save.getAttribute('aria-disabled'),
                     ariaLabel: save.getAttribute('aria-label'), text: save.textContent } : { present: false },
      cancel: cancel ? { present: true, disabled: cancel.disabled, ariaLabel: cancel.getAttribute('aria-label'),
                         text: cancel.textContent } : { present: false },
      status: (byId('status') || {}).textContent ?? null,
      statusRole: byId('status') ? byId('status').getAttribute('role') : null,
      statusLive: byId('status') ? byId('status').getAttribute('aria-live') : null,
      error: (byId('error') || {}).textContent ?? null,
      errorRole: byId('error') ? byId('error').getAttribute('role') : null,
      errorLive: byId('error') ? byId('error').getAttribute('aria-live') : null,
    };
  })()`);
}

// ------------------------------------------------------------------- assets ---

const apiUsers = async () => (await (await fetch(`${APP}/api/users`)).json()).users;
const apiAudit = async () => (await (await fetch(`${APP}/api/audit`)).json()).writes;

async function pickNonAdminUser() {
  const list = await apiUsers();
  const user = list.find((entry) => entry.role !== 'admin');
  if (!user) throw new Error('suite needs a non-admin user; none found');
  return user;
}

async function pickAdminUser() {
  const list = await apiUsers();
  const user = list.find((entry) => entry.role === 'admin');
  if (!user) throw new Error('suite needs an admin user; none found');
  return user;
}

// a role that is not admin, different from the given one
function otherNonAdminRole(role) {
  return role === 'viewer' ? 'analyst' : 'viewer';
}

// -------------------------------------------------------------------- runner --

const tests = [];
const test = (name, fn) => tests.push({ name, fn });

function check(condition, message) {
  if (!condition) throw new Error(message);
}

const isNonEmpty = (value) => typeof value === 'string' && value.trim().length > 0;

// --------------------------------------------------------------------- tests --

test('screen renders the frozen DOM contract, idle (nothing staged)', async () => {
  await reload();
  const users = await apiUsers();
  const state = await evaluate(`(() => {
    const rows = Array.from(document.querySelectorAll('#users-table tbody tr'));
    return {
      role: (document.getElementById('status') || {}).getAttribute
        ? document.getElementById('status').getAttribute('role') : null,
      live: document.getElementById('status').getAttribute('aria-live'),
      errorRole: document.getElementById('error').getAttribute('role'),
      errorLive: document.getElementById('error').getAttribute('aria-live'),
      rowCount: rows.length,
      ids: rows.map((r) => r.dataset.userId),
      controls: rows.map((r) => {
        const id = r.dataset.userId;
        const select = document.getElementById('role-' + id);
        const save = document.getElementById('save-' + id);
        const cancel = document.getElementById('cancel-' + id);
        return {
          id,
          selectTag: select ? select.tagName : null,
          selectValue: select ? select.value : null,
          selectLabel: select ? select.getAttribute('aria-label') : null,
          options: select ? Array.from(select.options).map((o) => o.value) : [],
          saveTag: save ? save.tagName : null,
          saveText: save ? save.textContent : null,
          saveLabel: save ? save.getAttribute('aria-label') : null,
          saveDisabled: save ? save.disabled : null,
          cancelTag: cancel ? cancel.tagName : null,
          cancelText: cancel ? cancel.textContent : null,
          cancelLabel: cancel ? cancel.getAttribute('aria-label') : null,
          pending: !!document.getElementById('pending-' + id),
          loading: !!document.getElementById('loading-' + id),
          confirm: !!document.getElementById('confirm-' + id),
        };
      }),
    };
  })()`);

  check(state.rowCount === users.length, `expected ${users.length} rows, saw ${state.rowCount}`);
  for (const user of users) {
    check(state.ids.includes(user.id), `no row for ${user.id} (data-user-id)`);
    const control = state.controls.find((c) => c.id === user.id);
    check(control.selectTag === 'SELECT', `#role-${user.id} is not a <select>`);
    check(control.options.join(',') === 'viewer,analyst,admin', `#role-${user.id} options are ${control.options.join(',')}`);
    check(control.selectValue === user.role, `#role-${user.id} shows ${control.selectValue}, server says ${user.role}`);
    check(isNonEmpty(control.selectLabel), `#role-${user.id} has no accessible name`);
    check(control.saveTag === 'BUTTON', `#save-${user.id} is not a <button>`);
    check(isNonEmpty(control.saveText), `#save-${user.id} has no visible label`);
    check(isNonEmpty(control.saveLabel), `#save-${user.id} has no accessible name (aria-label)`);
    check(control.saveDisabled === true, `#save-${user.id} must be inactive while nothing is staged`);
    check(control.cancelTag === 'BUTTON', `#cancel-${user.id} is not a <button>`);
    check(isNonEmpty(control.cancelLabel), `#cancel-${user.id} has no accessible name (aria-label)`);
    check(!control.pending, `#pending-${user.id} must not exist while nothing is staged`);
    check(!control.loading, `#loading-${user.id} must not exist while idle`);
    check(!control.confirm, `#confirm-${user.id} must not exist while nothing is staged`);
  }
  check(state.role === 'status', `#status role is ${state.role}, expected status`);
  check(state.live === 'polite', `#status aria-live is ${state.live}, expected polite`);
  check(state.errorRole === 'alert' || state.errorRole === 'status',
    `#error role is ${state.errorRole}, expected a live-region role`);
  check(isNonEmpty(state.errorLive), '#error must carry an explicit aria-live attribute');
});

test('changing the dropdown stages locally, sends nothing, and is visibly pending', async () => {
  await reload();
  const user = await pickNonAdminUser();
  const target = otherNonAdminRole(user.role);
  const writesBefore = (await apiAudit()).length;

  await stageRole(user.id, target);
  const snap = await snapshot(user.id);

  check(snap.selectValue === target, `select shows ${snap.selectValue} after staging ${target}`);
  check(snap.pending.present, `#pending-${user.id} must be present while a change is staged`);
  check(snap.pending.visible, `#pending-${user.id} must be visible while a change is staged`);
  check(snap.pending.text.includes(target), `#pending-${user.id} text "${snap.pending.text}" does not mention ${target}`);
  check(!snap.loading.present, '#loading must not appear for a staged (unsent) change');
  check(snap.save.disabled === false, `#save-${user.id} must be activatable once a change is staged (${snap.save.disabled})`);
  check(snap.status === '', `#status must stay empty while a change is only staged, saw "${snap.status}"`);

  await sleep(400); // give any stray request time to land
  const writesAfter = await apiAudit();
  check(writesAfter.length === writesBefore,
    `staging must not send anything: writes went ${writesBefore} -> ${writesAfter.length}`);
  const server = (await apiUsers()).find((entry) => entry.id === user.id);
  check(server.role === user.role, `server role changed on staging: ${user.role} -> ${server.role}`);

  // A staged change that is set back to the persisted value stages nothing.
  await stageRole(user.id, user.role);
  const back = await snapshot(user.id);
  check(!back.pending.present, `#pending-${user.id} must disappear when the dropdown is back on the stored value`);
  check(back.save.disabled === true, `#save-${user.id} must be inactive again with nothing staged`);
});

test('Apply commits the staged change once and reports success', async () => {
  await reload();
  const user = await pickNonAdminUser();
  const target = otherNonAdminRole(user.role);
  const writesBefore = (await apiAudit()).length;

  await stageRole(user.id, target);
  await click(`#save-${user.id}`);
  await until(`(document.getElementById('status') || {}).textContent && document.getElementById('status').textContent.length > 0`,
    { label: '#status after apply' });
  await until(`!document.getElementById('loading-${user.id}')`, { label: 'loading badge cleared' });

  const snap = await snapshot(user.id);
  check(snap.status.includes('Saved'), `#status does not report success: "${snap.status}"`);
  check(snap.status.includes(target), `#status does not mention the applied role: "${snap.status}"`);
  check(snap.error === '', `#error must stay empty on success, saw "${snap.error}"`);
  check(!snap.pending.present, `#pending-${user.id} must be gone once the change is applied`);
  check(!snap.loading.present, `#loading-${user.id} must be gone once the request finished`);
  check(snap.save.disabled === true, `#save-${user.id} must be inactive again after applying`);
  check(snap.selectValue === target, `select should show the applied role, saw ${snap.selectValue}`);

  const writes = await apiAudit();
  check(writes.length === writesBefore + 1, `expected exactly 1 write, saw ${writes.length - writesBefore}`);
  const write = writes[writes.length - 1];
  check(write.user_id === user.id && write.role === target,
    `audit recorded ${JSON.stringify(write)}, expected user ${user.id} -> ${target}`);
  check(write.version === user.version, `audit sent version ${write.version}, expected the version read (${user.version})`);

  const server = (await apiUsers()).find((entry) => entry.id === user.id);
  check(server.role === target, `server role is ${server.role}, expected ${target}`);
  check(server.version === user.version + 1, `server version is ${server.version}, expected ${user.version + 1}`);
});

test('Cancel discards the staged change without touching the API', async () => {
  await reload();
  const user = await pickNonAdminUser();
  const target = otherNonAdminRole(user.role);
  const writesBefore = (await apiAudit()).length;

  await stageRole(user.id, target);
  check((await snapshot(user.id)).pending.present, 'precondition: a change must be staged');
  await click(`#cancel-${user.id}`);

  const snap = await snapshot(user.id);
  check(!snap.pending.present, `#pending-${user.id} must be gone after Cancel`);
  check(snap.selectValue === user.role, `select must show the stored role ${user.role} after Cancel, saw ${snap.selectValue}`);
  check(snap.save.disabled === true, '#save must be inactive after Cancel');
  check(!snap.status.includes('Saved'), `#status must not claim a save after Cancel: "${snap.status}"`);

  await sleep(300);
  check((await apiAudit()).length === writesBefore, 'Cancel must not send anything to the API');
  const server = (await apiUsers()).find((entry) => entry.id === user.id);
  check(server.role === user.role && server.version === user.version, 'Cancel must not change the record');
});

test('granting admin requires an explicit in-page confirmation', async () => {
  await reload();
  const user = await pickNonAdminUser();      // viewer or analyst
  const writesBefore = (await apiAudit()).length;

  await stageRole(user.id, 'admin');
  let snap = await snapshot(user.id);
  check(snap.confirm.present, `#confirm-${user.id} must appear when admin is granted`);
  check(snap.confirm.visible, `#confirm-${user.id} must be visible`);
  check(snap.confirmYes.present, `#confirm-${user.id} must carry a [data-confirm="yes"] control`);
  check(isNonEmpty(snap.confirmYes.label), 'the confirmation control needs an accessible name');
  check(snap.save.disabled === true, `#save-${user.id} must be inactive until the change is confirmed`);

  // pressing Apply before confirming must not send anything
  await click(`#save-${user.id}`);
  await sleep(400);
  check((await apiAudit()).length === writesBefore,
    'applying an unconfirmed privilege change must not send anything');

  await click(`#confirm-${user.id} [data-confirm="yes"]`);
  snap = await snapshot(user.id);
  check(!snap.confirm.present, `#confirm-${user.id} must disappear once confirmed`);
  check(snap.save.disabled === false, `#save-${user.id} must become activatable after confirming`);
  check(snap.pending.present, `#pending-${user.id} must still be staged after confirming`);

  await click(`#save-${user.id}`);
  await until(`(document.getElementById('status') || {}).textContent.includes('Saved')`, { label: 'success after confirmed apply' });
  const server = (await apiUsers()).find((entry) => entry.id === user.id);
  check(server.role === 'admin', `server role is ${server.role}, expected admin`);
  const writes = await apiAudit();
  check(writes.length === writesBefore + 1, `expected exactly 1 write, saw ${writes.length - writesBefore}`);
  check(writes[writes.length - 1].role === 'admin', 'the applied role must be admin');
});

test('removing admin requires an explicit in-page confirmation', async () => {
  await reload();
  const user = await pickAdminUser();
  const writesBefore = (await apiAudit()).length;

  await stageRole(user.id, 'viewer');
  let snap = await snapshot(user.id);
  check(snap.confirm.present, `#confirm-${user.id} must appear when admin is removed`);
  check(snap.confirmYes.present, `#confirm-${user.id} must carry a [data-confirm="yes"] control`);
  check(snap.confirm.text.includes('admin'), `confirmation text should mention admin: "${snap.confirm.text}"`);
  check(snap.save.disabled === true, `#save-${user.id} must be inactive until the removal is confirmed`);

  await click(`#save-${user.id}`);
  await sleep(400);
  check((await apiAudit()).length === writesBefore, 'an unconfirmed admin removal must not send anything');

  await click(`#confirm-${user.id} [data-confirm="yes"]`);
  snap = await snapshot(user.id);
  check(!snap.confirm.present, 'the confirmation panel must disappear once confirmed');
  check(snap.save.disabled === false, '#save must be activatable after confirming');

  await click(`#save-${user.id}`);
  await until(`(document.getElementById('status') || {}).textContent.includes('Saved')`, { label: 'success after confirmed removal' });
  const server = (await apiUsers()).find((entry) => entry.id === user.id);
  check(server.role === 'viewer', `server role is ${server.role}, expected viewer`);
  check((await apiAudit()).length === writesBefore + 1, 'exactly one write expected for the removal');
});

test('loading state is visible in flight and the apply control cannot be activated twice', async () => {
  await reload();
  const user = await pickNonAdminUser();
  const target = otherNonAdminRole(user.role);
  const writesBefore = (await apiAudit()).length;

  // slow the submission down so the in-flight state can be observed
  await evaluate(`(() => {
    window.__realFetch = window.__realFetch || window.fetch;
    window.fetch = (url, opts) => new Promise((resolve, reject) => {
      setTimeout(() => window.__realFetch(url, opts).then(resolve, reject), 1200);
    });
    return true;
  })()`);

  await stageRole(user.id, target);

  // one page call: press Apply, then look at the DOM in the same tick
  const inFlight = await evaluate(`(() => {
    const save = document.getElementById('save-${user.id}');
    save.click();
    const loading = document.getElementById('loading-${user.id}');
    const row = document.querySelector('tr[data-user-id="${user.id}"]');
    const vis = (el) => !!el && getComputedStyle(el).display !== 'none';
    const snapshot = {
      loadingPresent: !!loading,
      loadingVisible: vis(loading),
      loadingText: loading ? loading.textContent : null,
      loadingRole: loading ? loading.getAttribute('role') : null,
      saveDisabled: document.getElementById('save-${user.id}').disabled,
      saveAriaDisabled: document.getElementById('save-${user.id}').getAttribute('aria-disabled'),
      rowBusy: row ? row.getAttribute('aria-busy') : null,
    };
    // try hard to submit again while the first request is in flight
    document.getElementById('save-${user.id}').click();
    const again = document.getElementById('save-${user.id}');
    again.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return snapshot;
  })()`);

  check(inFlight.loadingPresent, `#loading-${user.id} must be present while the request is in flight`);
  check(inFlight.loadingVisible, `#loading-${user.id} must be visible while the request is in flight`);
  check(isNonEmpty(inFlight.loadingText), '#loading-<id> must announce something to assistive tech');
  check(inFlight.loadingRole === 'status', `#loading-${user.id} role is ${inFlight.loadingRole}, expected status`);
  check(inFlight.saveDisabled === true, `#save-${user.id} must be disabled while the request is in flight`);
  check(inFlight.saveAriaDisabled === 'true', `#save-${user.id} must report aria-disabled while in flight`);

  await until(`(document.getElementById('status') || {}).textContent.includes('Saved')`, { timeout: 8000, label: 'success after slowed apply' });
  await until(`!document.getElementById('loading-${user.id}')`, { label: 'loading badge cleared' });

  const writes = await apiAudit();
  check(writes.length === writesBefore + 1,
    `the in-flight apply must be submitted exactly once, saw ${writes.length - writesBefore} writes`);
  const server = (await apiUsers()).find((entry) => entry.id === user.id);
  check(server.role === target, `server role is ${server.role}, expected ${target}`);
});

test('a failed submission is reported as a failure and never drops the staged change', async () => {
  await reload();
  const user = await pickNonAdminUser();
  const target = otherNonAdminRole(user.role);
  const writesBefore = (await apiAudit()).length;

  // make the API answer 500 for every POST (X-Test-Fail: 1), the way a broken
  // upstream behaves; the app must not report success.
  await evaluate(`(() => {
    const raw = window.fetch;
    window.fetch = (url, opts) => {
      const o = Object.assign({}, opts || {});
      const headers = Object.assign({}, o.headers || {});
      headers['X-Test-Fail'] = '1';
      o.headers = headers;
      return raw(url, o);
    };
    return true;
  })()`);

  await stageRole(user.id, target);
  await click(`#save-${user.id}`);
  await until(`(document.getElementById('error') || {}).textContent.length > 0`, { label: '#error after failure' });

  let snap = await snapshot(user.id);
  check(!snap.status.includes('Saved'), `#status must not claim success on a failure: "${snap.status}"`);
  check(snap.status === '', `#status must be empty on a failure, saw "${snap.status}"`);
  check(/500|fail|could not save/i.test(snap.error), `#error should explain the failure, saw "${snap.error}"`);
  check(snap.pending.present && snap.pending.visible,
    `#pending-${user.id} must survive a failed submission (staged change kept)`);
  check(snap.selectValue === target, `the staged value must survive a failure, saw ${snap.selectValue}`);
  check(snap.save.disabled === false, '#save must stay available to retry');
  check(!snap.loading.present, `#loading-${user.id} must be cleared after a failure`);
  const serverAfterFailure = (await apiUsers()).find((entry) => entry.id === user.id);
  check(serverAfterFailure.role === user.role, 'the failed submission must not change the record');
  const failedWrites = await apiAudit();
  check(failedWrites.length === writesBefore + 1 && failedWrites[failedWrites.length - 1].fail_header === true,
    'the rejected attempt should be the only recorded write');

  // with the API healthy again the kept staged change can still be applied
  await reload();
  await stageRole(user.id, target);
  await click(`#save-${user.id}`);
  await until(`(document.getElementById('status') || {}).textContent.includes('Saved')`, { label: 'retry after failure' });
  const server = (await apiUsers()).find((entry) => entry.id === user.id);
  check(server.role === target, `retry should apply ${target}, server says ${server.role}`);
});

test('a stale-version 409 is surfaced to the administrator', async () => {
  await reload();
  const user = await pickNonAdminUser();
  const target = otherNonAdminRole(user.role);
  const writesBefore = (await apiAudit()).length;

  // someone else changes the record after this page was loaded: same role, new version
  const conflict = await fetch(`${APP}/api/users/${user.id}/role`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role: user.role, version: user.version }),
  });
  check(conflict.status === 200, `precondition: the concurrent write should succeed, got ${conflict.status}`);

  await stageRole(user.id, target);
  await click(`#save-${user.id}`);
  await until(`(document.getElementById('error') || {}).textContent.length > 0`, { label: '#error after conflict' });

  const snap = await snapshot(user.id);
  check(snap.status === '', `#status must not claim success on a conflict: "${snap.status}"`);
  check(/conflict|stale|changed by someone else/i.test(snap.error),
    `#error should surface the conflict, saw "${snap.error}"`);
  check(snap.pending.present && snap.pending.visible,
    `#pending-${user.id} must survive a 409 (staged change kept)`);
  check(snap.selectValue === target, 'the staged value must survive a 409');
  check(!snap.loading.present, '#loading must be cleared after the conflict');

  const writes = await apiAudit();
  check(writes.length === writesBefore + 2, `expected the concurrent write plus the rejected one (${writes.length - writesBefore})`);

  // the administrator can review the refreshed record and apply deliberately
  await click(`#save-${user.id}`);
  await until(`(document.getElementById('status') || {}).textContent.includes('Saved')`, { label: 'apply after conflict' });
  const server = (await apiUsers()).find((entry) => entry.id === user.id);
  check(server.role === target, `after resolving the conflict the role should be ${target}, server says ${server.role}`);
  check((await apiAudit()).length === writesBefore + 3, 'the deliberate retry should be recorded');
});

test('status and error are distinct live regions and every control is named', async () => {
  await reload();
  const user = await pickNonAdminUser();
  const shape = await evaluate(`(() => {
    const status = document.getElementById('status');
    const error = document.getElementById('error');
    const controls = Array.from(document.querySelectorAll('#users-table button, #users-table select'));
    return {
      statusTag: status.tagName,
      statusRole: status.getAttribute('role'),
      statusLive: status.getAttribute('aria-live'),
      errorRole: error.getAttribute('role'),
      errorLive: error.getAttribute('aria-live'),
      errorTag: error.tagName,
      unnamed: controls.filter((el) => {
        const label = el.getAttribute('aria-label')
          || (el.textContent || '').trim()
          || el.getAttribute('title');
        return !label;
      }).map((el) => el.id || el.tagName),
      distinctRegions: status !== error,
    };
  })()`);
  check(shape.statusRole === 'status', `#status role is ${shape.statusRole}`);
  check(shape.statusLive === 'polite', `#status aria-live is ${shape.statusLive}`);
  check(['status', 'alert', 'log'].includes(shape.errorRole), `#error role is ${shape.errorRole}`);
  check(isNonEmpty(shape.errorLive), '#error must carry an explicit aria-live attribute');
  check(shape.distinctRegions, '#status and #error must be different regions');
  check(shape.unnamed.length === 0, `controls without an accessible name: ${shape.unnamed.join(', ')}`);

  // the confirmation control only exists once a privilege change is staged, and is named too
  await stageRole(user.id, 'admin');
  const confirmShape = await evaluate(`(() => {
    const yes = document.querySelector('#confirm-${user.id} [data-confirm="yes"]');
    const box = document.getElementById('confirm-${user.id}');
    return {
      yesPresent: !!yes,
      yesLabel: yes ? (yes.getAttribute('aria-label') || yes.textContent) : null,
      boxLabel: box ? (box.getAttribute('aria-label') || box.getAttribute('aria-labelledby')) : null,
      boxRole: box ? box.getAttribute('role') : null,
    };
  })()`);
  check(confirmShape.yesPresent, 'the confirmation control must exist for a privilege change');
  check(isNonEmpty(confirmShape.yesLabel), 'the confirmation control must have an accessible name');
  check(isNonEmpty(confirmShape.boxLabel), '#confirm-<id> must have an accessible name');
  check(isNonEmpty(confirmShape.boxRole), '#confirm-<id> should expose a role');
  await click(`#cancel-${user.id}`);
});

test('narrow (390px) viewport: structure that cannot overflow the viewport', async () => {
  // lightpanda honours Emulation.setDeviceMetricsOverride for window.innerWidth and
  // matchMedia, but its layout engine does not resolve percentage widths, so a
  // scrollWidth measurement there is not meaningful (it reports the default 1920 for
  // any page). The layout invariants that keep the screen inside 390px are asserted
  // here; the measured no-overflow check runs in a real Chromium (see notes.md).
  await cdp.send('Emulation.setDeviceMetricsOverride', {
    width: 390, height: 844, deviceScaleFactor: 1, mobile: true,
  });
  await reload();
  const viewport = await evaluate(`(() => ({
    innerWidth: window.innerWidth,
    narrow: window.matchMedia('(max-width: 560px)').matches,
    hasViewportMeta: !!document.querySelector('meta[name="viewport"]'),
    content: (document.querySelector('meta[name="viewport"]') || {}).content || null,
  }))()`);
  check(viewport.innerWidth === 390, `emulated width is ${viewport.innerWidth}`);
  check(viewport.narrow, 'the stacked (narrow) stylesheet branch must match at 390px');
  check(viewport.hasViewportMeta, 'index.html must declare a viewport meta tag');
  check(/width=device-width/.test(viewport.content || ''), `viewport meta content is "${viewport.content}"`);

  const css = readFileSync(path.join(ROOT, 'public/styles.css'), 'utf8');
  const fixedWidths = [...css.matchAll(/(?:^|[;{\s])(?:min-)?width\s*:\s*(\d+(?:\.\d+)?)px/g)]
    .map((match) => Number(match[1]))
    .filter((value) => value > 390);
  check(fixedWidths.length === 0,
    `styles.css must not pin a width above the 390px viewport, found: ${fixedWidths.join(', ')}px`);
  check(/max-width\s*:\s*560px/.test(css), 'styles.css must keep a narrow-viewport media query');
  check(/overflow-wrap/.test(css), 'styles.css should allow long values (emails) to wrap');
  check(/max-width:\s*100%/.test(css), 'styles.css should bound flexible elements to their container');

  // nothing in the rendered page carries an inline width that overflows 390px
  const inline = await evaluate(`(() => {
    return Array.from(document.querySelectorAll('[style*="width"]'))
      .map((el) => el.getAttribute('style'))
      .filter((style) => {
        const m = style.match(/width\\s*:\\s*(\\d+)px/);
        return m && Number(m[1]) > 390;
      });
  })()`);
  check(inline.length === 0, `elements with an overflowing inline width: ${inline.join(' | ')}`);
  await cdp.send('Emulation.clearDeviceMetricsOverride');
});

// ---------------------------------------------------------------------- main --

let serverProc;
let browserProc;

async function main() {
  const appPort = await freePort();
  const cdpPort = await freePort();
  APP = `http://127.0.0.1:${appPort}`;

  serverProc = spawn('python3', [path.join(ROOT, 'server.py'), String(appPort)], {
    cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'],
  });
  await waitForHttp(`${APP}/api/users`, { label: 'mock API' });

  browserProc = spawn('lightpanda', ['serve', '--host', '127.0.0.1', '--port', String(cdpPort)], {
    cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'],
  });
  const cdpHttp = `http://127.0.0.1:${cdpPort}`;
  await waitForHttp(`${cdpHttp}/json/version`, { label: 'lightpanda CDP' });
  cdp = await connectCDP(cdpHttp);

  let failures = 0;
  console.log(`browser_test.mjs: ${tests.length} tests against ${APP} (lightpanda CDP on ${cdpPort})`);
  for (let index = 0; index < tests.length; index += 1) {
    const { name, fn } = tests[index];
    const started = Date.now();
    try {
      await fn();
      console.log(`ok ${index + 1} - ${name} (${Date.now() - started}ms)`);
    } catch (err) {
      failures += 1;
      console.log(`not ok ${index + 1} - ${name}`);
      console.log(`  ${String(err && err.message ? err.message : err).split('\n').join('\n  ')}`);
    }
  }
  console.log(`browser_test.mjs: ${tests.length - failures}/${tests.length} passed`);
  return failures;
}

let exitCode = 1;
try {
  exitCode = (await main()) === 0 ? 0 : 1;
} catch (err) {
  console.error('browser_test.mjs: harness error:', err && err.stack ? err.stack : err);
  exitCode = 1;
} finally {
  if (cdp) cdp.close();
  for (const proc of [browserProc, serverProc]) {
    if (proc && !proc.killed) {
      try { proc.kill('SIGKILL'); } catch (err) { /* already gone */ }
    }
  }
  await sleep(200);
}
process.exit(exitCode);
