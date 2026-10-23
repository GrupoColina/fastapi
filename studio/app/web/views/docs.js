// Tela de documentacao: links para as interfaces geradas e healthcheck real.

import { api } from '/api.js';
import { esc, showError } from '/ui.js';

export async function renderDocs(view) {
  view.innerHTML = `
    <section class="card">
      <div class="card__head"><h2>Documentação e sistema</h2></div>
      <ul class="doc-links">
        <li><a class="link" href="/api/v1/docs" target="_blank" rel="noopener">Swagger UI (APIs publicadas)</a><code>/api/v1/docs</code></li>
        <li><a class="link" href="/api/v1/redoc" target="_blank" rel="noopener">ReDoc (APIs publicadas)</a><code>/api/v1/redoc</code></li>
        <li><a class="link" href="/api/v1/openapi.json" target="_blank" rel="noopener">OpenAPI JSON</a><code>/api/v1/openapi.json</code></li>
        <li><a class="link" href="/health" target="_blank" rel="noopener">Healthcheck</a><code>/health</code></li>
      </ul>
    </section>
    <section class="card">
      <div class="card__head">
        <h2>Healthcheck</h2>
        <button class="btn btn--primary" id="btn-health">Verificar /health</button>
      </div>
      <div id="health-result"><p class="muted">Clique em "Verificar" para consultar o endpoint real.</p></div>
    </section>`;

  view.querySelector('#btn-health').addEventListener('click', async () => {
    const slot = view.querySelector('#health-result');
    slot.innerHTML = '<div class="loading">consultando…</div>';
    try {
      const result = await api.health();
      slot.innerHTML = `
        <dl class="kv">
          <dt>Status</dt><dd>${esc(result.status)}</dd>
          <dt>Banco</dt><dd>${result.database ? 'ok' : 'indisponível'}</dd>
          <dt>Engine de metadados</dt><dd>${esc(result.metadata_engine)}</dd>
          <dt>Endpoints no runtime</dt><dd>${esc(result.runtime_endpoints)}</dd>
        </dl>`;
    } catch (err) {
      slot.innerHTML = '<div class="alert alert--error">Falha ao consultar /health.</div>';
      showError(err);
    }
  });
}
