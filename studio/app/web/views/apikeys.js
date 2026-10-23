// Tela de API keys: listar, criar (mostrando o segredo uma unica vez), revogar e remover.

import { api } from '/api.js';
import {
  confirmAction,
  copyText,
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

const ENVIRONMENTS = [['live', 'live'], ['test', 'test']];

function projectSelectHtml(projects, selectedId) {
  const options = [
    `<option value="">todos os projetos</option>`,
    ...projects.map((p) => `<option value="${esc(p.id)}" ${p.id === selectedId ? 'selected' : ''}>${esc(p.name)} (${esc(p.slug)})</option>`),
  ].join('');
  return `<label class="field field--inline"><span>Projeto</span><select id="project-select">${options}</select></label>`;
}

function showPlaintextModal(created) {
  openModal(
    'API key criada',
    `
    <div class="alert alert--warn"><strong>Atenção:</strong> o segredo abaixo é exibido uma única vez. Copie e guarde agora.</div>
    <label class="field"><span>Segredo</span><input id="key-plaintext" value="${esc(created.plaintext)}" readonly></label>
    <div class="modal__actions">
      <button class="btn btn--primary" id="copy-key">Copiar segredo</button>
    </div>
    <dl class="kv">
      <dt>Prefixo</dt><dd><code>${esc(created.key_prefix)}</code></dd>
      <dt>Ambiente</dt><dd>${esc(created.environment)}</dd>
      <dt>Projeto</dt><dd>${created.project_id ?? '—'}</dd>
    </dl>`,
    {
      onMount(body) {
        qs('#copy-key', body).addEventListener('click', () => copyText(created.plaintext));
      },
    },
  );
}

export async function renderApiKeys(view, params) {
  view.innerHTML = loading('carregando API keys…');
  const projects = await api.listProjects();
  const selectedId = params[0] ? Number(params[0]) : null;
  const keys = await api.listApiKeys(selectedId);

  view.innerHTML = `
    <section class="card">
      <div class="card__head">
        <h2>API keys</h2>
        <button class="btn btn--primary" id="btn-new-key">Nova API key</button>
      </div>
      ${projectSelectHtml(projects, selectedId)}
      ${
        keys.length
          ? `<table class="table">
              <thead><tr><th>Id</th><th>Nome</th><th>Prefixo</th><th>Ambiente</th><th>Projeto</th><th>Escopos</th><th>Ativa</th><th>Usos</th><th>Criada</th><th></th></tr></thead>
              <tbody>
                ${keys
                  .map(
                    (key) => `
                  <tr>
                    <td>${esc(key.id)}</td>
                    <td>${esc(key.name)}</td>
                    <td><code>${esc(key.key_prefix)}…</code></td>
                    <td>${esc(key.environment)}</td>
                    <td>${key.project_id ?? '—'}</td>
                    <td>${(key.scopes || []).map((s) => `<span class="pill">${esc(s)}</span>`).join(' ') || '<span class="muted">—</span>'}</td>
                    <td>${key.is_active ? '<span class="pill pill--ok">ativa</span>' : '<span class="pill pill--err">revogada</span>'}</td>
                    <td>${esc(key.usage_count)}</td>
                    <td>${esc(fmtDateTime(key.created_at))}</td>
                    <td class="table__actions">
                      ${key.is_active ? `<button class="btn btn--sm" data-action="revoke" data-id="${esc(key.id)}">Revogar</button>` : ''}
                      <button class="btn btn--sm btn--danger" data-action="delete" data-id="${esc(key.id)}">Remover</button>
                    </td>
                  </tr>`,
                  )
                  .join('')}
              </tbody>
            </table>`
          : empty('Nenhuma API key encontrada.')
      }
    </section>`;

  const reload = () => renderApiKeys(view, selectedId ? [String(selectedId)] : []);

  qs('#project-select', view).addEventListener('change', (event) => {
    location.hash = event.target.value ? `#/chaves/${event.target.value}` : '#/chaves';
  });

  qs('#btn-new-key', view).addEventListener('click', () => {
    openModal(
      'Nova API key',
      `
      <form id="apikey-form">
        ${field('Nome', 'name', { required: true })}
        <label class="field"><span>Projeto</span>
          <select name="project_id">
            <option value="">— sem projeto (global) —</option>
            ${projects.map((p) => `<option value="${esc(p.id)}" ${p.id === selectedId ? 'selected' : ''}>${esc(p.name)} (${esc(p.slug)})</option>`).join('')}
          </select>
        </label>
        ${selectField('Ambiente', 'environment', ENVIRONMENTS, 'live')}
        ${field('Escopos (vírgula)', 'scopes', { list: true })}
        ${field('Expira em (ISO, opcional)', 'expires_at', { placeholder: '2026-12-31T23:59:59' })}
        <div class="modal__actions"><button type="submit" class="btn btn--primary">Criar</button></div>
      </form>`,
      {
        onMount(body, close) {
          const form = qs('#apikey-form', body);
          form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const values = readForm(form);
            const payload = {
              name: values.name,
              environment: values.environment,
              scopes: values.scopes || [],
            };
            if (values.project_id !== '') payload.project_id = Number(values.project_id);
            if (values.expires_at) payload.expires_at = values.expires_at;
            try {
              const created = await api.createApiKey(payload);
              close();
              showPlaintextModal(created);
              await reload();
            } catch (err) {
              showError(err);
            }
          });
        },
      },
    );
  });

  view.querySelectorAll('[data-action="revoke"]').forEach((button) => {
    button.addEventListener('click', async () => {
      if (!confirmAction('Revogar esta API key? A ação não pode ser desfeita.')) return;
      try {
        await api.revokeApiKey(Number(button.dataset.id));
        toast('API key revogada.', 'success');
        await reload();
      } catch (err) {
        showError(err);
      }
    });
  });

  view.querySelectorAll('[data-action="delete"]').forEach((button) => {
    button.addEventListener('click', async () => {
      if (!confirmAction('Remover definitivamente esta API key?')) return;
      try {
        await api.deleteApiKey(Number(button.dataset.id));
        toast('API key removida.', 'success');
        await reload();
      } catch (err) {
        showError(err);
      }
    });
  });
}
