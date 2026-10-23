// Construtor visual da `definition` de um endpoint.
//
// Monta o objeto aceito por EndpointDefinition (extra="forbid"), emitindo apenas
// os campos previstos no contrato. Tambem oferece um "modo avancado" com o JSON cru.

import { api } from '/api.js';
import { esc, qs, splitList, toast, showError } from '/ui.js';

const TYPE_OPTIONS = [
  'string',
  'integer',
  'number',
  'boolean',
  'date',
  'datetime',
  'uuid',
  'binary',
  'time',
  'array',
  'object',
].map((value) => [value, value]);

const LOCATIONS = [
  ['query', 'query'],
  ['path', 'path'],
  ['header', 'header'],
  ['body', 'body'],
];

const ENVELOPES = [
  ['object', 'object'],
  ['list', 'list'],
  ['paginated', 'paginated'],
];

const AUTH_MODES = [
  ['none', 'none'],
  ['api_key', 'api_key'],
  ['jwt', 'jwt'],
];

const SOURCE_MODES = [
  ['sql', 'sql (consulta parametrizada)'],
  ['procedure', 'procedure (stored procedure)'],
  ['advanced', 'advanced (codigo Python)'],
];

function emptyState() {
  return {
    summary: '',
    description: '',
    tagsText: '',
    deprecated: false,
    parameters: [],
    source: {
      mode: 'sql',
      sql: '',
      procedure_schema: 'dbo',
      procedure_name: '',
      advanced_code: '',
    },
    response: { envelope: 'list', fields: [] },
    auth: { mode: 'api_key', scopesText: '', rate_limit_per_minute: '' },
    advancedMode: false,
    advancedJson: '',
    objects: [],
  };
}

function applyDefinition(state, def) {
  if (!def || typeof def !== 'object') return state;
  state.summary = def.summary || '';
  state.description = def.description || '';
  state.tagsText = (def.tags || []).join(', ');
  state.deprecated = Boolean(def.deprecated);
  state.parameters = (def.parameters || []).map((p) => ({
    name: p.name || '',
    location: p.location || 'query',
    type: p.type || 'string',
    required: Boolean(p.required),
    description: p.description || '',
    defaultText: p.default === undefined || p.default === null ? '' : String(p.default),
  }));
  const src = def.source || {};
  state.source = {
    mode: src.mode || 'sql',
    sql: src.sql || '',
    procedure_schema: src.procedure_schema || 'dbo',
    procedure_name: src.procedure_name || '',
    advanced_code: src.advanced_code || '',
  };
  const resp = def.response || {};
  state.response = {
    envelope: resp.envelope || 'list',
    fields: (resp.fields || []).map((f) => ({
      name: f.name || '',
      type: f.type || 'string',
      nullable: f.nullable !== false,
      required: Boolean(f.required),
    })),
  };
  const auth = def.auth || {};
  state.auth = {
    mode: auth.mode || 'api_key',
    scopesText: (auth.scopes || []).join(', '),
    rate_limit_per_minute:
      auth.rate_limit_per_minute === undefined || auth.rate_limit_per_minute === null
        ? ''
        : String(auth.rate_limit_per_minute),
  };
  return state;
}

function setPath(obj, path, value) {
  const keys = path.split('.');
  let cursor = obj;
  for (let i = 0; i < keys.length - 1; i += 1) cursor = cursor[keys[i]];
  cursor[keys[keys.length - 1]] = value;
}

function selectHtml(path, options, current, extra = '') {
  const optsHtml = options
    .map(([val, label]) => {
      const selected = String(val) === String(current) ? 'selected' : '';
      return `<option value="${esc(val)}" ${selected}>${esc(label)}</option>`;
    })
    .join('');
  return `<select data-path="${esc(path)}" ${extra}>${optsHtml}</select>`;
}

// Cria o editor dentro de `container`. Devolve { node, getValue, setValue, setDatasource }.
export function createDefinitionEditor(options = {}) {
  const { container, initial = null } = options;
  let datasourceId = options.datasourceId ?? null;
  const state = applyDefinition(emptyState(), initial);

  const node = document.createElement('div');
  node.className = 'def-editor';
  container.appendChild(node);

  function buildSource() {
    const src = state.source;
    if (src.mode === 'procedure') {
      return {
        mode: 'procedure',
        procedure_schema: src.procedure_schema || 'dbo',
        procedure_name: src.procedure_name.trim(),
      };
    }
    if (src.mode === 'advanced') {
      return { mode: 'advanced', advanced_code: src.advanced_code };
    }
    return { mode: 'sql', sql: src.sql };
  }

  function buildResponse() {
    return {
      envelope: state.response.envelope,
      fields: state.response.fields
        .filter((f) => f.name && f.name.trim())
        .map((f) => ({
          name: f.name.trim(),
          type: f.type,
          nullable: Boolean(f.nullable),
          required: Boolean(f.required),
        })),
    };
  }

  function buildAuth() {
    const auth = { mode: state.auth.mode, scopes: splitList(state.auth.scopesText) };
    const raw = String(state.auth.rate_limit_per_minute ?? '').trim();
    if (raw !== '') {
      const value = Number(raw);
      if (!Number.isNaN(value)) auth.rate_limit_per_minute = value;
    }
    return auth;
  }

  function buildDefinition() {
    const parameters = state.parameters
      .filter((p) => p.name && p.name.trim())
      .map((p) => {
        const param = {
          name: p.name.trim(),
          location: p.location,
          type: p.type,
          required: p.location === 'path' ? true : Boolean(p.required),
          description: p.description || '',
        };
        const defaultText = String(p.defaultText || '').trim();
        if (defaultText !== '') param.default = defaultText;
        return param;
      });
    return {
      summary: state.summary,
      description: state.description,
      tags: splitList(state.tagsText),
      deprecated: Boolean(state.deprecated),
      parameters,
      source: buildSource(),
      response: buildResponse(),
      auth: buildAuth(),
    };
  }

  function getValue() {
    if (state.advancedMode) {
      const parsed = JSON.parse(state.advancedJson);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error('a definição deve ser um objeto JSON');
      }
      return parsed;
    }
    return buildDefinition();
  }

  function setValue(def) {
    applyDefinition(state, def);
    state.advancedMode = false;
    render();
  }

  async function loadObjects() {
    if (!datasourceId) {
      state.objects = [];
      render();
      return;
    }
    try {
      state.objects = await api.listObjects(datasourceId, { onlyAllowed: true });
    } catch (err) {
      showError(err);
      state.objects = [];
    }
    render();
  }

  function setDatasource(id) {
    datasourceId = id ?? null;
    loadObjects();
  }

  // -- Render -------------------------------------------------------------
  function parametersHtml() {
    if (!state.parameters.length) return '<p class="muted">Nenhum parâmetro declarado.</p>';
    return state.parameters
      .map((p, i) => {
        const isPath = p.location === 'path';
        return `
        <div class="row row--param">
          <input data-path="parameters.${i}.name" value="${esc(p.name)}" placeholder="nome (identificador)">
          ${selectHtml(`parameters.${i}.location`, LOCATIONS, p.location, 'data-rerender="true"')}
          ${selectHtml(`parameters.${i}.type`, TYPE_OPTIONS, p.type)}
          <label class="checkbox"><input type="checkbox" data-path="parameters.${i}.required" ${p.required || isPath ? 'checked' : ''} ${isPath ? 'disabled' : ''}><span>obrigatório</span></label>
          <input data-path="parameters.${i}.description" value="${esc(p.description)}" placeholder="descrição">
          <input data-path="parameters.${i}.defaultText" value="${esc(p.defaultText)}" placeholder="default">
          <button type="button" class="btn btn--danger btn--sm" data-action="remove-param" data-index="${i}">remover</button>
        </div>`;
      })
      .join('');
  }

  function sourceHtml() {
    const src = state.source;
    let extra = '';
    if (src.mode === 'sql') {
      extra = `<label class="field"><span>SQL (bind params nomeados :param)</span>
        <textarea data-path="source.sql" rows="5" class="code">${esc(src.sql)}</textarea></label>`;
    } else if (src.mode === 'procedure') {
      extra = `<div class="row row--2">
        <label class="field"><span>Schema da procedure</span><input data-path="source.procedure_schema" value="${esc(src.procedure_schema)}"></label>
        <label class="field"><span>Nome da procedure</span><input data-path="source.procedure_name" value="${esc(src.procedure_name)}"></label>
      </div>`;
    } else {
      extra = `<label class="field"><span>Código Python (handle(ctx) -> dict)</span>
        <textarea data-path="source.advanced_code" rows="8" class="code">${esc(src.advanced_code)}</textarea></label>`;
    }
    return `
      <div class="field-row">
        <label class="field field--inline"><span>Modo da fonte</span>${selectHtml('source.mode', SOURCE_MODES, src.mode, 'data-rerender="true"')}</label>
      </div>
      ${extra}`;
  }

  function responseFieldsHtml() {
    if (!state.response.fields.length) return '<p class="muted">Nenhum campo de resposta declarado.</p>';
    return state.response.fields
      .map(
        (f, i) => `
        <div class="row row--field">
          <input data-path="response.fields.${i}.name" value="${esc(f.name)}" placeholder="campo">
          ${selectHtml(`response.fields.${i}.type`, TYPE_OPTIONS, f.type)}
          <label class="checkbox"><input type="checkbox" data-path="response.fields.${i}.nullable" ${f.nullable ? 'checked' : ''}><span>nullable</span></label>
          <label class="checkbox"><input type="checkbox" data-path="response.fields.${i}.required" ${f.required ? 'checked' : ''}><span>requerido</span></label>
          <button type="button" class="btn btn--danger btn--sm" data-action="remove-field" data-index="${i}">remover</button>
        </div>`,
      )
      .join('');
  }

  function objectFillHtml() {
    if (!datasourceId) {
      return '<p class="muted">Selecione uma fonte de dados para preencher a resposta a partir de um objeto descoberto.</p>';
    }
    const options = state.objects
      .map((obj) => `<option value="${esc(obj.id)}">${esc(obj.schema_name)}.${esc(obj.object_name)} (${esc(obj.object_type)})</option>`)
      .join('');
    const hasObjects = state.objects.length > 0;
    return `
      <div class="field-row">
        <label class="field field--inline"><span>Objeto descoberto/autorizado</span>
          <select data-role="object-select" ${hasObjects ? '' : 'disabled'}>${options || '<option value="">nenhum objeto autorizado</option>'}</select>
        </label>
        <button type="button" class="btn" data-action="reload-objects">Recarregar objetos</button>
        <button type="button" class="btn" data-action="fill-fields" ${hasObjects ? '' : 'disabled'}>Preencher campos da resposta</button>
      </div>`;
  }

  function render() {
    node.innerHTML = `
      <section class="def-section">
        <div class="card__head">
          <h4>Definição do endpoint</h4>
          <label class="toggle"><input type="checkbox" data-role="advanced-mode" ${state.advancedMode ? 'checked' : ''}><span>Modo avançado (JSON cru)</span></label>
        </div>
      </section>

      <div data-role="visual" ${state.advancedMode ? 'hidden' : ''}>
        <section class="def-section">
          <h5>Metadados</h5>
          <div class="row row--2">
            <label class="field"><span>Summary</span><input data-path="summary" value="${esc(state.summary)}"></label>
            <label class="field"><span>Tags (separadas por vírgula)</span><input data-path="tagsText" value="${esc(state.tagsText)}"></label>
          </div>
          <label class="field"><span>Descrição</span><textarea data-path="description" rows="2">${esc(state.description)}</textarea></label>
          <label class="checkbox"><input type="checkbox" data-path="deprecated" ${state.deprecated ? 'checked' : ''}><span>deprecated</span></label>
        </section>

        <section class="def-section">
          <div class="card__head">
            <h5>Parâmetros</h5>
            <button type="button" class="btn btn--sm" data-action="add-param">Adicionar parâmetro</button>
          </div>
          ${parametersHtml()}
        </section>

        <section class="def-section">
          <h5>Fonte dos dados</h5>
          ${sourceHtml()}
        </section>

        <section class="def-section">
          <div class="card__head">
            <h5>Resposta</h5>
            <button type="button" class="btn btn--sm" data-action="add-field">Adicionar campo</button>
          </div>
          <label class="field field--inline"><span>Envelope</span>${selectHtml('response.envelope', ENVELOPES, state.response.envelope)}</label>
          ${responseFieldsHtml()}
          ${objectFillHtml()}
        </section>

        <section class="def-section">
          <h5>Autenticação</h5>
          <div class="row row--3">
            <label class="field field--inline"><span>Modo</span>${selectHtml('auth.mode', AUTH_MODES, state.auth.mode)}</label>
            <label class="field"><span>Scopes (vírgula)</span><input data-path="auth.scopesText" value="${esc(state.auth.scopesText)}"></label>
            <label class="field"><span>Rate limit/min</span><input data-path="auth.rate_limit_per_minute" data-type="int" value="${esc(state.auth.rate_limit_per_minute)}"></label>
          </div>
        </section>
      </div>

      <div data-role="advanced" ${state.advancedMode ? '' : 'hidden'}>
        <section class="def-section">
          <p class="muted">JSON cru da definição completa. Os campos não previstos no contrato serão rejeitados pelo servidor.</p>
          <textarea data-path="advancedJson" rows="18" class="code">${esc(state.advancedJson)}</textarea>
        </section>
      </div>`;
  }

  // -- Eventos ------------------------------------------------------------
  function handleEdit(event) {
    const target = event.target;
    if (target.dataset.role === 'advanced-mode') {
      toggleAdvanced(target.checked);
      return;
    }
    const path = target.dataset.path;
    if (!path) return;
    const value = target.type === 'checkbox' ? target.checked : target.value;
    setPath(state, path, value);
    if (path.endsWith('.location') && value === 'path') {
      const index = Number(path.split('.')[1]);
      state.parameters[index].required = true;
      render();
      return;
    }
    if (target.dataset.rerender === 'true') render();
  }

  function handleClick(event) {
    const button = event.target.closest('[data-action]');
    if (!button) return;
    const action = button.dataset.action;
    if (action === 'add-param') {
      state.parameters.push({ name: '', location: 'query', type: 'string', required: false, description: '', defaultText: '' });
      render();
    } else if (action === 'remove-param') {
      state.parameters.splice(Number(button.dataset.index), 1);
      render();
    } else if (action === 'add-field') {
      state.response.fields.push({ name: '', type: 'string', nullable: true, required: false });
      render();
    } else if (action === 'remove-field') {
      state.response.fields.splice(Number(button.dataset.index), 1);
      render();
    } else if (action === 'reload-objects') {
      loadObjects();
    } else if (action === 'fill-fields') {
      fillFieldsFromObject();
    }
  }

  function fillFieldsFromObject() {
    const select = qs('[data-role="object-select"]', node);
    if (!select) return;
    const id = Number(select.value);
    const obj = state.objects.find((item) => item.id === id);
    if (!obj) {
      toast('Selecione um objeto para preencher a resposta.', 'error');
      return;
    }
    state.response.fields = (obj.columns || []).map((column) => ({
      name: column.name,
      type: column.type || 'string',
      nullable: column.nullable !== false,
      required: column.nullable === false,
    }));
    render();
    toast(`${state.response.fields.length} campos preenchidos a partir de ${obj.schema_name}.${obj.object_name}`, 'success');
  }

  function toggleAdvanced(enabled) {
    if (enabled) {
      state.advancedJson = JSON.stringify(buildDefinition(), null, 2);
      state.advancedMode = true;
      render();
      return;
    }
    try {
      const parsed = JSON.parse(state.advancedJson);
      applyDefinition(state, parsed);
      state.advancedMode = false;
      render();
    } catch (err) {
      toast(`JSON inválido: ${err.message}`, 'error');
      render();
    }
  }

  node.addEventListener('input', handleEdit);
  node.addEventListener('change', handleEdit);
  node.addEventListener('click', handleClick);

  render();
  if (datasourceId) loadObjects();

  return { node, getValue, setValue, setDatasource };
}
