// Tela de logs: telemetria de requisicoes, trilha de auditoria e expurgo.

import { api } from '/api.js';
import { empty, esc, field, fmtDateTime, loading, qs, readForm, showError, toast } from '/ui.js';

function requestLogsTable(logs) {
  if (!logs.length) return empty('Nenhuma requisição encontrada.');
  return `<table class="table">
    <thead><tr><th>Id</th><th>Quando</th><th>Método</th><th>Path</th><th>Status</th><th>Duração</th><th>Linhas</th><th>Projeto</th><th>Endpoint</th><th>IP</th><th>Mode</th><th>Erro</th></tr></thead>
    <tbody>
      ${logs
        .map(
          (log) => `
        <tr>
          <td>${esc(log.id)}</td>
          <td>${esc(fmtDateTime(log.ts))}</td>
          <td><span class="method">${esc(log.method)}</span></td>
          <td><code>${esc(log.path)}</code></td>
          <td><span class="pill ${log.status_code >= 400 ? 'pill--err' : 'pill--ok'}">${esc(log.status_code)}</span></td>
          <td>${esc(log.duration_ms)} ms</td>
          <td>${esc(log.rows_returned)}</td>
          <td>${log.project_id ?? '—'}</td>
          <td>${log.endpoint_id ?? '—'}</td>
          <td>${esc(log.client_ip)}</td>
          <td>${esc(log.mode)}</td>
          <td>${esc(log.error_code || '')} ${esc(log.error_message || '')}</td>
        </tr>`,
        )
        .join('')}
    </tbody>
  </table>`;
}

function auditLogsTable(logs) {
  if (!logs.length) return empty('Nenhum registro de auditoria encontrado.');
  return `<table class="table">
    <thead><tr><th>Id</th><th>Quando</th><th>Ator</th><th>Ação</th><th>Recurso</th><th>Recurso id</th><th>IP</th><th>Sucesso</th></tr></thead>
    <tbody>
      ${logs
        .map(
          (log) => `
        <tr>
          <td>${esc(log.id)}</td>
          <td>${esc(fmtDateTime(log.ts))}</td>
          <td>${esc(log.actor_email || log.actor_user_id || '—')}</td>
          <td>${esc(log.action)}</td>
          <td>${esc(log.resource_type)}</td>
          <td>${esc(log.resource_id)}</td>
          <td>${esc(log.ip)}</td>
          <td>${log.success ? '<span class="pill pill--ok">sim</span>' : '<span class="pill pill--err">não</span>'}</td>
        </tr>`,
        )
        .join('')}
    </tbody>
  </table>`;
}

export async function renderLogs(view) {
  view.innerHTML = loading('carregando logs…');
  const [requests, audits] = await Promise.all([
    api.requestLogs({ limit: 100 }),
    api.auditLogs({ limit: 100 }),
  ]);

  view.innerHTML = `
    <section class="card">
      <div class="card__head"><h2>Requisições ao runtime</h2></div>
      <form id="requests-filter" class="field-row">
        ${field('Endpoint id', 'endpoint_id', { datatype: 'int' })}
        ${field('Projeto id', 'project_id', { datatype: 'int' })}
        ${field('Status mínimo', 'status_min', { datatype: 'int' })}
        ${field('Limite', 'limit', { datatype: 'int', value: 100 })}
        <button type="submit" class="btn btn--primary">Buscar</button>
      </form>
      <div id="requests-slot">${requestLogsTable(requests)}</div>
    </section>

    <section class="card">
      <div class="card__head"><h2>Trilha de auditoria</h2></div>
      <form id="audit-filter" class="field-row">
        ${field('Ação', 'action', { placeholder: 'project.create' })}
        ${field('Limite', 'limit', { datatype: 'int', value: 100 })}
        <button type="submit" class="btn btn--primary">Buscar</button>
      </form>
      <div id="audit-slot">${auditLogsTable(audits)}</div>
    </section>

    <section class="card">
      <div class="card__head"><h2>Expurgar telemetria antiga</h2></div>
      <form id="purge-form" class="field-row">
        ${field('Remover registros mais antigos que (dias)', 'older_than_days', { datatype: 'int', value: 30 })}
        <button type="submit" class="btn btn--danger">Expurgar</button>
      </form>
    </section>`;

  const requestsForm = qs('#requests-filter', view);
  requestsForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const values = readForm(requestsForm);
    try {
      const logs = await api.requestLogs({
        endpointId: values.endpoint_id,
        projectId: values.project_id,
        statusMin: values.status_min,
        limit: values.limit || 100,
      });
      qs('#requests-slot', view).innerHTML = requestLogsTable(logs);
    } catch (err) {
      showError(err);
    }
  });

  const auditForm = qs('#audit-filter', view);
  auditForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const values = readForm(auditForm);
    try {
      const logs = await api.auditLogs({ action: values.action, limit: values.limit || 100 });
      qs('#audit-slot', view).innerHTML = auditLogsTable(logs);
    } catch (err) {
      showError(err);
    }
  });

  const purgeForm = qs('#purge-form', view);
  purgeForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const values = readForm(purgeForm);
    try {
      const result = await api.purgeLogs(values.older_than_days || 30);
      toast(`Telemetria removida: ${result.deleted} registro(s).`, 'success');
      const logs = await api.requestLogs({ limit: 100 });
      qs('#requests-slot', view).innerHTML = requestLogsTable(logs);
    } catch (err) {
      showError(err);
    }
  });
}
