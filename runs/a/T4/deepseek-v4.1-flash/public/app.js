'use strict';
// Users and access screen.
//
// Interaction model (deliberate, not save-on-change):
//   1. picking a new role in #role-<id> only *stages* a local pending change; nothing
//      is sent to the API;
//   2. the staged change is flagged in the row (#pending-<id>) until it is applied or
//      discarded;
//   3. granting or removing `admin` is privilege sensitive: #confirm-<id> appears with
//      an in-page confirmation control (data-confirm="yes") and #save-<id> stays
//      disabled until the administrator confirms;
//   4. #save-<id> commits it through the API, showing #loading-<id> while the request
//      is in flight and refusing to start a second submission;
//   5. #cancel-<id> discards it.
// Outcomes go to #status (success) or #error (failure/conflict); a failure never
// claims success and never drops the staged change.

const ROLES = ['viewer', 'analyst', 'admin'];
const PRIVILEGED_ROLE = 'admin';

const state = {
  users: [],            // [{ id, email, role, version }] as last read from the API
  pending: new Map(),   // user id -> staged role that has not been applied yet
  confirmed: new Map(), // user id -> staged role the administrator confirmed
  busy: new Set(),      // user ids with a submission in flight
};

const byId = (id) => document.getElementById(id);
const userById = (id) => state.users.find((user) => user.id === id) || null;
const stagedRole = (id) => (state.pending.has(id) ? state.pending.get(id) : undefined);

function isPrivilegeSensitive(user, staged) {
  return staged !== user.role && (staged === PRIVILEGED_ROLE || user.role === PRIVILEGED_ROLE);
}

function isConfirmed(user, staged) {
  return staged !== undefined && state.confirmed.get(user.id) === staged;
}

function canApply(user) {
  const staged = stagedRole(user.id);
  if (staged === undefined || staged === user.role) return false;
  if (state.busy.has(user.id)) return false;
  if (isPrivilegeSensitive(user, staged) && !isConfirmed(user, staged)) return false;
  return true;
}

// ---------------------------------------------------------------- messages ---

function setStatus(text) {
  const node = byId('status');
  if (node) node.textContent = text || '';
}

function setError(text) {
  const node = byId('error');
  if (node) node.textContent = text || '';
}

// A new deliberate action starts from a clean slate: no stale outcome text is left
// on screen next to it.
function clearMessages() {
  setStatus('');
  setError('');
}

// ------------------------------------------------------------------ a11y -----

function named(button, name) {
  button.setAttribute('aria-label', name);
  return button;
}

function makeButton({ id, label, className, ariaName }) {
  const button = document.createElement('button');
  button.type = 'button';
  button.id = id;
  button.className = className;
  button.textContent = label;
  named(button, ariaName);
  return button;
}

// ------------------------------------------------------------------ render ---

function roleSelect(user) {
  const staged = stagedRole(user.id);
  const value = staged === undefined ? user.role : staged;
  const select = document.createElement('select');
  select.id = `role-${user.id}`;
  select.setAttribute('aria-label', `Access level for ${user.email}`);
  if (staged !== undefined && staged !== user.role) {
    select.classList.add('pending-select');
    select.setAttribute('data-staged', staged);
    select.setAttribute('aria-describedby', `pending-${user.id}`);
  }
  for (const role of ROLES) {
    const option = document.createElement('option');
    option.value = role;
    option.textContent = role;
    if (role === value) option.selected = true;
    select.appendChild(option);
  }
  select.disabled = state.busy.has(user.id); // frozen while a submission is in flight
  select.addEventListener('change', () => stageChange(user.id, select.value));
  return select;
}

function pendingBadge(user) {
  const staged = stagedRole(user.id);
  if (staged === undefined || staged === user.role) return null;
  const badge = document.createElement('span');
  badge.id = `pending-${user.id}`;
  badge.className = 'badge badge-pending';
  badge.setAttribute('data-pending', 'true');
  badge.setAttribute('data-staged-role', staged);
  const confirmed = isConfirmed(user, staged);
  badge.textContent = confirmed
    ? `Pending: ${user.role} → ${staged} (confirmed, not applied)`
    : `Pending: ${user.role} → ${staged} (not applied)`;
  return badge;
}

function loadingBadge(user) {
  if (!state.busy.has(user.id)) return null;
  const badge = document.createElement('span');
  badge.id = `loading-${user.id}`;
  badge.className = 'badge badge-loading';
  badge.setAttribute('data-loading', 'true');
  badge.setAttribute('role', 'status');
  badge.setAttribute('aria-live', 'polite');
  badge.textContent = 'Saving…';
  return badge;
}

function confirmPanel(user) {
  const staged = stagedRole(user.id);
  if (staged === undefined || !isPrivilegeSensitive(user, staged) || isConfirmed(user, staged)) {
    return null;
  }
  const box = document.createElement('div');
  box.id = `confirm-${user.id}`;
  box.className = 'confirm';
  box.setAttribute('role', 'group');
  box.setAttribute('data-confirm-required', 'true');
  box.setAttribute('aria-label', `Confirm the privilege change for ${user.email}`);

  const text = document.createElement('p');
  text.id = `confirm-text-${user.id}`;
  text.className = 'confirm-text';
  text.textContent = staged === PRIVILEGED_ROLE
    ? `This grants admin access to ${user.email}. Confirm before it can be applied.`
    : `This removes admin access from ${user.email}. Confirm before it can be applied.`;
  box.setAttribute('aria-describedby', text.id);

  const yes = makeButton({
    id: `confirm-yes-${user.id}`,
    label: 'Confirm',
    className: 'btn btn-warn',
    ariaName: `Yes, confirm changing ${user.email} from ${user.role} to ${staged}`,
  });
  yes.setAttribute('data-confirm', 'yes');
  yes.addEventListener('click', () => confirmChange(user.id));

  const no = makeButton({
    id: `confirm-no-${user.id}`,
    label: 'No, discard',
    className: 'btn',
    ariaName: `No, discard the staged change for ${user.email}`,
  });
  no.setAttribute('data-confirm', 'no');
  no.addEventListener('click', () => discardChange(user.id));

  box.append(text, yes, no);
  return box;
}

function rowFor(user) {
  const row = document.createElement('tr');
  row.dataset.userId = user.id;
  if (state.busy.has(user.id)) row.setAttribute('aria-busy', 'true');

  const email = document.createElement('td');
  email.className = 'cell-email';
  email.dataset.label = 'Email';
  email.textContent = user.email;

  const roleCell = document.createElement('td');
  roleCell.className = 'cell-role';
  roleCell.dataset.label = 'Access level';
  roleCell.appendChild(roleSelect(user));
  const pending = pendingBadge(user);
  if (pending) roleCell.appendChild(pending);
  const loading = loadingBadge(user);
  if (loading) roleCell.appendChild(loading);

  const actions = document.createElement('td');
  actions.className = 'cell-actions';
  actions.dataset.label = 'Actions';
  const group = document.createElement('div');
  group.className = 'row-actions';

  const staged = stagedRole(user.id);
  const apply = makeButton({
    id: `save-${user.id}`,
    label: 'Apply',
    className: 'btn btn-primary',
    ariaName: `Apply the access-level change for ${user.email}`,
  });
  const blocked = !canApply(user);
  apply.disabled = blocked;
  apply.setAttribute('aria-disabled', String(blocked));
  if (state.busy.has(user.id)) apply.setAttribute('aria-busy', 'true');
  if (blocked && isPrivilegeSensitive(user, staged) && !isConfirmed(user, staged) && staged !== undefined) {
    apply.setAttribute('aria-describedby', `confirm-${user.id}`);
  }
  apply.addEventListener('click', () => applyChange(user.id));

  const cancel = makeButton({
    id: `cancel-${user.id}`,
    label: 'Cancel',
    className: 'btn',
    ariaName: `Discard the staged access-level change for ${user.email}`,
  });
  cancel.disabled = staged === undefined || state.busy.has(user.id);
  cancel.addEventListener('click', () => discardChange(user.id));

  group.append(apply, cancel);
  actions.appendChild(group);
  const confirm = confirmPanel(user);
  if (confirm) actions.appendChild(confirm);

  row.append(email, roleCell, actions);
  return row;
}

function render() {
  const tbody = document.querySelector('#users-table tbody');
  if (!tbody) return;
  tbody.textContent = '';
  for (const user of state.users) tbody.appendChild(rowFor(user));
}

// ------------------------------------------------------------------ actions --

function stageChange(id, role) {
  const user = userById(id);
  if (!user) return;
  if (state.busy.has(id)) { // frozen while a submission is in flight
    render();
    return;
  }
  clearMessages();
  if (role === user.role) {
    state.pending.delete(id); // back to the persisted value: nothing is staged any more
  } else {
    state.pending.set(id, role);
  }
  // Confirmation is always given for one specific staged value; a different value
  // (or a different target user state) needs a fresh confirmation.
  state.confirmed.delete(id);
  render();
}

function confirmChange(id) {
  const user = userById(id);
  const staged = stagedRole(id);
  if (!user || staged === undefined) return;
  state.confirmed.set(id, staged);
  render();
}

function discardChange(id) {
  const user = userById(id);
  if (!user || state.busy.has(id)) return;
  state.pending.delete(id);
  state.confirmed.delete(id);
  clearMessages();
  render(); // the row is rebuilt: the select shows the persisted role again, #pending-<id> is gone
}

function requestHeaders() {
  const headers = { 'Content-Type': 'application/json' };
  // Test hook: a harness may inject extra headers (e.g. X-Test-Fail: 1) here.
  const extra = typeof window !== 'undefined' ? window.ADMINUI_TEST_HEADERS : null;
  if (extra && typeof extra === 'object') {
    for (const [key, value] of Object.entries(extra)) headers[key] = String(value);
  }
  return headers;
}

async function readJson(response) {
  try {
    return await response.json();
  } catch (err) {
    return {};
  }
}

// `fetch` is looked up on the global object at call time so a test harness can wrap
// or stub it before a submission happens.
async function postRole(id, role, version) {
  const response = await fetch(`/api/users/${encodeURIComponent(id)}/role`, {
    method: 'POST',
    headers: requestHeaders(),
    body: JSON.stringify({ role, version }),
  });
  return { ok: response.ok, status: response.status, body: await readJson(response) };
}

async function fetchUsers() {
  const response = await fetch('/api/users');
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return await readJson(response);
}

async function applyChange(id) {
  const user = userById(id);
  const staged = stagedRole(id);
  if (!user || staged === undefined || staged === user.role) return;
  if (isPrivilegeSensitive(user, staged) && !isConfirmed(user, staged)) return; // awaiting confirmation
  if (state.busy.has(id)) return; // duplicate-submit guard

  const sentVersion = user.version;
  state.busy.add(id);
  clearMessages();
  render(); // #loading-<id> is now on screen and #save-<id> is disabled

  let result;
  try {
    result = await postRole(user.id, staged, sentVersion);
  } catch (err) {
    state.busy.delete(id);
    reportFailure(user, `Could not save ${user.email}: the request failed (${
      err && err.message ? err.message : 'network error'}). Your staged change to ${staged} was kept.`);
    return;
  }
  state.busy.delete(id);

  if (result.ok) {
    const server = (result.body && result.body.user) || {};
    user.role = server.role || staged;
    user.version = server.version !== undefined ? server.version : Number(sentVersion) + 1;
    // Only clear what was actually committed; a newer staged value stays staged.
    if (state.pending.get(id) === staged) state.pending.delete(id);
    state.confirmed.delete(id);
    setStatus(`Saved. ${user.email} now has ${user.role} access (version ${user.version}).`);
  } else if (result.status === 409) {
    await reportConflict(user, staged);
    return;
  } else {
    const reason = (result.body && result.body.error) || 'request rejected';
    reportFailure(user, `Could not save ${user.email}: ${reason} (HTTP ${result.status}). `
      + `Your staged change to ${staged} was kept — you can try again.`);
    return;
  }
  render();
}

function reportFailure(user, message) {
  setStatus(''); // never claim success on a failure
  setError(message);
  render();
}

async function reportConflict(user, staged) {
  setStatus(''); // never claim success on a failure
  setError(`Conflict: ${user.email}'s access level was changed by someone else while you were `
    + `reviewing (stale version ${user.version}). Your staged change to ${staged} was kept.`);
  render();
  let fresh = null;
  try {
    const body = await fetchUsers();
    fresh = (body.users || []).find((candidate) => candidate.id === user.id) || null;
  } catch (err) {
    fresh = null;
  }
  if (!fresh) {
    render();
    return;
  }
  user.role = fresh.role;
  user.version = fresh.version;
  let extra = ` The record is now ${fresh.role} (version ${fresh.version}); review it and apply again.`;
  if (fresh.role === staged) {
    state.pending.delete(user.id);
    state.confirmed.delete(user.id);
    extra = ` The record is now ${fresh.role} (version ${fresh.version}); it already matches your `
      + `staged change, so nothing is staged any more.`;
  }
  setError(`Conflict: ${user.email}'s access level was changed by someone else while you were `
    + `reviewing (stale version). Your staged change to ${staged} was kept.` + extra);
  setStatus('');
  render();
}

// --------------------------------------------------------------------- init --

async function load() {
  try {
    const body = await fetchUsers();
    state.users = body.users || [];
  } catch (err) {
    state.users = [];
    setError(`Could not load users: ${err && err.message ? err.message : 'request failed'}. `
      + 'Reload the page to try again.');
  }
  render();
}

load();
