'use strict';
/*
 * Access-management screen, contract-compliant reference implementation.
 *
 * Invariants:
 *  - the dropdown only stages a local change; nothing is sent until the administrator
 *    activates the apply control;
 *  - a change that grants or removes 'admin' needs an explicit in-page confirmation;
 *  - exactly one request per accepted apply, guarded against duplicate submits;
 *  - a failure or conflict is reported and the staged change is kept, never claimed as saved.
 */

const ROLES = ['viewer', 'analyst', 'admin'];
const state = new Map(); // user id -> row state

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, body };
}

function setStatus(text) {
  document.getElementById('status').textContent = text || '';
}

function setError(text) {
  document.getElementById('error').textContent = text || '';
}

function isSensitive(original, staged) {
  return original !== staged && (original === 'admin' || staged === 'admin');
}

function buildRow(user) {
  const row = document.createElement('tr');
  row.dataset.userId = user.id;

  const emailCell = document.createElement('td');
  emailCell.textContent = user.email;

  const roleCell = document.createElement('td');
  const select = document.createElement('select');
  select.id = `role-${user.id}`;
  select.setAttribute('aria-label', `Access level for ${user.email}`);
  for (const role of ROLES) {
    const option = document.createElement('option');
    option.value = role;
    option.textContent = role;
    if (role === user.role) option.selected = true;
    select.appendChild(option);
  }

  const pending = document.createElement('span');
  pending.id = `pending-${user.id}`;
  pending.className = 'pending';
  pending.hidden = true;
  pending.textContent = 'not applied yet';

  roleCell.append(select, pending);

  const actions = document.createElement('td');
  actions.className = 'actions';

  const loading = document.createElement('span');
  loading.id = `loading-${user.id}`;
  loading.className = 'loading';
  loading.hidden = true;
  loading.textContent = 'saving…';

  const save = document.createElement('button');
  save.type = 'button';
  save.id = `save-${user.id}`;
  save.textContent = 'Apply';

  const cancel = document.createElement('button');
  cancel.type = 'button';
  cancel.id = `cancel-${user.id}`;
  cancel.textContent = 'Discard';

  const confirm = document.createElement('span');
  confirm.id = `confirm-${user.id}`;
  confirm.className = 'confirm';
  confirm.hidden = true;

  const confirmText = document.createElement('span');
  confirmText.textContent = `Grant or remove admin access for ${user.email}? `;

  const confirmYes = document.createElement('button');
  confirmYes.type = 'button';
  confirmYes.dataset.confirm = 'yes';
  confirmYes.textContent = 'Confirm change';

  const confirmNo = document.createElement('button');
  confirmNo.type = 'button';
  confirmNo.textContent = 'Keep original';

  confirm.append(confirmText, confirmYes, confirmNo);
  actions.append(loading, save, cancel, confirm);

  const rowState = {
    original: user.role,
    staged: user.role,
    version: user.version,
    saving: false,
    confirmed: false,
    email: user.email,
  };
  state.set(user.id, rowState);

  const refresh = () => {
    const staged = rowState.staged;
    const dirty = staged !== rowState.original;
    pending.hidden = !dirty;
    confirm.hidden = !(dirty && isSensitive(rowState.original, staged) && !rowState.confirmed);
    cancel.disabled = !dirty || rowState.saving;
    save.disabled = rowState.saving;
    loading.hidden = !rowState.saving;
    if (select.value !== staged) select.value = staged;
  };

  select.addEventListener('change', () => {
    rowState.staged = select.value;
    rowState.confirmed = false;
    setError('');
    setStatus('');
    refresh();
  });

  cancel.addEventListener('click', () => {
    if (rowState.saving) return;
    rowState.staged = rowState.original;
    rowState.confirmed = false;
    setError('');
    refresh();
  });

  confirmYes.addEventListener('click', () => {
    rowState.confirmed = true;
    refresh();
  });

  confirmNo.addEventListener('click', () => {
    rowState.staged = rowState.original;
    rowState.confirmed = false;
    refresh();
  });

  save.addEventListener('click', async () => {
    if (rowState.saving) return;
    if (rowState.staged === rowState.original) return;
    if (isSensitive(rowState.original, rowState.staged) && !rowState.confirmed) {
      refresh();
      setError('Confirm the administrative change before applying it.');
      return;
    }
    rowState.saving = true;
    setError('');
    refresh();
    const result = await api(`/api/users/${user.id}/role`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role: rowState.staged, version: rowState.version }),
    });
    rowState.saving = false;
    if (result.ok) {
      rowState.original = result.body.user ? result.body.user.role : rowState.staged;
      rowState.staged = rowState.original;
      rowState.version = result.body.user ? result.body.user.version : rowState.version;
      rowState.confirmed = false;
      setStatus(`Saved. ${user.email} is now ${rowState.original}.`);
    } else if (result.status === 409) {
      setError('This access level changed elsewhere (conflict). Reload the page and try again.');
    } else if (result.status === 400) {
      setError(`The change was rejected: ${result.body.error || 'invalid request'}.`);
    } else {
      setError('The change could not be saved. Nothing was applied; try again.');
    }
    refresh();
  });

  refresh();
  row.append(emailCell, roleCell, actions);
  return row;
}

async function render() {
  const tbody = document.querySelector('#users-table tbody');
  tbody.textContent = '';
  const { body } = await api('/api/users');
  for (const user of body.users || []) tbody.appendChild(buildRow(user));
}

render();
