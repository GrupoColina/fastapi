// Utilitarios de interface: escape, formatacao, campos de formulario,
// notificacoes e um modal simples. Sem dependencia de frameworks externos.

export function esc(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

export function fmtDateTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString('pt-BR');
}

export function json(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function splitList(text) {
  return String(text || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

export function qs(selector, root = document) {
  return root.querySelector(selector);
}

export function qsa(selector, root = document) {
  return Array.from(root.querySelectorAll(selector));
}

export function on(root, selector, event, handler) {
  qsa(selector, root).forEach((node) => node.addEventListener(event, handler));
}

export function loading(message = 'carregando…') {
  return `<div class="loading">${esc(message)}</div>`;
}

export function empty(message) {
  return `<div class="empty">${esc(message)}</div>`;
}

// -- Notificacoes ---------------------------------------------------------
export function toast(message, type = 'info', timeout = 6000) {
  const host = document.getElementById('toasts');
  if (!host) return;
  const node = document.createElement('div');
  node.className = `toast toast--${type}`;
  const text = document.createElement('span');
  text.className = 'toast__msg';
  text.textContent = message;
  node.appendChild(text);
  const close = document.createElement('button');
  close.type = 'button';
  close.className = 'toast__close';
  close.textContent = '×';
  close.addEventListener('click', () => node.remove());
  node.appendChild(close);
  host.appendChild(node);
  if (timeout) setTimeout(() => node.remove(), timeout);
}

// Nunca engole erro: mostra o codigo e a mensagem devolvidos pela API.
export function showError(err) {
  const code = err && err.code ? err.code : 'erro';
  const message = err && err.message ? err.message : String(err);
  toast(`${code}: ${message}`, 'error', 9000);
  if (err && err.details) console.warn('detalhes do erro:', err.details);
}

// -- Campos de formulario -------------------------------------------------
export function field(label, name, opts = {}) {
  const {
    type = 'text',
    value = '',
    required = false,
    placeholder = '',
    step = '',
    datatype = '',
    list = false,
    disabled = false,
  } = opts;
  const attrs = [
    `type="${esc(type)}"`,
    `name="${esc(name)}"`,
    `value="${esc(value)}"`,
    required ? 'required' : '',
    placeholder ? `placeholder="${esc(placeholder)}"` : '',
    step ? `step="${esc(step)}"` : '',
    datatype ? `data-type="${esc(datatype)}"` : '',
    list ? 'data-list="true"' : '',
    disabled ? 'disabled' : '',
  ].filter(Boolean).join(' ');
  return `<label class="field"><span>${esc(label)}</span><input ${attrs}></label>`;
}

export function textareaField(label, name, value = '', rows = 4) {
  return `<label class="field"><span>${esc(label)}</span>
    <textarea name="${esc(name)}" rows="${esc(rows)}">${esc(value)}</textarea></label>`;
}

export function selectField(label, name, options, value, opts = {}) {
  const { datatype = '', rerender = false } = opts;
  const current = value === undefined || value === null ? '' : String(value);
  const optsHtml = options
    .map(([val, text]) => {
      const selected = String(val) === current ? 'selected' : '';
      return `<option value="${esc(val)}" ${selected}>${esc(text)}</option>`;
    })
    .join('');
  const attrs = [
    datatype ? `data-type="${esc(datatype)}"` : '',
    rerender ? 'data-rerender="true"' : '',
  ].filter(Boolean).join(' ');
  return `<label class="field"><span>${esc(label)}</span>
    <select name="${esc(name)}" ${attrs}>${optsHtml}</select></label>`;
}

export function checkboxField(label, name, checked = false) {
  return `<label class="checkbox"><input type="checkbox" name="${esc(name)}" ${checked ? 'checked' : ''}><span>${esc(label)}</span></label>`;
}

// Le os campos nomeados de um formulario. Checkboxes viram boolean,
// data-list vira array por virgula e data-type=int/number vira numero.
export function readForm(form) {
  const out = {};
  Array.from(form.elements).forEach((el) => {
    if (!el.name) return;
    if (el.type === 'checkbox') {
      out[el.name] = el.checked;
      return;
    }
    if (el.dataset.list === 'true') {
      out[el.name] = splitList(el.value);
      return;
    }
    if (el.dataset.type === 'int' || el.dataset.type === 'number') {
      const raw = el.value.trim();
      out[el.name] = raw === '' ? null : Number(raw);
      return;
    }
    out[el.name] = typeof el.value === 'string' ? el.value.trim() : el.value;
  });
  return out;
}

export function confirmAction(message) {
  return window.confirm(message);
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast('Copiado para a área de transferência.', 'success');
  } catch {
    toast('Não foi possível copiar automaticamente.', 'error');
  }
}

// -- Modal ----------------------------------------------------------------
export function openModal(title, bodyHtml, options = {}) {
  const { onMount = null, width = '' } = options;
  const root = document.getElementById('modal-root');
  root.innerHTML = `
    <div class="modal-backdrop">
      <div class="modal" ${width ? `style="max-width:${esc(width)}"` : ''}>
        <header class="modal__head">
          <h2>${esc(title)}</h2>
          <button class="modal__close" type="button" aria-label="Fechar">×</button>
        </header>
        <div class="modal__body">${bodyHtml}</div>
      </div>
    </div>`;
  const close = () => {
    root.innerHTML = '';
  };
  const backdrop = qs('.modal-backdrop', root);
  qs('.modal__close', root).addEventListener('click', close);
  backdrop.addEventListener('click', (event) => {
    if (event.target === backdrop) close();
  });
  document.addEventListener(
    'keydown',
    (event) => {
      if (event.key === 'Escape') close();
    },
    { once: true },
  );
  const body = qs('.modal__body', root);
  if (onMount) onMount(body, close);
  return { close, body };
}
