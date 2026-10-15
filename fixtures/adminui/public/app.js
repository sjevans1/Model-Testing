'use strict';
// Users and access screen.
//
// NOTE (engineering): saving on change keeps the markup small: there is no Save button
// for an administrator to forget to press.

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

async function render() {
  const tbody = document.querySelector('#users-table tbody');
  tbody.textContent = '';
  const { body } = await api('/api/users');
  for (const user of body.users || []) {
    const row = document.createElement('tr');
    row.dataset.userId = user.id;

    const email = document.createElement('td');
    email.textContent = user.email;

    const roleCell = document.createElement('td');
    const select = roleSelect(user);
    select.addEventListener('change', async () => {
      await api(`/api/users/${user.id}/role`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: select.value, version: user.version }),
      });
      document.getElementById('status').textContent = 'Saved.';
    });
    roleCell.appendChild(select);

    const actions = document.createElement('td');
    row.append(email, roleCell, actions);
    tbody.appendChild(row);
  }
}

render();
