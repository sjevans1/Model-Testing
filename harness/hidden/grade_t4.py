#!/usr/bin/env python3
"""T4 grader: independent browser acceptance checks for the adminui fixture.

    python3 grade_t4.py <tree> [--pretty] [--timeout 300]

Starts the tree's own `server.py` on a free port and drives the screen through a real
headless browser (lightpanda over CDP, see cdp.py). Writes are counted server-side from
`writes.log`, so a UI that merely *claims* success cannot pass.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from cdp import CDP, CDPError  # noqa: E402

CHECK_META: dict[str, tuple[str, str]] = {
    # id: (group, description)
    "S01": ("functional", "changing the dropdown stages the change and writes nothing"),
    "S02": ("functional", "the explicit apply control writes exactly once and reports success"),
    "S03": ("functional", "discard reverts the staged value and writes nothing"),
    "S04": ("security", "a privilege-sensitive change requires an explicit confirmation first"),
    "S05": ("functional", "in-flight submission shows a loading state and blocks duplicate submits"),
    "S06": ("functional", "a failed submission shows an error, never a success claim"),
    "S07": ("functional", "a stale-version conflict is surfaced, not silently swallowed"),
    "S08": ("a11y", "the controls have accessible names and the live regions are labelled"),
    "S09": ("responsive", "the screen does not overflow a 390px viewport"),
}

PRELUDE = r"""
window.__T4 = {
  q: (sel) => document.querySelector(sel),
  row: (id) => document.querySelector(`tr[data-user-id="${id}"]`),
  rows: () => Array.from(document.querySelectorAll('#users-table tbody tr[data-user-id]')),
  visible: (sel) => {
    const el = document.querySelector(sel);
    if (!el) return false;
    if (el.type === 'hidden') return false;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity || '1') === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  },
  enabled: (sel) => {
    const el = document.querySelector(sel);
    if (!el) return false;
    if (el.disabled) return false;
    if (el.getAttribute('aria-disabled') === 'true') return false;
    if (el.classList && el.classList.contains('disabled')) return false;
    return true;
  },
  click: (target) => {
    const el = typeof target === 'string' ? document.querySelector(target) : target;
    if (!el) throw new Error('no element to click: ' + target);
    const r = el.getBoundingClientRect();
    const opts = {bubbles: true, cancelable: true, composed: true, view: window, detail: 1,
                  clientX: r.left + r.width / 2, clientY: r.top + r.height / 2};
    ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'].forEach((type) =>
      el.dispatchEvent(new MouseEvent(type, opts)));
  },
  setRole: (id, role) => {
    const sel = document.querySelector(`#role-${id}`);
    if (!sel) throw new Error('missing #role-' + id);
    sel.value = role;
    sel.dispatchEvent(new Event('input', {bubbles: true}));
    sel.dispatchEvent(new Event('change', {bubbles: true}));
  },
  text: (sel) => { const el = document.querySelector(sel); return el ? (el.textContent || '').trim() : null; },
  slowFetch: (ms) => {
    if (!window.__origFetch) window.__origFetch = window.fetch;
    window.fetch = (...args) => new Promise((res) => setTimeout(() => res(window.__origFetch(...args)), ms));
  },
  failFetch: (status, body) => {
    if (!window.__origFetch) window.__origFetch = window.fetch;
    window.fetch = (url, opts) => (opts && String(opts.method).toUpperCase() === 'POST')
      ? Promise.resolve({
          ok: false, status: status, statusText: 'Error',
          headers: { get: () => 'application/json' },
          json: async () => body,
          text: async () => JSON.stringify(body),
        })
      : window.__origFetch(url, opts);
  },
  restoreFetch: () => { if (window.__origFetch) window.fetch = window.__origFetch; },
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
};
true;
"""

SENSITIVE_HELP = ("a staged change that grants or removes 'admin' must be confirmed through an "
                  "in-page control carrying data-confirm=\"yes\" inside #confirm-<id>")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_http(url: str, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as fh:
                fh.read(64)
            return True
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    return False


class Runner:
    """Owns the app server, the browser and the write log for one grading run."""

    def __init__(self, tree: pathlib.Path, timeout: float = 300.0) -> None:
        self.tree = tree
        self.timeout = timeout
        self.port = free_port()
        self.debug_port = free_port()
        self.app: subprocess.Popen | None = None
        self.browser_proc: subprocess.Popen | None = None
        self.cdp: CDP | None = None
        self.writes = tree / "writes.log"
        self.base = f"http://127.0.0.1:{self.port}"

    def start_app(self) -> None:
        """(Re)start the tree's mock API with a clean in-memory state and write log."""
        if self.writes.exists():
            self.writes.unlink()
        if self.app and self.app.poll() is None:
            self.app.terminate()
            try:
                self.app.wait(timeout=5)
            except Exception:  # noqa: BLE001
                self.app.kill()
        self.app = subprocess.Popen(
            [sys.executable, "server.py", str(self.port)], cwd=str(self.tree),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        if not wait_http(self.base + "/api/users"):
            raise RuntimeError("the fixture's server.py did not come up")

    def start(self) -> None:
        self.start_app()
        self.browser_proc = subprocess.Popen(
            ["lightpanda", "serve", "--host", "127.0.0.1", "--port", str(self.debug_port)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.debug_port}/json/version", timeout=2):
                    break
            except Exception:  # noqa: BLE001
                time.sleep(0.25)
        self.cdp = CDP(port=self.debug_port)
        # lightpanda allows a single target: open it once and navigate for each scenario.
        self.session = self.cdp.open_page("about:blank")

    def stop(self) -> None:
        if self.cdp:
            self.cdp.close()
        for proc in (self.browser_proc, self.app):
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    proc.kill()

    # -- helpers -------------------------------------------------------------------
    def page(self, tag: str = "") -> str:
        """Navigate the single target to a fresh page and install the test helpers."""
        url = f"{self.base}/?t4={tag}&n={time.time():.0f}"
        self.cdp.call("Page.navigate", session_id=self.session, url=url)
        deadline = time.time() + 15
        ready = False
        while time.time() < deadline:
            time.sleep(0.3)
            try:
                state = self.cdp.eval(self.session, "document.readyState", await_promise=False)
            except CDPError:
                continue
            if state == "complete":
                rows = self.cdp.eval(
                    self.session,
                    "document.querySelectorAll('#users-table tbody tr[data-user-id]').length",
                    await_promise=False,
                )
                if isinstance(rows, int) and rows > 0:
                    ready = True
                    break
        if not ready:
            raise RuntimeError(f"the screen did not render rows at {url}")
        self.cdp.eval(self.session, PRELUDE, await_promise=False)
        return self.session

    def write_entries(self) -> list[dict]:
        if not self.writes.exists():
            return []
        out = []
        for line in self.writes.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass
        return out


def _reset_writes(runner: Runner) -> None:
    if runner.writes.exists():
        runner.writes.unlink()


def run(tree: pathlib.Path, scenario_filter: str | None = None) -> list[dict]:
    results: list[dict] = []
    runner = Runner(tree)

    def check(cid: str, fn) -> None:
        group, desc = CHECK_META[cid]
        if scenario_filter and cid != scenario_filter:
            return
        try:
            runner.start_app()  # every scenario starts from a clean API state
        except Exception as exc:  # noqa: BLE001
            results.append({"id": cid, "group": group, "desc": desc, "passed": False,
                            "detail": f"could not restart the mock API: {exc}"})
            return
        try:
            detail = fn() or "ok"
            results.append({"id": cid, "group": group, "desc": desc, "passed": True, "detail": detail})
        except Exception as exc:  # noqa: BLE001
            results.append({"id": cid, "group": group, "desc": desc, "passed": False,
                            "detail": f"{type(exc).__name__}: {exc}"})

    try:
        runner.start()
    except Exception as exc:  # noqa: BLE001
        return [{"id": cid, "group": g, "desc": d, "passed": False,
                 "detail": f"harness could not start: {exc}"} for cid, (g, d) in CHECK_META.items()]

    # -- S01: staging writes nothing -------------------------------------------------
    def s01():
        s = runner.page("s01")
        r = runner.cdp.eval(s, """(async () => {
          __T4.setRole('u1', 'analyst');
          await __T4.sleep(700);
          return {pending: __T4.visible('#pending-u1'),
                  save: !!__T4.q('#save-u1'), cancel: !!__T4.q('#cancel-u1'),
                  select: __T4.q('#role-u1') ? __T4.q('#role-u1').value : null};
        })()""")
        writes = runner.write_entries()
        assert not writes, f"staging a change wrote to the API: {writes}"
        assert r.get("save"), "there is no #save-u1 control: a change cannot be applied explicitly"
        assert r.get("cancel"), "there is no #cancel-u1 control"
        assert r.get("pending"), "#pending-u1 is not visible while a change is staged"
        return "no write on stage, #pending-u1 visible, save+cancel present"

    # -- S02: apply writes exactly once ---------------------------------------------
    def s02():
        s = runner.page("s02")
        r = runner.cdp.eval(s, """(async () => {
          __T4.setRole('u1', 'analyst');
          await __T4.sleep(300);
          __T4.click('#save-u1');
          await __T4.sleep(900);
          return {status: __T4.text('#status'), pending: __T4.visible('#pending-u1'),
                  select: __T4.q('#role-u1').value};
        })()""")
        writes = runner.write_entries()
        assert len(writes) == 1, f"expected exactly one write, saw {len(writes)}: {writes}"
        assert writes[0].get("role") == "analyst", f"wrong role written: {writes[0]}"
        assert r.get("select") == "analyst", f"select shows {r.get('select')!r} after a successful apply"
        assert not r.get("pending"), "#pending-u1 is still visible after a successful apply"
        status = (r.get("status") or "").lower()
        assert any(word in status for word in ("saved", "updated", "applied", "success")), (
            f"#status does not report success: {status!r}")
        return f"one write, status={status!r}"

    # -- S03: discard ----------------------------------------------------------------
    def s03():
        s = runner.page("s03")
        r = runner.cdp.eval(s, """(async () => {
          __T4.setRole('u1', 'analyst');
          await __T4.sleep(300);
          __T4.click('#cancel-u1');
          await __T4.sleep(500);
          return {select: __T4.q('#role-u1').value, pending: __T4.visible('#pending-u1')};
        })()""")
        assert not runner.write_entries(), "discard wrote to the API"
        assert r.get("select") == "viewer", f"discard left the select at {r.get('select')!r}"
        assert not r.get("pending"), "#pending-u1 is still visible after a discard"
        return "discard reverted the select and wrote nothing"

    # -- S04: privilege-sensitive confirmation --------------------------------------
    def s04():
        s = runner.page("s04")
        r = runner.cdp.eval(s, """(async () => {
          __T4.setRole('u1', 'admin');
          await __T4.sleep(400);
          const confirmVisible = __T4.visible('#confirm-u1');
          const confirmControl = !!document.querySelector('#confirm-u1 [data-confirm="yes"]');
          let saveExists = !!__T4.q('#save-u1');
          if (saveExists) { __T4.click('#save-u1'); await __T4.sleep(600); }
          const writesBeforeConfirm = null;
          return {confirmVisible, confirmControl, saveExists};
        })()""")
        writes_before = runner.write_entries()
        assert r.get("confirmVisible"), f"#confirm-u1 is not visible for a privilege-sensitive change ({SENSITIVE_HELP})"
        assert r.get("confirmControl"), f"#confirm-u1 has no [data-confirm=\"yes\"] control ({SENSITIVE_HELP})"
        assert not writes_before, f"the sensitive change was written before confirmation: {writes_before}"
        r2 = runner.cdp.eval(s, """(async () => {
          __T4.click('#confirm-u1 [data-confirm="yes"]');
          await __T4.sleep(400);
          if (__T4.q('#save-u1') && __T4.enabled('#save-u1')) { __T4.click('#save-u1'); }
          await __T4.sleep(900);
          return {select: __T4.q('#role-u1').value};
        })()""")
        writes = runner.write_entries()
        assert len(writes) == 1, f"expected one write after confirming, saw {len(writes)}: {writes}"
        assert writes[0].get("role") == "admin", f"wrong role written: {writes[0]}"
        return "sensitive change gated, then applied once"

    # -- S05: loading state + duplicate submits --------------------------------------
    def s05():
        s = runner.page("s05")
        r = runner.cdp.eval(s, """(async () => {
          __T4.slowFetch(600);
          __T4.setRole('u1', 'analyst');
          await __T4.sleep(250);
          __T4.click('#save-u1');
          await __T4.sleep(250);
          const loading = __T4.visible('#loading-u1');
          const saveEnabled = __T4.enabled('#save-u1');
          try { __T4.click('#save-u1'); } catch (e) {}
          try { __T4.click('#save-u1'); } catch (e) {}
          await __T4.sleep(1600);
          __T4.restoreFetch();
          return {loading, saveEnabled};
        })()""", timeout=60)
        writes = runner.write_entries()
        assert r.get("loading"), "#loading-u1 is not visible while the submission is in flight"
        assert not r.get("saveEnabled"), "the apply control stays enabled while a submission is in flight"
        assert len(writes) == 1, f"duplicate submissions reached the API: {len(writes)} writes"
        return "loading shown, apply disabled, exactly one write"

    # -- S06: failure honesty --------------------------------------------------------
    def s06():
        s = runner.page("s06")
        r = runner.cdp.eval(s, """(async () => {
          __T4.failFetch(500, {error: 'upstream'});
          __T4.setRole('u1', 'analyst');
          await __T4.sleep(250);
          __T4.click('#save-u1');
          await __T4.sleep(900);
          const out = {error: __T4.text('#error'), status: __T4.text('#status'),
                       pending: __T4.visible('#pending-u1'), select: __T4.q('#role-u1').value};
          __T4.restoreFetch();
          return out;
        })()""")
        assert (r.get("error") or "").strip(), "#error is empty after a failed submission"
        status = (r.get("status") or "").lower()
        assert not any(word in status for word in ("saved", "success", "updated", "applied")), (
            f"#status claims success after a failure: {status!r}")
        assert r.get("pending") or r.get("select") == "analyst", (
            "the staged change was silently lost after a failure")
        return f"error shown ({r['error']!r}), no success claim"

    # -- S07: stale version conflict --------------------------------------------------
    def s07():
        s = runner.page("s07")
        r = runner.cdp.eval(s, """(async () => {
          __T4.failFetch(409, {error: 'StaleVersion', current: 4});
          __T4.setRole('u1', 'analyst');
          await __T4.sleep(250);
          __T4.click('#save-u1');
          await __T4.sleep(900);
          const out = {error: __T4.text('#error'), status: __T4.text('#status')};
          __T4.restoreFetch();
          return out;
        })()""")
        blob = f"{r.get('error') or ''} {r.get('status') or ''}".lower()
        assert any(word in blob for word in ("stale", "conflict", "changed", "refresh", "version", "reload")), (
            f"a stale-version conflict was not surfaced to the administrator: {blob!r}")
        return f"conflict surfaced: {r.get('error')!r}"

    # -- S08: accessible names -------------------------------------------------------
    def s08():
        s = runner.page("s08")
        r = runner.cdp.eval(s, """(() => {
          const sel = __T4.q('#role-u1');
          const labelled = !!(sel && (sel.getAttribute('aria-label') || sel.getAttribute('aria-labelledby')
                             || (sel.id && document.querySelector(`label[for="${sel.id}"]`))));
          const save = __T4.q('#save-u1');
          const saveName = save ? (save.textContent || '').trim() || save.getAttribute('aria-label') || '' : '';
          const saveOk = !!(save && save.tagName === 'BUTTON' && saveName && save.tabIndex >= 0);
          const status = __T4.q('#status');
          const statusOk = !!status && (status.getAttribute('role') === 'status'
                           || status.getAttribute('aria-live') === 'polite' || status.getAttribute('aria-live') === 'assertive');
          const error = __T4.q('#error');
          const errorOk = !!error && (error.getAttribute('role') === 'alert' || !!error.getAttribute('aria-live'));
          return {labelled, saveOk, statusOk, errorOk};
        })()""")
        assert r.get("labelled"), "#role-u1 has no accessible name"
        assert r.get("saveOk"), "#save-u1 is missing, is not a button, or has no accessible name"
        assert r.get("statusOk"), "#status is not a polite live region"
        assert r.get("errorOk"), "#error is not an alert/live region"
        return "select + apply control + live regions labelled"

    # -- S09: responsive -------------------------------------------------------------
    def s09():
        s = runner.page("s09")
        for method, kwargs in (("Emulation.setDeviceMetricsOverride",
                                dict(width=390, height=844, deviceScaleFactor=3, mobile=True)),):
            try:
                runner.cdp.call(method, session_id=s, **kwargs)
            except CDPError:
                return "SKIPPED: this browser build does not implement device-metrics emulation"
        time.sleep(0.8)
        r = runner.cdp.eval(s, """(() => {
          const doc = document.documentElement;
          const overflowing = Array.from(document.querySelectorAll('body *')).filter((el) => {
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.right > window.innerWidth + 2;
          }).slice(0, 5).map((el) => el.tagName + (el.id ? '#' + el.id : ''));
        return {innerWidth: window.innerWidth, scrollWidth: doc.scrollWidth, overflowing};
        })()""")
        if r.get("innerWidth", 0) > 400 or r.get("scrollWidth", 0) >= 2 * max(r.get("innerWidth", 1), 1):
            return (f"SKIPPED: viewport emulation does not reflow layout in this browser build "
                    f"(innerWidth={r.get('innerWidth')}, scrollWidth={r.get('scrollWidth')}); "
                    "responsive behaviour was not verifiable here")
        assert r.get("scrollWidth", 9999) <= r.get("innerWidth", 0) + 2, (
            f"horizontal overflow at 390px: scrollWidth={r.get('scrollWidth')}")
        assert not r.get("overflowing"), f"elements overflow the 390px viewport: {r.get('overflowing')}"
        return f"no overflow at {r.get('innerWidth')}px"

    for cid, fn in (("S01", s01), ("S02", s02), ("S03", s03), ("S04", s04), ("S05", s05),
                    ("S06", s06), ("S07", s07), ("S08", s08), ("S09", s09)):
        check(cid, fn)
    runner.stop()
    return results


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    tree = pathlib.Path(args[0] if args else ".").resolve()
    results = run(tree)
    if "--pretty" in sys.argv:
        for r in results:
            print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['id']}  [{r['group']}]  {r['detail']}")
        failed = [r["id"] for r in results if not r["passed"]]
        print(f"\n{len(results) - len(failed)}/{len(results)} pass" + (f"; failing: {failed}" if failed else ""))
    else:
        print(json.dumps({"tree": str(tree), "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
