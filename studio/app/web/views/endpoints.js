// Tela de endpoints: lista por projeto e criacao com o construtor visual de definicao.

import { api } from '/api.js';
import { createDefinitionEditor } from '/definition-editor.js';
import {
  checkboxField,
  confirmAction,
  empty,
  esc,
  field,
  loading,
  qs,
  readForm,
  selectField,
  showError,
  toast,
} from '/ui.js';

const METHODS = [['GET', 'GET'], ['POST', 'POST'], ['PUT', 'PUT'], ['PATCH', 'PATCH'], ['DELETE', 'DELETE']];

function projectSelectHtml(projects, selectedId) {
  const options = projects
    .map((p) => `<option value="${esc(p.id)}" ${p.id === selectedId ? 'selected' : ''}>${esc(p.name)} (${esc(p.slug)})</option>`)
    .join('');
  return `<label class="field field--inline"><span>Projeto</span><select id="project-select">${options}</select></label>`;
}

function datasourceSelectHtml(sources, selectedId) {
  const options = [
    `<option value="">— sem fonte —</option>`,
    ...sources.map((s) => `<option value="${esc(s.id)}" ${s.id === selectedId ? 'selected' : ''}>${esc(s.name)} (${esc(s.kind)})</option>`),
  ].join('');
  return `<label class="field field--inline"><span>Fonte de dados</span><select id="datasource-select">${options}</select></label>`;
}

export async function renderEndpoints(view, params) {
  view.innerHTML = loading('carregando endpoints…');
  const projects = await api.listProjects();
  if (!projects.length) {
    view.innerHTML = empty('Cadastre um projeto antes de criar endpoints.');
    return;
  }
  const selectedId = params[0] ? Number(params[0]) : projects[0].id;
  const [endpoints, sources] = await Promise.all([
    api.listEndpoints(selectedId),
    api.listDatasources(selectedId),
  ]);

  view.innerHTML = `
    <section class="card">
      <div class="card__head">
        <h2>Endpoints</h2>
        <button class="btn btn--primary" id="btn-toggle-create">Novo endpoint</button>
      </div>
      ${projectSelectHtml(projects, selectedId)}
      <div id="create-panel" hidden></div>
      ${
        endpoints.length
          ? `<table class="table">
              <thead><tr><th>Id</th><th>Slug</th><th>Método</th><th>Path</th><th>Runtime</th><th>Publicado</th><th>Ativo</th><th></th></tr></thead>
              <tbody>
                ${endpoints
                  .map(
                    (endpoint) => `
                  <tr>
                    <td>${esc(endpoint.id)}</td>
                    <td><code>${esc(endpoint.slug)}</code></td>
                    <td><span class="method">${esc(endpoint.http_method)}</span></td>
                    <td><code>${esc(endpoint.path)}</code></td>
                    <td>
                      <code>${esc(endpoint.runtime_path)}</code>
                      <a class="link" href="${esc(endpoint.runtime_path)}" target="_blank" rel="noopener">abrir</a>
                    </td>
                    <td>${endpoint.published_version_id ? `<span class="pill pill--ok">v${esc(endpoint.published_version_id)}</span>` : '<span class="pill">rascunho</span>'}</td>
                    <td>${endpoint.is_active ? 'sim' : 'não'}</td>
                    <td class="table__actions">
                      <a class="btn btn--sm" href="#/endpoint/${esc(endpoint.id)}">Detalhes</a>
                      <button class="btn btn--sm btn--danger" data-action="delete" data-id="${esc(endpoint.id)}">Remover</button>
                    </td>
                  </tr>`,
                  )
                  .join('')}
              </tbody>
            </table>`
          : empty('Nenhum endpoint neste projeto.')
      }
    </section>`;

  qs('#project-select', view).addEventListener('change', (event) => {
    location.hash = `#/endpoints/${event.target.value}`;
  });

  const reload = () => renderEndpoints(view, [String(selectedId)]);

  // -- Painel de criacao --------------------------------------------------
  const panel = qs('#create-panel', view);
  const toggle = qs('#btn-toggle-create', view);

  function buildCreateForm() {
    panel.innerHTML = `
      <form id="endpoint-form" class="stack">
        <h3>Novo endpoint</h3>
        <div class="row row--2">
          ${field('Slug', 'slug', { required: true, placeholder: 'listar-clientes' })}
          ${field('Nome', 'name', { required: true })}
        </div>
        <div class="row row--2">
          ${selectField('Método HTTP', 'http_method', METHODS, 'GET')}
          ${field('Path', 'path', { required: true, placeholder: 'clientes' })}
        </div>
        <label class="field"><span>Descrição</span><textarea name="description" rows="2"></textarea></label>
        <div class="row row--2">
          ${field('Tags (vírgula)', 'tags', { list: true })}
          ${checkboxField('Ativo', 'is_active', true)}
        </div>
        <div id="datasource-slot"></div>
        <div id="definition-slot"></div>
        <div class="modal__actions">
          <button type="submit" class="btn btn--primary">Criar endpoint</button>
          <button type="button" class="btn" id="btn-cancel-create">Cancelar</button>
        </div>
      </form>`;

    let datasourceId = sources.length ? sources[0].id : null;

    const renderDatasourceSelect = () => {
      const slot = qs('#datasource-slot', panel);
      slot.innerHTML = datasourceSelectHtml(sources, datasourceId);
      qs('#datasource-select', slot).addEventListener('change', (event) => {
        datasourceId = event.target.value ? Number(event.target.value) : null;
        editor.setDatasource(datasourceId);
      });
    };

    const definitionSlot = qs('#definition-slot', panel);
    const editor = createDefinitionEditor({ container: definitionSlot, datasourceId });
    renderDatasourceSelect();

    qs('#btn-cancel-create', panel).addEventListener('click', () => {
      panel.hidden = true;
      panel.innerHTML = '';
    });

    const form = qs('#endpoint-form', panel);
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const values = readForm(form);
      let definition;
      try {
        definition = editor.getValue();
      } catch (err) {
        showError(err);
        return;
      }
      const payload = {
        project_id: selectedId,
        datasource_id: datasourceId,
        slug: values.slug,
        name: values.name,
        description: values.description,
        http_method: values.http_method,
        path: values.path,
        tags: values.tags || [],
        is_active: values.is_active,
        definition,
      };
      const submit = qs('button[type="submit"]', form);
      submit.disabled = true;
      try {
        const created = await api.createEndpoint(payload);
        toast(`Endpoint #${created.id} criado.`, 'success');
        location.hash = `#/endpoint/${created.id}`;
      } catch (err) {
        showError(err);
      } finally {
        submit.disabled = false;
      }
    });
  }

  toggle.addEventListener('click', () => {
    if (panel.hidden) {
      buildCreateForm();
      panel.hidden = false;
    } else {
      panel.hidden = true;
      panel.innerHTML = '';
    }
  });

  view.querySelectorAll('[data-action="delete"]').forEach((button) => {
    button.addEventListener('click', async () => {
      const endpoint = endpoints.find((item) => item.id === Number(button.dataset.id));
      if (!confirmAction(`Remover o endpoint "${endpoint.name}" (#${endpoint.id})?`)) return;
      try {
        await api.deleteEndpoint(endpoint.id);
        toast('Endpoint removido.', 'success');
        await reload();
      } catch (err) {
        showError(err);
      }
    });
  });
}
