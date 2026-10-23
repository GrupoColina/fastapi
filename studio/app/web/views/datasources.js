// Tela de fontes de dados: CRUD, teste de conexao, descoberta e allow-list de objetos.

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
  textareaField,
  toast,
} from '/ui.js';

const KINDS = [
  ['sqlserver', 'SQL Server'],
  ['sqlite', 'SQLite'],
];

function projectSelectHtml(projects, selectedId) {
  const options = projects
    .map((p) => `<option value="${esc(p.id)}" ${p.id === selectedId ? 'selected' : ''}>${esc(p.name)} (${esc(p.slug)})</option>`)
    .join('');
  return `<label class="field field--inline"><span>Projeto</span><select id="project-select">${options}</select></label>`;
}

function datasourceModal(source, onDone) {
  const isEdit = Boolean(source && source.id);
  const kind = (source && source.kind) || 'sqlserver';
  const options = (source && source.options) || {};
  return {
    html: `
      <form id="datasource-form">
        ${isEdit ? '' : field('Slug', 'slug', { required: true, placeholder: 'erp-prod' })}
        ${field('Nome', 'name', { value: (source && source.name) || '', required: true })}
        ${selectField('Tipo', 'kind', KINDS, kind)}
        <div data-role="group-sqlserver" ${kind === 'sqlserver' ? '' : 'hidden'}>
          <div class="row row--2">
            ${field('Host', 'host', { value: (source && source.host) || '' })}
            ${field('Porta', 'port', { value: source && source.port != null ? source.port : 1433, datatype: 'int' })}
          </div>
          ${field('Banco de dados', 'database', { value: (source && source.database) || '' })}
          <div class="row row--2">
            ${field('Usuário', 'username', { value: (source && source.username) || '' })}
            ${field('Senha', 'password', { type: 'password', placeholder: isEdit ? 'deixe vazio para manter' : '' })}
          </div>
          <div class="row row--2">
            ${checkboxField('Encrypt', 'encrypt', options.encrypt !== false)}
            ${checkboxField('Trust server certificate', 'trust_server_certificate', Boolean(options.trust_server_certificate))}
          </div>
          ${field('Schemas a descobrir (vírgula)', 'discover_schemas', { value: (source && source.discover_schemas || []).join(', '), list: true })}
        </div>
        <div data-role="group-sqlite" ${kind === 'sqlite' ? '' : 'hidden'}>
          ${textareaField('Caminho do arquivo', 'file_path', (source && source.file_path) || '', 2)}
        </div>
        <div class="row row--2">
          ${checkboxField('Ativa', 'is_active', !source || source.is_active !== false)}
          ${checkboxField('Permitir escrita', 'allow_write', Boolean(source && source.allow_write))}
        </div>
        <div class="modal__actions"><button type="submit" class="btn btn--primary">${isEdit ? 'Salvar' : 'Criar fonte'}</button></div>
      </form>`,
    onMount(body, close) {
      const form = qs('#datasource-form', body);
      const kindSelect = form.elements.namedItem('kind');
      kindSelect.addEventListener('change', () => {
        const value = kindSelect.value;
        qs('[data-role="group-sqlserver"]', body).hidden = value !== 'sqlserver';
        qs('[data-role="group-sqlite"]', body).hidden = value !== 'sqlite';
      });
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const values = readForm(form);
        const payload = {
          name: values.name,
          kind: values.kind,
          is_active: values.is_active,
          allow_write: values.allow_write,
        };
        if (!isEdit) payload.slug = values.slug;
        if (values.kind === 'sqlserver') {
          payload.host = values.host;
          payload.port = values.port;
          payload.database = values.database;
          payload.username = values.username;
          if (!isEdit || values.password !== '') payload.password = values.password;
          payload.options = {
            encrypt: Boolean(values.encrypt),
            trust_server_certificate: Boolean(values.trust_server_certificate),
          };
          payload.discover_schemas = values.discover_schemas || [];
        } else if (values.kind === 'sqlite') {
          payload.file_path = values.file_path;
        }
        try {
          if (isEdit) {
            await api.updateDatasource(source.id, payload);
            toast('Fonte atualizada.', 'success');
          } else {
            await api.createDatasource(payload);
            toast('Fonte criada.', 'success');
          }
          close();
          await onDone();
        } catch (err) {
          showError(err);
        }
      });
    },
  };
}

function showTestResult(source, result) {
  openModal(
    `Teste de conexão · ${source.name}`,
    `
    <p>${result.ok ? '<span class="pill pill--ok">ok</span>' : '<span class="pill pill--err">falhou</span>'}</p>
    <dl class="kv">
      <dt>Mensagem</dt><dd>${esc(result.message)}</dd>
      <dt>Latência (ms)</dt><dd>${esc(result.latency_ms)}</dd>
      <dt>Versão do servidor</dt><dd>${esc(result.server_version || '—')}</dd>
      <dt>Driver</dt><dd>${esc(result.driver || '—')}</dd>
    </dl>`,
  );
}

function objectsHtml(objects) {
  if (!objects.length) return empty('Nenhum objeto descoberto.');
  return `<table class="table">
    <thead><tr><th></th><th>Schema</th><th>Objeto</th><th>Tipo</th><th>Colunas</th><th>Autorizado</th><th></th></tr></thead>
    <tbody>
      ${objects
        .map(
          (obj) => `
        <tr>
          <td><input type="checkbox" class="object-check" value="${esc(obj.id)}"></td>
          <td>${esc(obj.schema_name)}</td>
          <td>${esc(obj.object_name)}</td>
          <td>${esc(obj.object_type)}</td>
          <td class="columns-cell">
            ${(obj.columns || [])
              .map((c) => `<span class="col-chip" title="${esc(c.native_type)}">${esc(c.name)}: ${esc(c.type)}</span>`)
              .join('')}
          </td>
          <td>${obj.allowed ? '<span class="pill pill--ok">sim</span>' : '<span class="pill">não</span>'}</td>
          <td class="table__actions"><button class="btn btn--sm" data-action="toggle-one" data-id="${esc(obj.id)}" data-allowed="${obj.allowed ? 'true' : 'false'}">${obj.allowed ? 'Desautorizar' : 'Autorizar'}</button></td>
        </tr>`,
        )
        .join('')}
    </tbody>
  </table>`;
}

export async function renderDatasources(view, params) {
  view.innerHTML = loading('carregando fontes de dados…');
  const projects = await api.listProjects();
  if (!projects.length) {
    view.innerHTML = empty('Cadastre um projeto antes de criar fontes de dados.');
    return;
  }
  const selectedId = params[0] ? Number(params[0]) : projects[0].id;
  const sources = await api.listDatasources(selectedId);

  view.innerHTML = `
    <section class="card">
      <div class="card__head">
        <h2>Fontes de dados</h2>
        <button class="btn btn--primary" id="btn-new-source">Nova fonte</button>
      </div>
      ${projectSelectHtml(projects, selectedId)}
      ${
        sources.length
          ? `<table class="table">
              <thead><tr><th>Id</th><th>Slug</th><th>Nome</th><th>Tipo</th><th>Alvo</th><th>Último teste</th><th></th></tr></thead>
              <tbody>
                ${sources
                  .map(
                    (source) => `
                  <tr>
                    <td>${esc(source.id)}</td>
                    <td><code>${esc(source.slug)}</code></td>
                    <td>${esc(source.name)}</td>
                    <td>${esc(source.kind)}</td>
                    <td>${esc(source.kind === 'sqlite' ? source.file_path : `${source.host}:${source.port || ''}/${source.database}`)}</td>
                    <td>${
                      source.last_test_at
                        ? `${source.last_test_ok ? '<span class="pill pill--ok">ok</span>' : '<span class="pill pill--err">falhou</span>'} <span class="muted">${esc(fmtDateTime(source.last_test_at))}</span>`
                        : '<span class="muted">nunca testada</span>'
                    }</td>
                    <td class="table__actions">
                      <button class="btn btn--sm" data-action="test" data-id="${esc(source.id)}">Testar conexão</button>
                      <button class="btn btn--sm" data-action="discover" data-id="${esc(source.id)}">Descobrir objetos</button>
                      <button class="btn btn--sm" data-action="objects" data-id="${esc(source.id)}">Objetos</button>
                      <button class="btn btn--sm" data-action="edit" data-id="${esc(source.id)}">Editar</button>
                      <button class="btn btn--sm btn--danger" data-action="delete" data-id="${esc(source.id)}">Remover</button>
                    </td>
                  </tr>`,
                  )
                  .join('')}
              </tbody>
            </table>`
          : empty('Nenhuma fonte de dados neste projeto.')
      }
    </section>
    <section class="card" id="objects-panel" hidden></section>`;

  const reload = () => renderDatasources(view, [String(selectedId)]);
  const findSource = (id) => sources.find((item) => item.id === Number(id));

  qs('#project-select', view).addEventListener('change', (event) => {
    location.hash = `#/fontes/${event.target.value}`;
  });

  const modal = datasourceModal(null, reload);
  qs('#btn-new-source', view).addEventListener('click', () => openModal('Nova fonte de dados', modal.html, { onMount: modal.onMount }));

  async function showObjects(sourceId) {
    const panel = qs('#objects-panel', view);
    panel.hidden = false;
    panel.innerHTML = loading('carregando objetos…');
    const source = findSource(sourceId);
    try {
      const objects = await api.listObjects(sourceId, {});
      panel.innerHTML = `
        <div class="card__head">
          <h3>Objetos de ${esc(source ? source.name : sourceId)}</h3>
          <div class="table__actions">
            <button class="btn btn--sm" data-action="authorize-sel" data-mode="allow">Autorizar selecionados</button>
            <button class="btn btn--sm btn--danger" data-action="authorize-sel" data-mode="deny">Desautorizar selecionados</button>
          </div>
        </div>
        ${objectsHtml(objects)}`;

      const selectedIds = () =>
        Array.from(panel.querySelectorAll('.object-check:checked')).map((c) => Number(c.value));

      panel.querySelectorAll('[data-action="authorize-sel"]').forEach((button) => {
        button.addEventListener('click', async () => {
          const ids = selectedIds();
          if (!ids.length) {
            toast('Selecione ao menos um objeto.', 'error');
            return;
          }
          try {
            const result = await api.authorizeObjects(sourceId, ids, button.dataset.mode === 'allow');
            toast(`Objetos atualizados: ${result.updated}.`, 'success');
            await showObjects(sourceId);
          } catch (err) {
            showError(err);
          }
        });
      });

      panel.querySelectorAll('[data-action="toggle-one"]').forEach((button) => {
        button.addEventListener('click', async () => {
          const ids = [Number(button.dataset.id)];
          try {
            await api.authorizeObjects(sourceId, ids, button.dataset.allowed !== 'true');
            await showObjects(sourceId);
          } catch (err) {
            showError(err);
          }
        });
      });
    } catch (err) {
      panel.innerHTML = empty('Falha ao carregar objetos.');
      showError(err);
    }
  }

  view.querySelectorAll('[data-action="test"]').forEach((button) => {
    button.addEventListener('click', async () => {
      const source = findSource(button.dataset.id);
      button.disabled = true;
      try {
        const result = await api.testDatasource(source.id);
        showTestResult(source, result);
      } catch (err) {
        showError(err);
      } finally {
        button.disabled = false;
      }
    });
  });

  view.querySelectorAll('[data-action="discover"]').forEach((button) => {
    button.addEventListener('click', async () => {
      const source = findSource(button.dataset.id);
      button.disabled = true;
      try {
        const result = await api.discoverDatasource(source.id, source.discover_schemas || []);
        toast(
          `Descoberta concluída: ${result.objects} objetos (${result.tables} tabelas, ${result.views} views, ${result.procedures} procedures) em ${result.duration_ms} ms.`,
          'success',
        );
        await showObjects(source.id);
      } catch (err) {
        showError(err);
      } finally {
        button.disabled = false;
      }
    });
  });

  view.querySelectorAll('[data-action="objects"]').forEach((button) => {
    button.addEventListener('click', () => showObjects(Number(button.dataset.id)));
  });

  view.querySelectorAll('[data-action="edit"]').forEach((button) => {
    button.addEventListener('click', () => {
      const source = findSource(button.dataset.id);
      const modalEdit = datasourceModal(source, reload);
      openModal('Editar fonte de dados', modalEdit.html, { onMount: modalEdit.onMount });
    });
  });

  view.querySelectorAll('[data-action="delete"]').forEach((button) => {
    button.addEventListener('click', async () => {
      const source = findSource(button.dataset.id);
      if (!confirmAction(`Remover a fonte "${source.name}"?`)) return;
      try {
        await api.deleteDatasource(source.id);
        toast('Fonte removida.', 'success');
        await reload();
      } catch (err) {
        showError(err);
      }
    });
  });
}
