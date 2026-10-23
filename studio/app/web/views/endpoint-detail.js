// Tela de detalhe do endpoint: metadados, versoes (validar/publicar/rollback/diff),
// criacao de nova versao pelo construtor visual e playground de execucao real.

import { api } from '/api.js';
import { createDefinitionEditor } from '/definition-editor.js';
import {
  checkboxField,
  confirmAction,
  empty,
  esc,
  field,
  fmtDateTime,
  json,
  loading,
  openModal,
  qs,
  readForm,
  selectField,
  showError,
  toast,
} from '/ui.js';

const METHODS = [['GET', 'GET'], ['POST', 'POST'], ['PUT', 'PUT'], ['PATCH', 'PATCH'], ['DELETE', 'DELETE']];

function versionsTable(versions) {
  if (!versions.length) return empty('Nenhuma versão criada.');
  return `<table class="table">
    <thead><tr><th>#</th><th>Semver</th><th>Status</th><th>Nota</th><th>Validação</th><th>Criada</th><th></th></tr></thead>
    <tbody>
      ${versions
        .map(
          (version) => `
        <tr>
          <td>${esc(version.version_number)}</td>
          <td>${esc(version.semver)}</td>
          <td><span class="pill ${version.status === 'published' ? 'pill--ok' : ''}">${esc(version.status)}</span></td>
          <td>${esc(version.change_note)}</td>
          <td>${version.validation_errors && version.validation_errors.length ? `<span class="pill pill--err">${version.validation_errors.length} erro(s)</span>` : '<span class="muted">—</span>'}</td>
          <td>${esc(fmtDateTime(version.created_at))}</td>
          <td class="table__actions">
            <button class="btn btn--sm" data-action="view" data-id="${esc(version.id)}">Ver</button>
            <button class="btn btn--sm" data-action="validate" data-id="${esc(version.id)}">Validar</button>
            <button class="btn btn--sm" data-action="publish" data-id="${esc(version.id)}">Publicar</button>
            <button class="btn btn--sm" data-action="rollback" data-id="${esc(version.id)}">Rollback</button>
            <button class="btn btn--sm" data-action="diff" data-id="${esc(version.id)}">Diff</button>
            <button class="btn btn--sm btn--danger" data-action="archive" data-id="${esc(version.id)}">Arquivar</button>
          </td>
        </tr>`,
        )
        .join('')}
    </tbody>
  </table>`;
}

function showPlaygroundResult(result) {
  const badge = result.ok
    ? '<span class="pill pill--ok">ok</span>'
    : `<span class="pill pill--err">${esc(result.error_code || 'erro')}</span>`;
  return `
    <div class="playground__meta">
      ${badge}
      <span>status_code: <strong>${esc(result.status_code)}</strong></span>
      <span>rows: <strong>${esc(result.rows)}</strong></span>
      <span>duration_ms: <strong>${esc(result.duration_ms)}</strong></span>
      <span>mode: <strong>${esc(result.mode)}</strong></span>
      ${result.truncated ? '<span class="pill">truncado</span>' : ''}
    </div>
    ${result.error_message ? `<div class="alert alert--error">${esc(result.error_message)}</div>` : ''}
    <h5>Payload</h5>
    <pre class="code">${esc(json(result.payload))}</pre>`;
}

export async function renderEndpointDetail(view, params) {
  const endpointId = params[0] ? Number(params[0]) : null;
  if (!endpointId) {
    view.innerHTML = empty('Endpoint inválido.');
    return;
  }
  view.innerHTML = loading('carregando endpoint…');

  const endpoint = await api.getEndpoint(endpointId);
  const versions = await api.listVersions(endpointId);
  let latestDefinition = null;
  if (versions.length) {
    try {
      const detail = await api.getVersion(endpointId, versions[0].id);
      latestDefinition = detail.definition;
    } catch (err) {
      console.warn('nao foi possivel carregar a ultima definicao', err);
    }
  }

  view.innerHTML = `
    <section class="card">
      <div class="card__head">
        <h2>${esc(endpoint.name)} <span class="muted">#${esc(endpoint.id)}</span></h2>
        <div class="table__actions">
          <a class="btn btn--sm" href="${esc(endpoint.runtime_path)}" target="_blank" rel="noopener">Abrir runtime path</a>
          <button class="btn btn--sm" id="btn-deactivate">Desativar</button>
          <button class="btn btn--sm btn--danger" id="btn-delete">Remover</button>
        </div>
      </div>
      <dl class="kv">
        <dt>Slug</dt><dd><code>${esc(endpoint.slug)}</code></dd>
        <dt>Método / Path</dt><dd><span class="method">${esc(endpoint.http_method)}</span> <code>${esc(endpoint.path)}</code></dd>
        <dt>Runtime path</dt><dd><code>${esc(endpoint.runtime_path)}</code></dd>
        <dt>Publicado</dt><dd>${endpoint.published_version_id ? `versão ${esc(endpoint.published_version_id)}` : 'rascunho'}</dd>
        <dt>Ativo</dt><dd>${endpoint.is_active ? 'sim' : 'não'}</dd>
        <dt>Tags</dt><dd>${(endpoint.tags || []).map((t) => `<span class="pill">${esc(t)}</span>`).join(' ') || '<span class="muted">—</span>'}</dd>
      </dl>
    </section>

    <section class="card">
      <div class="card__head"><h3>Metadados do endpoint</h3></div>
      <form id="edit-form">
        ${field('Nome', 'name', { value: endpoint.name })}
        ${field('Descrição', 'description', { value: endpoint.description })}
        <div class="row row--3">
          ${selectField('Método HTTP', 'http_method', METHODS, endpoint.http_method)}
          ${field('Path', 'path', { value: endpoint.path })}
          ${field('Datasource id', 'datasource_id', { value: endpoint.datasource_id ?? '', datatype: 'int' })}
        </div>
        ${field('Tags (vírgula)', 'tags', { value: (endpoint.tags || []).join(', '), list: true })}
        ${checkboxField('Ativo', 'is_active', endpoint.is_active)}
        <div class="modal__actions"><button type="submit" class="btn btn--primary">Salvar metadados</button></div>
      </form>
    </section>

    <section class="card">
      <div class="card__head"><h3>Versões</h3></div>
      <div id="versions-slot">${versionsTable(versions)}</div>
    </section>

    <section class="card">
      <div class="card__head"><h3>Nova versão</h3></div>
      <form id="version-form">
        <div id="version-definition-slot"></div>
        <div class="row row--2">
          ${field('Nota da mudança', 'change_note')}
          ${field('Semver (opcional)', 'semver')}
        </div>
        <div class="modal__actions"><button type="submit" class="btn btn--primary">Criar versão (rascunho)</button></div>
      </form>
    </section>

    <section class="card">
      <div class="card__head"><h3>Playground</h3></div>
      <div class="field-row">
        <label class="field field--inline"><span>Versão</span>
          <select id="pg-version">
            <option value="">última versão</option>
            ${versions.map((v) => `<option value="${esc(v.id)}">v${esc(v.version_number)} (${esc(v.status)})</option>`).join('')}
          </select>
        </label>
      </div>
      <label class="field"><span>Argumentos (JSON)</span><textarea id="pg-args" rows="4" class="code">{}</textarea></label>
      <div class="modal__actions"><button class="btn btn--primary" id="pg-run">Executar</button></div>
      <div id="pg-result"></div>
    </section>`;

  const reload = () => renderEndpointDetail(view, [String(endpointId)]);

  // -- Metadados ----------------------------------------------------------
  const editForm = qs('#edit-form', view);
  editForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const values = readForm(editForm);
    const payload = {
      name: values.name,
      description: values.description,
      http_method: values.http_method,
      path: values.path,
      tags: values.tags || [],
      is_active: values.is_active,
    };
    if (values.datasource_id !== null) payload.datasource_id = values.datasource_id;
    try {
      await api.updateEndpoint(endpointId, payload);
      toast('Metadados atualizados.', 'success');
      await reload();
    } catch (err) {
      showError(err);
    }
  });

  qs('#btn-deactivate', view).addEventListener('click', async () => {
    if (!confirmAction('Desativar o endpoint e remover a rota do runtime?')) return;
    try {
      await api.deactivateEndpoint(endpointId);
      toast('Endpoint desativado.', 'success');
      await reload();
    } catch (err) {
      showError(err);
    }
  });

  qs('#btn-delete', view).addEventListener('click', async () => {
    if (!confirmAction(`Remover definitivamente o endpoint #${endpointId}?`)) return;
    try {
      await api.deleteEndpoint(endpointId);
      toast('Endpoint removido.', 'success');
      location.hash = '#/endpoints';
    } catch (err) {
      showError(err);
    }
  });

  // -- Nova versao --------------------------------------------------------
  const editor = createDefinitionEditor({
    container: qs('#version-definition-slot', view),
    initial: latestDefinition,
    datasourceId: endpoint.datasource_id,
  });

  const versionForm = qs('#version-form', view);
  versionForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const values = readForm(versionForm);
    let definition;
    try {
      definition = editor.getValue();
    } catch (err) {
      showError(err);
      return;
    }
    const payload = { definition, change_note: values.change_note || '' };
    if (values.semver) payload.semver = values.semver;
    const submit = qs('button[type="submit"]', versionForm);
    submit.disabled = true;
    try {
      const created = await api.createVersion(endpointId, payload);
      toast(`Versão ${created.version_number} criada.`, 'success');
      await reload();
    } catch (err) {
      showError(err);
    } finally {
      submit.disabled = false;
    }
  });

  // -- Acoes por versao ---------------------------------------------------
  view.querySelectorAll('[data-action="view"]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        const version = await api.getVersion(endpointId, Number(button.dataset.id));
        openModal(`Versão ${version.version_number}`, `<pre class="code">${esc(json(version.definition))}</pre>`, { width: '820px' });
      } catch (err) {
        showError(err);
      }
    });
  });

  view.querySelectorAll('[data-action="validate"]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        const result = await api.validateVersion(endpointId, Number(button.dataset.id));
        if (result.ok) {
          toast('Versão válida.', 'success');
        } else {
          openModal('Erros de validação', `<ul>${result.errors.map((e) => `<li>${esc(e)}</li>`).join('')}</ul>`);
        }
        await reload();
      } catch (err) {
        showError(err);
      }
    });
  });

  view.querySelectorAll('[data-action="publish"]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        const result = await api.publishVersion(endpointId, Number(button.dataset.id));
        toast(`Versão ${result.version.version_number} publicada.`, 'success');
        openModal(
          'Versão publicada',
          `<p>Runtime: <strong>${esc(result.runtime.endpoints)}</strong> rotas instaladas.</p>${
            result.runtime.errors && result.runtime.errors.length
              ? `<div class="alert alert--error"><ul>${result.runtime.errors.map((e) => `<li>${esc(e)}</li>`).join('')}</ul></div>`
              : ''
          }`,
        );
        await reload();
      } catch (err) {
        showError(err);
      }
    });
  });

  view.querySelectorAll('[data-action="rollback"]').forEach((button) => {
    button.addEventListener('click', async () => {
      if (!confirmAction('Restaurar esta versão como uma nova versão publicada?')) return;
      try {
        const result = await api.rollbackVersion(endpointId, Number(button.dataset.id));
        toast(`Rollback concluído: nova versão ${result.version.version_number} publicada.`, 'success');
        await reload();
      } catch (err) {
        showError(err);
      }
    });
  });

  view.querySelectorAll('[data-action="archive"]').forEach((button) => {
    button.addEventListener('click', async () => {
      if (!confirmAction('Arquivar esta versão?')) return;
      try {
        await api.archiveVersion(endpointId, Number(button.dataset.id));
        toast('Versão arquivada.', 'success');
        await reload();
      } catch (err) {
        showError(err);
      }
    });
  });

  view.querySelectorAll('[data-action="diff"]').forEach((button) => {
    button.addEventListener('click', async () => {
      const versionId = Number(button.dataset.id);
      openModal(
        'Comparar versões',
        `
        <label class="field"><span>Comparar contra a versão (id)</span>
          <select id="diff-against">${versions.map((v) => `<option value="${esc(v.id)}">v${esc(v.version_number)} (#${esc(v.id)})</option>`).join('')}</select>
        </label>
        <div class="modal__actions"><button class="btn btn--primary" id="diff-run">Comparar</button></div>
        <div id="diff-result"></div>`,
        {
          width: '820px',
          onMount(body) {
            qs('#diff-run', body).addEventListener('click', async () => {
              const against = Number(qs('#diff-against', body).value);
              try {
                const result = await api.diffVersions(endpointId, versionId, against);
                qs('#diff-result', body).innerHTML = result.changed
                  ? `<pre class="code">${esc(json(result.changes))}</pre>`
                  : '<p class="muted">Nenhuma diferença.</p>';
              } catch (err) {
                showError(err);
              }
            });
          },
        },
      );
    });
  });

  // -- Playground ---------------------------------------------------------
  qs('#pg-run', view).addEventListener('click', async () => {
    const argsText = qs('#pg-args', view).value.trim() || '{}';
    let args;
    try {
      args = JSON.parse(argsText);
    } catch (err) {
      toast(`Argumentos inválidos: ${err.message}`, 'error');
      return;
    }
    const versionId = qs('#pg-version', view).value;
    const payload = { arguments: args };
    if (versionId) payload.version_id = Number(versionId);
    const button = qs('#pg-run', view);
    button.disabled = true;
    try {
      const result = await api.playground(endpointId, payload);
      qs('#pg-result', view).innerHTML = showPlaygroundResult(result);
    } catch (err) {
      qs('#pg-result', view).innerHTML = '';
      showError(err);
    } finally {
      button.disabled = false;
    }
  });
}
