// Tela de usuarios: listar, criar, editar (nome/papel/senha/ativo) e remover.

import { api } from '/api.js';
import {
  checkboxField,
  confirmAction,
  empty,
  esc,
  field,
  fmtDateTime,
  loading,
  openModal,
  qs,
  readForm,
  selectField,
  showError,
  toast,
} from '/ui.js';

const ROLES = [['viewer', 'viewer'], ['operator', 'operator'], ['editor', 'editor'], ['admin', 'admin']];

function userForm(user) {
  const isEdit = Boolean(user && user.id);
  return `
    <form id="user-form">
      ${
        isEdit
          ? `<p class="muted">${esc(user.email)}</p>`
          : field('E-mail', 'email', { type: 'email', required: true })
      }
      ${field('Nome', 'name', { value: (user && user.name) || '' })}
      ${selectField('Papel', 'role', ROLES, (user && user.role) || 'viewer')}
      ${field(isEdit ? 'Nova senha (opcional)' : 'Senha', 'password', { type: 'password', required: !isEdit })}
      ${checkboxField('Ativo', 'is_active', !user || user.is_active !== false)}
      <div class="modal__actions"><button type="submit" class="btn btn--primary">${isEdit ? 'Salvar' : 'Criar usuário'}</button></div>
    </form>`;
}

function openUserModal(user, reload) {
  const isEdit = Boolean(user && user.id);
  openModal(isEdit ? 'Editar usuário' : 'Novo usuário', userForm(user), {
    onMount(body, close) {
      const form = qs('#user-form', body);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const values = readForm(form);
        try {
          if (isEdit) {
            const payload = { name: values.name, role: values.role, is_active: values.is_active };
            if (values.password) payload.password = values.password;
            await api.updateUser(user.id, payload);
            toast('Usuário atualizado.', 'success');
          } else {
            await api.createUser({
              email: values.email,
              name: values.name,
              password: values.password,
              role: values.role,
              is_active: values.is_active,
            });
            toast('Usuário criado.', 'success');
          }
          close();
          await reload();
        } catch (err) {
          showError(err);
        }
      });
    },
  });
}

export async function renderUsers(view) {
  view.innerHTML = loading('carregando usuários…');
  const users = await api.listUsers();

  view.innerHTML = `
    <section class="card">
      <div class="card__head">
        <h2>Usuários</h2>
        <button class="btn btn--primary" id="btn-new-user">Novo usuário</button>
      </div>
      <table class="table">
        <thead><tr><th>Id</th><th>E-mail</th><th>Nome</th><th>Papel</th><th>Ativo</th><th>Troca de senha</th><th>Último login</th><th></th></tr></thead>
        <tbody>
          ${users
            .map(
              (user) => `
            <tr>
              <td>${esc(user.id)}</td>
              <td>${esc(user.email)}</td>
              <td>${esc(user.name)}</td>
              <td><span class="role role--${esc(user.role)}">${esc(user.role)}</span></td>
              <td>${user.is_active ? '<span class="pill pill--ok">ativo</span>' : '<span class="pill">inativo</span>'}</td>
              <td>${user.must_change_password ? '<span class="pill pill--warn">pendente</span>' : '<span class="muted">—</span>'}</td>
              <td>${esc(fmtDateTime(user.last_login_at))}</td>
              <td class="table__actions">
                <button class="btn btn--sm" data-action="edit" data-id="${esc(user.id)}">Editar</button>
                <button class="btn btn--sm btn--danger" data-action="delete" data-id="${esc(user.id)}">Remover</button>
              </td>
            </tr>`,
            )
            .join('')}
        </tbody>
      </table>
    </section>`;

  const reload = () => renderUsers(view);
  qs('#btn-new-user', view).addEventListener('click', () => openUserModal(null, reload));

  view.querySelectorAll('[data-action="edit"]').forEach((button) => {
    button.addEventListener('click', () => {
      const user = users.find((item) => item.id === Number(button.dataset.id));
      openUserModal(user, reload);
    });
  });

  view.querySelectorAll('[data-action="delete"]').forEach((button) => {
    button.addEventListener('click', async () => {
      const user = users.find((item) => item.id === Number(button.dataset.id));
      if (!confirmAction(`Remover o usuário "${user.email}"?`)) return;
      try {
        await api.deleteUser(user.id);
        toast('Usuário removido.', 'success');
        await reload();
      } catch (err) {
        showError(err);
      }
    });
  });
}
