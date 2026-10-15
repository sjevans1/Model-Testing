'use strict';
// Users and access screen.
//
// Picking a new access level only stages a local change; nothing is sent until the
// administrator uses the explicit Apply control. Changes that grant or remove `admin`
// need an in-page confirmation first. While a submission is in flight the controls are
// disabled and a loading message is shown. Success, failure and version conflicts are
// reported distinctly. A failed or conflicting change stays staged, so it is never
// silently dropped.

const ROLES = ['viewer', 'analyst', 'admin'];

// userId -> { user, staged, inFlight, rows }
//   user:   last committed user as the client knows it ({id, email, role, version})
//   staged: pending role string, or null when nothing is staged
const state = {};

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, body };
}

function setStatus(text) {
  document.getElementById('status').textContent = text;
}

function setError(text) {
  document.getElementById('error').textContent = text;
}

// True when the change grants or removes the admin role.
function isPrivileged(user, role) {
  return (role === 'admin') !== (user.role === 'admin');
}

function makeButton(id, label, ariaLabel) {
  const b = document.createElement('button');
  b.type = 'button';
  b.id = id;
  b.textContent = label;
  b.setAttribute('aria-label', ariaLabel);
  return b;
}

function buildRow(user) {
  const entry = state[user.id];

  const row = document.createElement('tr');
  row.dataset.userId = user.id;

  const email = document.createElement('td');
  email.textContent = user.email;
  email.dataset.label = 'Email';

  const roleCell = document.createElement('td');
  roleCell.dataset.label = 'Access level';
  const select = document.createElement('select');
  select.id = `role-${user.id}`;
  select.setAttribute('aria-label', `Access level for ${user.email}`);
  for (const role of ROLES) {
    const option = document.createElement('option');
    option.value = role;
    option.textContent = role;
    select.appendChild(option);
  }
  roleCell.appendChild(select);

  const actions = document.createElement('td');
  actions.className = 'actions';
  actions.dataset.label = 'Actions';

  const pending = document.createElement('p');
  pending.id = `pending-${user.id}`;
  pending.className = 'pending';
  pending.hidden = true;

  const loading = document.createElement('p');
  loading.id = `loading-${user.id}`;
  loading.className = 'loading';
  loading.hidden = true;
  loading.textContent = `Saving access level for ${user.email}…`;

  const confirm = document.createElement('div');
  confirm.id = `confirm-${user.id}`;
  confirm.className = 'confirm';
  confirm.hidden = true;
  const confirmText = document.createElement('p');
  confirmText.className = 'confirm-text';
  const confirmYes = makeButton(`confirm-yes-${user.id}`, 'Confirm admin change',
    `Confirm admin access change for ${user.email}`);
  confirmYes.dataset.confirm = 'yes';
  const confirmNo = makeButton(`confirm-no-${user.id}`, 'Keep current',
    `Keep current access for ${user.email}`);
  confirmNo.dataset.confirm = 'no';
  confirm.append(confirmText, confirmYes, confirmNo);

  const controls = document.createElement('div');
  controls.className = 'controls';
  const save = makeButton(`save-${user.id}`, 'Apply change',
    `Apply access change for ${user.email}`);
  const cancel = makeButton(`cancel-${user.id}`, 'Discard change',
    `Discard staged access change for ${user.email}`);
  controls.append(save, cancel);

  actions.append(pending, loading, confirm, controls);
  row.append(email, roleCell, actions);

  entry.rows = { row, select, save, cancel, pending, loading, confirm, confirmText, confirmYes, confirmNo };

  select.addEventListener('change', () => {
    const value = select.value;
    entry.staged = value === entry.user.role ? null : value;
    setError('');
    setStatus(entry.staged ? `Change staged for ${entry.user.email}. It is not saved yet.` : '');
    paint(user.id);
  });
  save.addEventListener('click', () => commit(user.id, false));
  cancel.addEventListener('click', () => discard(user.id));
  confirmYes.addEventListener('click', () => commit(user.id, true));
  confirmNo.addEventListener('click', () => discard(user.id));

  return row;
}

// Reflects the state for one user in the DOM.
function paint(id) {
  const entry = state[id];
  const r = entry.rows;
  if (!r) return;
  const { user, staged, inFlight } = entry;
  const hasStaged = staged !== null;
  const privileged = hasStaged && isPrivileged(user, staged);

  r.select.value = hasStaged ? staged : user.role;
  r.select.disabled = inFlight;
  r.row.classList.toggle('staged', hasStaged);

  r.pending.hidden = !hasStaged || inFlight;
  r.pending.textContent = hasStaged ? `Pending: ${user.role} → ${staged}. Not saved.` : '';

  r.loading.hidden = !inFlight;

  r.confirm.hidden = !privileged || inFlight;
  if (privileged) {
    const verb = staged === 'admin' ? 'Grant' : 'Remove';
    r.confirmText.textContent = `${verb} admin access for ${user.email}? This is privilege-sensitive. ` +
      `Confirm to change access from ${user.role} to ${staged}.`;
  }
  r.confirmYes.disabled = inFlight;
  r.confirmNo.disabled = inFlight;

  r.save.disabled = !hasStaged || inFlight;
  r.save.textContent = inFlight ? 'Saving…' : 'Apply change';
  r.cancel.disabled = !hasStaged || inFlight;
}

// Applies the staged change. A privilege-sensitive change is sent only when confirmed.
async function commit(id, confirmed) {
  const entry = state[id];
  if (!entry || entry.inFlight || entry.staged === null) return;
  const { user } = entry;
  const role = entry.staged;

  if (isPrivileged(user, role) && !confirmed) {
    setStatus('');
    setError(`Confirm the admin change for ${user.email} before it is applied.`);
    entry.rows.confirmYes.focus();
    paint(id);
    return;
  }

  entry.inFlight = true;
  setError('');
  setStatus('');
  paint(id);

  let result;
  try {
    result = await api(`/api/users/${encodeURIComponent(user.id)}/role`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role, version: user.version }),
    });
  } catch (err) {
    result = { ok: false, status: 0, body: {} };
  }
  entry.inFlight = false;

  if (result.ok && result.body && result.body.user) {
    entry.user = result.body.user;
    entry.staged = null;
    setStatus(`Saved: ${user.email} now has ${entry.user.role} access.`);
    paint(id);
    return;
  }

  if (result.status === 409) {
    await refreshUser(id);
    const current = entry.user;
    if (entry.staged === current.role) {
      entry.staged = null;
      setError(`Conflict: ${user.email} already has ${current.role} access, so the staged change was dropped.`);
    } else {
      setError(`Conflict: ${user.email} was changed by someone else. Current access is ${current.role}. ` +
        `Your change to ${role} is still staged. Review it, then apply again or discard it.`);
    }
    paint(id);
    return;
  }

  const reason = result.status === 0 ? 'the request did not reach the server' : `the server returned ${result.status}`;
  setError(`Not saved: ${reason}. ${user.email} still has ${user.role} access. ` +
    `Your change to ${role} is still staged. Apply again or discard it.`);
  paint(id);
}

function discard(id) {
  const entry = state[id];
  if (!entry || entry.inFlight || entry.staged === null) return;
  const email = entry.user.email;
  entry.staged = null;
  setError('');
  setStatus(`Staged change discarded for ${email}.`);
  paint(id);
}

// Refreshes the committed role and version for one user, keeping any staged change.
async function refreshUser(id) {
  const { body } = await api('/api/users');
  const fresh = (body.users || []).find((u) => u.id === id);
  if (fresh && state[id]) state[id].user = fresh;
}

async function render() {
  const tbody = document.querySelector('#users-table tbody');
  tbody.textContent = '';
  let body;
  try {
    ({ body } = await api('/api/users'));
  } catch (err) {
    setError('Could not load users. Reload the page to try again.');
    return;
  }
  for (const user of body.users || []) {
    state[user.id] = { user, staged: null, inFlight: false, rows: null };
    tbody.appendChild(buildRow(user));
    paint(user.id);
  }
}

render();
