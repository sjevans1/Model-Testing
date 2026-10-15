// Browser-driven checks for the access screen. Drives lightpanda over CDP.
// Run: node tests/browser_access.mjs   (needs `lightpanda` on PATH and Node >= 22)
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { setTimeout as sleep } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const failures = [];
let passed = 0;

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.unref();
    srv.on('error', reject);
    srv.listen(0, '127.0.0.1', () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

async function waitFor(url, tries = 100) {
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(url);
      if (r.ok) return;
    } catch { /* not up yet */ }
    await sleep(100);
  }
  throw new Error(`timed out waiting for ${url}`);
}

class Cdp {
  constructor(wsUrl) {
    this.ws = new WebSocket(wsUrl);
    this.nextId = 1;
    this.pending = new Map();
    this.ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? reject(new Error(`${msg.error.message}`)) : resolve(msg.result);
      }
    });
  }
  open() {
    return new Promise((resolve, reject) => {
      this.ws.addEventListener('open', resolve, { once: true });
      this.ws.addEventListener('error', reject, { once: true });
    });
  }
  send(method, params = {}, sessionId) {
    const id = this.nextId++;
    const payload = { id, method, params };
    if (sessionId) payload.sessionId = sessionId;
    this.ws.send(JSON.stringify(payload));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }
}

async function main() {
  const cdpPort = await freePort();
  const apiPort = await freePort();

  const lp = spawn('lightpanda', ['serve', '--host', '127.0.0.1', '--port', String(cdpPort)], {
    stdio: 'ignore',
  });
  // server.py truncates writes.log on start, so a restart gives each scenario fresh state.
  let apiProc = null;
  const restartApi = async () => {
    if (apiProc) {
      const exited = new Promise((resolve) => apiProc.once('exit', resolve));
      apiProc.kill();
      await exited;
    }
    apiProc = spawn('python3', [path.join(ROOT, 'server.py'), String(apiPort)], {
      cwd: ROOT,
      stdio: 'ignore',
    });
    await waitFor(`http://127.0.0.1:${apiPort}/api/users`);
  };

  let cdp;
  let session;
  try {
    await waitFor(`http://127.0.0.1:${cdpPort}/json/version`);
    await restartApi();

    const version = await (await fetch(`http://127.0.0.1:${cdpPort}/json/version`)).json();
    cdp = new Cdp(version.webSocketDebuggerUrl);
    await cdp.open();

    const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
    const attached = await cdp.send('Target.attachToTarget', { targetId, flatten: true });
    session = attached.sessionId;
    const send = (m, p) => cdp.send(m, p, session);

    const evaluate = async (expression) => {
      const res = await send('Runtime.evaluate', {
        expression,
        returnByValue: true,
        awaitPromise: true,
      });
      if (res.exceptionDetails) {
        throw new Error(`page error: ${res.exceptionDetails.exception?.description ?? res.exceptionDetails.text}`);
      }
      return res.result.value;
    };

    async function openPage(viewportWidth = 1280) {
      await send('Page.navigate', { url: `http://127.0.0.1:${apiPort}/` });
      await sleep(300);
      await evaluate(`new Promise((resolve) => {
        const deadline = Date.now() + 5000;
        (function check() {
          if (document.querySelector('#users-table tbody tr[data-user-id="u3"]') || Date.now() > deadline) return resolve(true);
          setTimeout(check, 50);
        })();
      })`);
      if (viewportWidth !== 1280) {
        await send('Emulation.setDeviceMetricsOverride', {
          width: viewportWidth, height: 800, deviceScaleFactor: 1, mobile: true,
        });
      }
    }

    const audit = async () => {
      const r = await fetch(`http://127.0.0.1:${apiPort}/api/audit`);
      return (await r.json()).writes;
    };
    const users = async () => (await (await fetch(`http://127.0.0.1:${apiPort}/api/users`)).json()).users;

    const scenarios = {
      'changing the dropdown stages a change and sends nothing': async () => {
        await openPage();
        await evaluate(`(() => {
          const s = document.getElementById('role-u2');
          s.value = 'viewer'; s.dispatchEvent(new Event('change'));
        })()`);
        const state = await evaluate(`({
          pendingVisible: !document.getElementById('pending-u2').hidden,
          pendingText: document.getElementById('pending-u2').textContent,
          saveDisabled: document.getElementById('save-u2').disabled,
          cancelDisabled: document.getElementById('cancel-u2').disabled,
          confirmVisible: !document.getElementById('confirm-u2').hidden,
        })`);
        assert(state.pendingVisible, 'pending region should be visible after staging');
        assert(state.pendingText.includes('Not saved'), `pending text: ${state.pendingText}`);
        assert(!state.saveDisabled, 'Apply should be enabled while staged');
        assert(!state.cancelDisabled, 'Discard should be enabled while staged');
        assert(!state.confirmVisible, 'non-admin change must not need confirmation');
        const writes = await audit();
        assert(writes.length === 0, `staging must not write, audit has ${writes.length}`);
      },

      'Discard reverts the staged change without writing': async () => {
        await openPage();
        await evaluate(`(() => {
          const s = document.getElementById('role-u2');
          s.value = 'viewer'; s.dispatchEvent(new Event('change'));
          document.getElementById('cancel-u2').click();
        })()`);
        const state = await evaluate(`({
          select: document.getElementById('role-u2').value,
          pendingHidden: document.getElementById('pending-u2').hidden,
        })`);
        assert(state.select === 'analyst', `select should revert to analyst, got ${state.select}`);
        assert(state.pendingHidden, 'pending should be hidden after discard');
        assert((await audit()).length === 0, 'discard must not write');
      },

      'Apply commits a non-admin change and reports success distinctly': async () => {
        await openPage();
        await evaluate(`(() => {
          const s = document.getElementById('role-u2');
          s.value = 'viewer'; s.dispatchEvent(new Event('change'));
          document.getElementById('save-u2').click();
        })()`);
        await sleep(400);
        const status = await evaluate(`document.getElementById('status').textContent`);
        const error = await evaluate(`document.getElementById('error').textContent`);
        assert(status.startsWith('Saved'), `status should announce success: ${status}`);
        assert(error === '', `error should be empty on success: ${error}`);
        const writes = await audit();
        assert(writes.length === 1 && writes[0].role === 'viewer' && writes[0].user_id === 'u2',
          `expected one write u2->viewer, got ${JSON.stringify(writes)}`);
        const u2 = (await users()).find((u) => u.id === 'u2');
        assert(u2.role === 'viewer', 'server should now have viewer');
      },

      'admin grant requires in-page confirmation before any write': async () => {
        await openPage();
        await evaluate(`(() => {
          const s = document.getElementById('role-u1');
          s.value = 'admin'; s.dispatchEvent(new Event('change'));
        })()`);
        const shown = await evaluate(`!document.getElementById('confirm-u1').hidden`);
        assert(shown, 'confirmation should be visible for an admin grant');
        // Apply without confirming must not write.
        await evaluate(`document.getElementById('save-u1').click()`);
        await sleep(300);
        assert((await audit()).length === 0, 'unconfirmed admin grant must not write');
        const err = await evaluate(`document.getElementById('error').textContent`);
        assert(err.includes('Confirm'), `expected confirm prompt, got: ${err}`);
        // Confirm via the frozen selector.
        await evaluate(`document.querySelector('#confirm-u1 [data-confirm="yes"]').click()`);
        await sleep(400);
        const writes = await audit();
        assert(writes.length === 1 && writes[0].role === 'admin' && writes[0].user_id === 'u1',
          `expected one confirmed admin write, got ${JSON.stringify(writes)}`);
      },

      'removing admin also requires confirmation': async () => {
        await openPage();
        await evaluate(`(() => {
          const s = document.getElementById('role-u3');
          s.value = 'analyst'; s.dispatchEvent(new Event('change'));
        })()`);
        assert(await evaluate(`!document.getElementById('confirm-u3').hidden`),
          'confirmation should be visible for removing admin');
        assert(await evaluate(`document.querySelector('#confirm-u3 [data-confirm="yes"]') !== null`),
          'confirm yes control must carry data-confirm="yes"');
        assert((await audit()).length === 0, 'staging a removal must not write');
      },

      'loading state shows while in flight and blocks a second submit': async () => {
        await openPage();
        // Slow the POST so the in-flight window is observable.
        await evaluate(`(() => {
          const orig = window.fetch.bind(window);
          window.fetch = (input, init) => {
            if (init && init.method === 'POST') {
              return new Promise((r) => setTimeout(() => r(orig(input, init)), 800));
            }
            return orig(input, init);
          };
          const s = document.getElementById('role-u2');
          s.value = 'viewer'; s.dispatchEvent(new Event('change'));
          document.getElementById('save-u2').click();
        })()`);
        await sleep(200);
        const inFlight = await evaluate(`({
          loadingVisible: !document.getElementById('loading-u2').hidden,
          saveDisabled: document.getElementById('save-u2').disabled,
          saveText: document.getElementById('save-u2').textContent,
          pendingHidden: document.getElementById('pending-u2').hidden,
        })`);
        assert(inFlight.loadingVisible, 'loading should be visible while in flight');
        assert(inFlight.saveDisabled, 'Apply must be disabled while in flight');
        assert(inFlight.saveText === 'Saving…', `save label: ${inFlight.saveText}`);
        await evaluate(`document.getElementById('save-u2').click()`); // second click: ignored
        await sleep(1200);
        const writes = await audit();
        assert(writes.length === 1, `duplicate submit guard failed: ${writes.length} writes`);
        const after = await evaluate(`({
          loadingHidden: document.getElementById('loading-u2').hidden,
          status: document.getElementById('status').textContent,
        })`);
        assert(after.loadingHidden, 'loading should clear after completion');
        assert(after.status.startsWith('Saved'), `status after success: ${after.status}`);
      },

      'server failure is reported as an error and keeps the staged change': async () => {
        await openPage();
        await evaluate(`(() => {
          const orig = window.fetch.bind(window);
          window.fetch = (input, init) => {
            if (init && init.method === 'POST') {
              init = { ...init, headers: { ...init.headers, 'X-Test-Fail': '1' } };
            }
            return orig(input, init);
          };
          const s = document.getElementById('role-u2');
          s.value = 'viewer'; s.dispatchEvent(new Event('change'));
          document.getElementById('save-u2').click();
        })()`);
        await sleep(500);
        const st = await evaluate(`({
          status: document.getElementById('status').textContent,
          error: document.getElementById('error').textContent,
          pendingHidden: document.getElementById('pending-u2').hidden,
          select: document.getElementById('role-u2').value,
        })`);
        assert(!st.status.startsWith('Saved'), `failure must not claim success: ${st.status}`);
        assert(st.error.startsWith('Not saved'), `error should say not saved: ${st.error}`);
        assert(!st.pendingHidden, 'staged change must remain visible after failure');
        assert(st.select === 'viewer', 'staged selection must not be dropped after failure');
      },

      'stale version (409) is surfaced as a conflict': async () => {
        await openPage();
        // Another admin changes u2 first, so the version this page holds is stale.
        await evaluate(`fetch('/api/users/u2/role', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ role: 'analyst', version: 1 }),
        }).then((r) => r.status)`);
        await evaluate(`(() => {
          const s = document.getElementById('role-u2');
          s.value = 'viewer'; s.dispatchEvent(new Event('change'));
          document.getElementById('save-u2').click();
        })()`);
        await sleep(500);
        const st = await evaluate(`({
          error: document.getElementById('error').textContent,
          status: document.getElementById('status').textContent,
          pendingHidden: document.getElementById('pending-u2').hidden,
        })`);
        assert(st.error.startsWith('Conflict'), `409 should be a conflict message: ${st.error}`);
        assert(!st.status.startsWith('Saved'), 'conflict must not claim success');
        assert(!st.pendingHidden, 'conflicting change should remain staged for review');
      },

      'controls have accessible names and regions are live': async () => {
        await openPage();
        const a11y = await evaluate(`({
          select: document.getElementById('role-u2').getAttribute('aria-label'),
          save: document.getElementById('save-u2').getAttribute('aria-label'),
          cancel: document.getElementById('cancel-u2').getAttribute('aria-label'),
          statusRole: document.getElementById('status').getAttribute('role'),
          statusLive: document.getElementById('status').getAttribute('aria-live'),
          errorLive: document.getElementById('error').getAttribute('aria-live'),
          errorRole: document.getElementById('error').getAttribute('role'),
        })`);
        assert(a11y.select && a11y.select.includes('bo@example.test'), 'select needs an accessible name');
        assert(a11y.save && a11y.save.length > 0, 'Apply needs an accessible name');
        assert(a11y.cancel && a11y.cancel.length > 0, 'Discard needs an accessible name');
        assert(a11y.statusRole === 'status' && a11y.statusLive === 'polite', 'status must be a polite live region');
        assert(a11y.errorRole === 'alert' || a11y.errorLive, 'error must be a live region');
      },

      'layout does not overflow a 390px viewport': async () => {
        // lightpanda reports document.scrollWidth as 1920 on every page under mobile emulation
        // (even a blank page), so it cannot be used. Instead, measure every element's right
        // edge against the viewport, and first prove the detector flags a known-wide element.
        const offenders = `(() => [...document.querySelectorAll('body *')]
          .filter((e) => e.getBoundingClientRect().width > 0 && e.getBoundingClientRect().right > window.innerWidth + 0.5)
          .map((e) => (e.id || e.tagName) + '@' + Math.round(e.getBoundingClientRect().right)))()`;
        await send('Emulation.setDeviceMetricsOverride', {
          width: 390, height: 800, deviceScaleFactor: 1, mobile: true,
        });
        await send('Page.navigate', {
          url: 'data:text/html,<body style="margin:0"><div id="wide" style="width:800px;height:10px">x</div></body>',
        });
        await sleep(300);
        const control = await evaluate(`(${offenders})`);
        assert(control.length === 1 && control[0].startsWith('wide@'),
          `detector self-check failed: expected 1 offender, got ${JSON.stringify(control)}`);

        await openPage(390);
        await sleep(200);
        const vw = await evaluate('window.innerWidth');
        assert(vw === 390, `viewport not 390 (got ${vw}); emulation unsupported?`);
        const found = await evaluate(`(${offenders})`);
        assert(found.length === 0, `elements overflow the 390px viewport: ${JSON.stringify(found)}`);
      },
    };

    for (const [name, run] of Object.entries(scenarios)) {
      // The mock API keeps state in memory, so restart it for each scenario.
      await restartApi();
      try {
        await run();
        passed++;
        console.log(`ok   - ${name}`);
      } catch (err) {
        failures.push(`${name}: ${err.message}`);
        console.log(`FAIL - ${name}: ${err.message}`);
      }
    }
  } finally {
    try { cdp?.ws.close(); } catch { /* ignore */ }
    lp.kill();
    apiProc?.kill();
  }

  console.log(`\n${passed} passed, ${failures.length} failed`);
  if (failures.length) process.exitCode = 1;
}

function assert(cond, message) {
  if (!cond) throw new Error(message);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
