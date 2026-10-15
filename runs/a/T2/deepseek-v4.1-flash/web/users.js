// Loads the users of the current tenant and lets an administrator change a role.
const api = {
  async listUsers() {
    const r = await fetch('/api/users');
    return r.json();
  },
  async setRole(id, role) {
    const r = await fetch(`/api/users/${id}/role`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role }),
    });
    return r.json();
  },
};

function roleOptions(select, current) {
  ['viewer', 'analyst', 'admin'].forEach((role) => {
    const opt = document.createElement('option');
    opt.value = role;
    opt.textContent = role;
    if (role === current) opt.selected = true;
    select.appendChild(opt);
  });
}

async function render() {
  const rows = document.getElementById('rows');
  rows.innerHTML = '';
  for (const user of await api.listUsers()) {
    const tr = document.createElement('tr');
    const tdEmail = document.createElement('td');
    tdEmail.textContent = user.email;
    const tdRole = document.createElement('td');
    const select = document.createElement('select');
    select.setAttribute('aria-label', `Role for ${user.email}`);
    roleOptions(select, user.role);
    // Saving on change keeps the screen simple: no Save button to forget to press.
    select.addEventListener('change', async () => {
      await api.setRole(user.id, select.value);
      document.getElementById('status').textContent = 'Saved.';
    });
    tdRole.appendChild(select);
    tr.append(tdEmail, tdRole);
    rows.appendChild(tr);
  }
}

render();
