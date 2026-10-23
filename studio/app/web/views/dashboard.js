// Tela do painel: indicadores, estado do runtime e reconstrucao das rotas.

import { api } from '/api.js';
import { esc, fmtDateTime, loading, showError, toast } from '/ui.js';

export async function renderDashboard(view) {
  view.innerHTML = loading('carregando painel…');
  const [stats, runtime] = await Promise.all([api.stats(), api.runtime()]);

  const cards = [
    ['Usuários', stats.users],
    ['Projetos', stats.projects],
    ['Fontes de dados', stats.datasources],
    ['Endpoints', stats.endpoints],
    ['Publicados', stats.published_endpoints],
    ['API keys ativas', stats.api_keys],
    ['Requisições', stats.requests],
    ['Erros', stats.errors],
    ['Auditoria', stats.audit_entries],
  ];

  view.innerHTML = `
    <section class="grid grid--cards">
      ${cards
        .map(
          ([label, value]) => `
        <article class="card card--stat">
          <span class="card__label">${esc(label)}</span>
          <span class="card__value">${esc(value)}</span>
        </article>`,
        )
        .join('')}
    </section>
    <section class="card">
      <div class="card__head">
        <h2>Runtime dinâmico</h2>
        <button class="btn btn--primary" id="btn-rebuild">Reconstruir runtime</button>
      </div>
      <dl class="kv">
        <dt>Endpoints instalados</dt><dd>${esc(runtime.endpoints)}</dd>
        <dt>Projetos</dt><dd>${esc(runtime.projects)}</dd>
        <dt>Última reconstrução</dt><dd>${esc(fmtDateTime(runtime.rebuilt_at))}</dd>
        <dt>Duração (ms)</dt><dd>${esc(runtime.duration_ms)}</dd>
      </dl>
      ${
        runtime.errors && runtime.errors.length
          ? `<div class="alert alert--error"><strong>Erros de instalação</strong><ul>${runtime.errors
              .map((item) => `<li>${esc(item)}</li>`)
              .join('')}</ul></div>`
          : '<p class="muted">Nenhum erro de instalação reportado.</p>'
      }
    </section>`;

  const button = view.querySelector('#btn-rebuild');
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      const result = await api.rebuildRuntime();
      toast(`Runtime reconstruído: ${result.endpoints} rotas.`, 'success');
      await renderDashboard(view);
    } catch (err) {
      showError(err);
    } finally {
      button.disabled = false;
    }
  });
}
