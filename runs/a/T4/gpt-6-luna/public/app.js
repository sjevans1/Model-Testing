'use strict';

const ROLES = ['viewer', 'analyst', 'admin'];

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  return { ok: response.ok, status: response.status, body };
}

function roleSelect(user) {
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
  return select;
}

function setMessage(id, message) {
  document.getElementById(id).textContent = message;
}

function makeButton(id, label, text, onClick) {
  const button = document.createElement('button');
  button.id = id;
  button.type = 'button';
  button.setAttribute('aria-label', label);
  button.textContent = text;
  button.addEventListener('click', onClick);
  return button;
}

function renderRowState(state) {
  const { user, select, actions } = state;
  const pending = select.value !== user.role;
  const sensitive = pending && ((user.role === 'admin') !== (select.value === 'admin'));
  actions.textContent = '';

  if (pending) {
    const pendingLabel = document.createElement('span');
    pendingLabel.id = `pending-${user.id}`;
    pendingLabel.className = 'pending';
    pendingLabel.textContent = `Pending: ${select.value}`;
    actions.appendChild(pendingLabel);
  }

  if (sensitive) {
    const confirmation = document.createElement('div');
    confirmation.id = `confirm-${user.id}`;
    confirmation.className = 'confirmation';
    const confirmButton = makeButton(
      `confirm-action-${user.id}`,
      `Confirm ${select.value === 'admin' ? 'granting' : 'removing'} administrator access for ${user.email}`,
      state.confirmed ? 'Confirmed' : 'Confirm admin change',
      () => {
        if (state.busy) return;
        state.confirmed = true;
        renderRowState(state);
      },
    );
    confirmButton.dataset.confirm = state.confirmed ? 'yes' : 'no';
    confirmButton.disabled = state.busy || state.confirmed;
    confirmation.appendChild(confirmButton);
    actions.appendChild(confirmation);
  }

  const apply = makeButton(
    `save-${user.id}`,
    `Apply access level change for ${user.email}`,
    'Apply',
    () => submit(state),
  );
  apply.disabled = !pending || state.busy || (sensitive && !state.confirmed);
  actions.appendChild(apply);

  const cancel = makeButton(
    `cancel-${user.id}`,
    `Discard access level change for ${user.email}`,
    'Discard',
    () => discard(state),
  );
  cancel.disabled = !pending || state.busy;
  actions.appendChild(cancel);

  if (state.busy) {
    const loading = document.createElement('span');
    loading.id = `loading-${user.id}`;
    loading.className = 'loading';
    loading.setAttribute('role', 'status');
    loading.textContent = 'Saving…';
    actions.appendChild(loading);
  }

  select.disabled = state.busy;
}

function discard(state) {
  if (state.busy) return;
  state.select.value = state.user.role;
  state.confirmed = false;
  setMessage('status', '');
  setMessage('error', '');
  renderRowState(state);
}

async function submit(state) {
  const { user, select } = state;
  const nextRole = select.value;
  const pending = nextRole !== user.role;
  const sensitive = pending && ((user.role === 'admin') !== (nextRole === 'admin'));
  if (!pending || state.busy || (sensitive && !state.confirmed)) return;

  state.busy = true;
  setMessage('status', '');
  setMessage('error', '');
  renderRowState(state);

  try {
    const result = await api(`/api/users/${encodeURIComponent(user.id)}/role`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role: nextRole, version: user.version }),
    });
    if (result.status === 409) {
      setMessage('error', 'This user was changed elsewhere (stale version). Your change is still pending; refresh the user data before applying it again.');
    } else if (!result.ok) {
      setMessage('error', `Could not save the change (HTTP ${result.status || 'network error'}). Your change is still pending; try again.`);
    } else if (!result.body.user) {
      setMessage('error', 'The server returned an invalid response. Your change is still pending; try again.');
    } else {
      user.role = result.body.user.role;
      user.version = result.body.user.version;
      select.value = user.role;
      state.confirmed = false;
      setMessage('status', 'Access level saved.');
    }
  } catch (error) {
    setMessage('error', 'Could not save the change because of a network error. Your change is still pending; try again.');
  } finally {
    state.busy = false;
    renderRowState(state);
  }
}

async function render() {
  const tbody = document.querySelector('#users-table tbody');
  tbody.textContent = '';
  try {
    const { body, ok } = await api('/api/users');
    if (!ok || !Array.isArray(body.users)) throw new Error('Unable to load users');
    for (const user of body.users) {
      const row = document.createElement('tr');
      row.dataset.userId = user.id;

      const email = document.createElement('td');
      email.dataset.label = 'Email';
      email.textContent = user.email;

      const roleCell = document.createElement('td');
      roleCell.dataset.label = 'Access level';
      const select = roleSelect(user);
      roleCell.appendChild(select);

      const actions = document.createElement('td');
      actions.dataset.label = 'Actions';
      const state = { user: { ...user }, select, actions, confirmed: false, busy: false };
      select.addEventListener('change', () => {
        state.confirmed = false;
        setMessage('status', '');
        setMessage('error', '');
        renderRowState(state);
      });
      renderRowState(state);
      row.append(email, roleCell, actions);
      tbody.appendChild(row);
    }
  } catch (error) {
    setMessage('error', 'Could not load users. Please reload the page.');
  }
}

render();
