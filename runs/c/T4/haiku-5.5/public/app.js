'use strict';
// Users and access screen.
//
// A role change is staged locally when the administrator picks a new value. Nothing is
// sent until Save is pressed. Changes that grant or remove `admin` also require an
// explicit in-page confirmation. Every submission reports success or failure distinctly
// and keeps the staged change on failure.

const ROLES = ['viewer', 'analyst', 'admin'];

// Per-user UI state, keyed by user id:
//   email:     shown in labels and messages
//   committed: role the server last confirmed
//   version:   version the server last reported (sent with every write)
//   staged:    role chosen by the administrator but not yet applied, or null
//   busy:      a submission is in flight
const state = new Map();

async function api(path, options) {
  let response;
  try {
    response = await fetch(path, options);
  } catch (err) {
    return { ok: false, status: 0, body: {} };
  }
  const body = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, body };
}

function $(id) {
  return document.getElementById(id);
}

function setStatus(text) {
  $('status').textContent = text;
}

function setError(text) {
  $('error').textContent = text;
}

function isPrivileged(committed, staged) {
  // Granting or removing admin is privilege sensitive.
  return (committed === 'admin') !== (staged === 'admin');
}

function roleSelect(user) {
  const select = document.createElement('select');
  select.id = `role-${user.id}`;
  select.setAttribute('aria-label', `Access level for ${user.email}`);
  for (const role of ROLES) {
    const option = document.createElement('option');
    option.value = role;
    option.textContent = role;
    select.appendChild(option);
  }
  select.addEventListener('change', () => onSelect(user.id));
  return select;
}

function actionButton(id, kind, text, handler) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.id = `${kind}-${id}`;
  btn.textContent = text;
  btn.setAttribute('aria-label', `${text} access level change for ${state.get(id).email}`);
  btn.addEventListener('click', handler);
  return btn;
}

function buildActions(user) {
  const cell = document.createElement('td');
  cell.dataset.label = 'Actions';

  const pending = document.createElement('p');
  pending.id = `pending-${user.id}`;
  pending.className = 'pending';
  pending.hidden = true;

  const confirm = document.createElement('div');
  confirm.id = `confirm-${user.id}`;
  confirm.className = 'confirm';
  confirm.hidden = true;
  const warning = document.createElement('p');
  warning.className = 'confirm-text';
  warning.id = `confirm-text-${user.id}`;
  const yes = document.createElement('button');
  yes.type = 'button';
  yes.dataset.confirm = 'yes';
  yes.className = 'danger';
  yes.textContent = 'Confirm and apply';
  yes.setAttribute('aria-label', `Confirm and apply admin change for ${user.email}`);
  yes.addEventListener('click', () => submit(user.id));
  const no = document.createElement('button');
  no.type = 'button';
  no.dataset.confirm = 'no';
  no.textContent = 'Back';
  no.setAttribute('aria-label', `Back without applying admin change for ${user.email}`);
  no.addEventListener('click', () => onCancel(user.id));
  confirm.append(warning, yes, no);

  const loading = document.createElement('p');
  loading.id = `loading-${user.id}`;
  loading.className = 'loading';
  loading.hidden = true;
  loading.textContent = 'Saving…';

  const save = actionButton(user.id, 'save', 'Save', () => onSave(user.id));
  const cancel = actionButton(user.id, 'cancel', 'Discard', () => onCancel(user.id));

  const group = document.createElement('div');
  group.className = 'row-actions';
  group.append(save, cancel);

  cell.append(pending, confirm, loading, group);
  return cell;
}

function renderRow(user) {
  const row = document.createElement('tr');
  row.dataset.userId = user.id;

  const email = document.createElement('td');
  email.dataset.label = 'Email';
  email.textContent = user.email;

  const roleCell = document.createElement('td');
  roleCell.dataset.label = 'Access level';
  roleCell.appendChild(roleSelect(user));

  row.append(email, roleCell, buildActions(user));
  return row;
}

function updateRow(id) {
  const s = state.get(id);
  const row = document.querySelector(`#users-table tbody tr[data-user-id="${id}"]`);
  const select = $(`role-${id}`);
  const pending = $(`pending-${id}`);
  const confirm = $(`confirm-${id}`);
  const loading = $(`loading-${id}`);
  const save = $(`save-${id}`);
  const cancel = $(`cancel-${id}`);

  select.value = s.staged || s.committed;
  select.disabled = s.busy;

  const hasStaged = s.staged !== null;
  row.classList.toggle('is-pending', hasStaged);

  pending.hidden = !hasStaged || s.busy;
  pending.textContent = hasStaged
    ? `Pending: ${s.committed} → ${s.staged}. Not saved yet.`
    : '';

  const needsConfirm = hasStaged && isPrivileged(s.committed, s.staged) && !s.busy;
  confirm.hidden = !needsConfirm;
  if (needsConfirm) {
    $(`confirm-text-${id}`).textContent = s.staged === 'admin'
      ? `This grants admin access to ${s.email}. Confirm to apply.`
      : `This removes admin access from ${s.email}. Confirm to apply.`;
  }

  loading.hidden = !s.busy;
  row.setAttribute('aria-busy', s.busy ? 'true' : 'false');

  save.disabled = !hasStaged || s.busy;
  cancel.disabled = !hasStaged || s.busy;
}

function onSelect(id) {
  const s = state.get(id);
  const chosen = $(`role-${id}`).value;
  s.staged = chosen === s.committed ? null : chosen;
  setError('');
  setStatus(s.staged ? `Staged change for ${s.email}: ${s.committed} → ${s.staged}. Not saved yet.` : '');
  updateRow(id);
}

function onCancel(id) {
  const s = state.get(id);
  if (s.busy || s.staged === null) return;
  const discarded = s.staged;
  s.staged = null;
  setError('');
  setStatus(`Discarded pending change to ${discarded} for ${s.email}.`);
  updateRow(id);
}

function onSave(id) {
  const s = state.get(id);
  if (s.busy || s.staged === null) return;
  if (isPrivileged(s.committed, s.staged)) {
    // Privilege-sensitive changes are applied only through the in-page confirmation.
    setStatus('');
    setError(`Confirm the ${s.staged === 'admin' ? 'grant' : 'removal'} of admin access before it is applied.`);
    $(`confirm-${id}`).querySelector('button[data-confirm="yes"]').focus();
    return;
  }
  submit(id);
}

async function submit(id) {
  const s = state.get(id);
  if (s.busy || s.staged === null) return; // duplicate-submit guard
  const attempted = s.staged;
  s.busy = true;
  setError('');
  setStatus('');
  updateRow(id);

  const res = await api(`/api/users/${encodeURIComponent(id)}/role`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role: attempted, version: s.version }),
  });
  s.busy = false;

  if (res.ok && res.body.user) {
    s.committed = res.body.user.role;
    s.version = res.body.user.version;
    s.staged = null;
    updateRow(id);
    setStatus(`Saved: ${s.email} is now ${s.committed}.`);
    return;
  }

  if (res.status === 409) {
    // Someone else changed the user since it was loaded. Refresh the version and current
    // role so the administrator can review. The staged change is kept, not applied.
    await refreshUser(id);
    const after = state.get(id);
    updateRow(id);
    if (after.staged === null) {
      setError(
        `Conflict: ${after.email} was changed by someone else and is now ${after.committed}. ` +
        `Your pending change to ${attempted} matches that and was dropped. Nothing was applied by you.`
      );
    } else {
      setError(
        `Conflict: ${after.email} was changed by someone else and is now ${after.committed}. ` +
        `Your pending change to ${attempted} was NOT applied and is still staged. ` +
        'Review it and press Save again to apply it to the current version.'
      );
    }
    return;
  }

  updateRow(id);
  const reason = res.status === 0 ? 'network error' : `HTTP ${res.status}`;
  setError(
    `Save failed (${reason}). Nothing was changed. Your pending change to ${attempted} ` +
    'is still staged: press Save to retry or Discard to drop it.'
  );
}

async function refreshUser(id) {
  const { ok, body } = await api('/api/users');
  if (!ok) return;
  const fresh = (body.users || []).find((u) => u.id === id);
  if (!fresh) return;
  const s = state.get(id);
  s.committed = fresh.role;
  s.version = fresh.version;
  if (s.staged === s.committed) s.staged = null;
}

async function load() {
  const tbody = document.querySelector('#users-table tbody');
  tbody.textContent = '';
  const { ok, body } = await api('/api/users');
  if (!ok) {
    setError('Could not load users. Reload the page to try again.');
    return;
  }
  for (const user of body.users || []) {
    state.set(user.id, {
      email: user.email,
      committed: user.role,
      version: user.version,
      staged: null,
      busy: false,
    });
  }
  for (const user of body.users || []) {
    tbody.appendChild(renderRow(user));
    updateRow(user.id);
  }
}

load();
