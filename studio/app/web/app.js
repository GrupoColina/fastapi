// Ponto de entrada da SPA: sessao, layout, roteador por hash e tela de login.

import { api } from '/api.js';
import { clearSession, getRefreshToken, getStoredUser, isAuthenticated, setTokens, setUser } from '/session.js';
import { esc, openModal, qs, showError, toast } from '/ui.js';
import { renderDashboard } from '/views/dashboard.js';
import { renderProjects } from '/views/projects.js';
import { renderDatasources } from '/views/datasources.js';
import { renderEndpoints } from '/views/endpoints.js';
import { renderEndpointDetail } from '/views/endpoint-detail.js';
import { renderApiKeys } from '/views/apikeys.js';
import { renderUsers } from '/views/users.js';
import { renderLogs } from '/views/logs.js';
import { renderDocs } from '/views/docs.js';

const NAV = [
  ['/dashboard', 'Dashboard'],
  ['/projetos', 'Projetos'],
  ['/fontes', 'Fontes de dados'],
  ['/endpoints', 'Endpoints'],
  ['/chaves', 'API keys'],
  ['/usuarios', 'Usuários'],
  ['/logs', 'Logs'],
  ['/docs', 'Documentação'],
];

const TITLES = {
  dashboard: 'Dashboard',
  projetos: 'Projetos',
  fontes: 'Fontes de dados',
  endpoints: 'Endpoints',
  endpoint: 'Detalhe do endpoint',
  chaves: 'API keys',
  usuarios: 'Usuários',
  logs: 'Logs e auditoria',
  docs: 'Documentação',
};

function currentRoute() {
  const raw = location.hash.replace(/^#/, '').replace(/^\/+/, '');
  if (!raw) return [];
  return raw.split('/').filter(Boolean);
}

function shell(active) {
  const user = getStoredUser() || {};
  const navHtml = NAV.map(([hash, label]) => {
    const activeClass = active === hash ? 'nav__item nav__item--active' : 'nav__item';
    return `<a href="#${hash}" class="${activeClass}">${esc(label)}</a>`;
  }).join('');
  return `
    <div class="shell">
      <aside class="sidebar" id="sidebar">
        <a class="brand" href="#/dashboard" aria-label="Grupo Colina">
          <img class="brand__logo" src="/logo-colina.png" alt="Grupo Colina">
        </a>
        <nav class="nav">${navHtml}</nav>
        <div class="sidebar__foot">
          <a href="/api/v1/docs" target="_blank" rel="noopener">Swagger</a>
          <a href="/api/v1/redoc" target="_blank" rel="noopener">ReDoc</a>
          <a href="/api/v1/openapi.json" target="_blank" rel="noopener">OpenAPI</a>
          <a href="/health" target="_blank" rel="noopener">/health</a>
        </div>
      </aside>
      <div class="sidebar-backdrop" id="sidebar-backdrop"></div>
      <div class="main">
        <header class="topbar">
          <div class="topbar__lead">
            <button class="menu-toggle" type="button" id="btn-menu" aria-label="Abrir menu">☰</button>
            <div class="topbar__title" id="page-title"></div>
          </div>
          <div class="topbar__user">
            <span class="user-chip">
              <strong>${esc(user.name || user.email || 'sessão')}</strong>
              <span class="role role--${esc(user.role || '')}">${esc(user.role || '')}</span>
            </span>
            ${user.must_change_password ? '<button class="btn btn--warn" id="btn-change-password">Trocar senha</button>' : ''}
            <button class="btn" id="btn-logout">Sair</button>
          </div>
        </header>
        <main class="view" id="view"></main>
      </div>
    </div>`;
}

async function doLogout() {
  try {
    await api.logout(getRefreshToken());
  } catch (err) {
    // Logout e idempotente no servidor; seguimos limpando a sessao local.
    console.warn('logout falhou', err);
  }
  clearSession();
  toast('Sessão encerrada.', 'success');
  location.hash = '#/login';
}

function openChangePassword() {
  const user = getStoredUser() || {};
  openModal(
    'Trocar senha',
    `
    <form id="change-password-form">
      <p class="muted">Usuário: ${esc(user.email || '')}</p>
      <label class="field"><span>Senha atual</span><input type="password" name="current_password" required></label>
      <label class="field"><span>Nova senha</span><input type="password" name="new_password" required></label>
      <div class="modal__actions">
        <button type="submit" class="btn btn--primary">Salvar</button>
      </div>
    </form>`,
    {
      onMount(body, close) {
        const form = qs('#change-password-form', body);
        form.addEventListener('submit', async (event) => {
          event.preventDefault();
          const data = new FormData(form);
          try {
            const updated = await api.changePassword(
              String(data.get('current_password') || ''),
              String(data.get('new_password') || ''),
            );
            setUser(updated);
            toast('Senha alterada com sucesso.', 'success');
            close();
            await boot();
          } catch (err) {
            showError(err);
          }
        });
      },
    },
  );
}

function bindChrome() {
  const logout = qs('#btn-logout');
  if (logout) logout.addEventListener('click', doLogout);
  const change = qs('#btn-change-password');
  if (change) change.addEventListener('click', openChangePassword);

  // Sidebar em modo drawer abaixo de 768px (identidade Colina Core, secao 3.5).
  const shell = qs('.shell');
  const menu = qs('#btn-menu');
  const backdrop = qs('#sidebar-backdrop');
  if (shell && menu) {
    const closeNav = () => shell.classList.remove('shell--nav-open');
    menu.addEventListener('click', () => shell.classList.toggle('shell--nav-open'));
    if (backdrop) backdrop.addEventListener('click', closeNav);
    document.addEventListener(
      'keydown',
      (event) => {
        if (event.key === 'Escape') closeNav();
      },
      { once: true },
    );
  }
}

function renderLogin() {
  document.getElementById('app').innerHTML = `
    <div class="login">
      <form class="login__card" id="login-form">
        <img class="login__logo" src="/logo-colina.png" alt="Grupo Colina">
        <h1>FastAPI Studio</h1>
        <p class="muted">Painel administrativo</p>
        <label class="field"><span>E-mail</span><input type="email" name="email" autocomplete="username" required></label>
        <label class="field"><span>Senha</span><input type="password" name="password" autocomplete="current-password" required></label>
        <button class="btn btn--primary" type="submit">Entrar</button>
        <div class="login__error" id="login-error" hidden></div>
        <p class="login__foot">Em caso de problemas, contate o administrador do sistema.</p>
      </form>
    </div>`;
  const form = qs('#login-form');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const errorBox = qs('#login-error');
    errorBox.hidden = true;
    const data = new FormData(form);
    const submit = qs('button[type="submit"]', form);
    submit.disabled = true;
    try {
      const result = await api.login(
        String(data.get('email') || ''),
        String(data.get('password') || ''),
      );
      setTokens(result);
      toast(`Bem-vindo, ${result.user.name || result.user.email}.`, 'success');
      location.hash = '#/dashboard';
    } catch (err) {
      errorBox.hidden = false;
      errorBox.textContent = `${err.code || 'erro'}: ${err.message}`;
      showError(err);
    } finally {
      submit.disabled = false;
    }
  });
}

async function route() {
  const parts = currentRoute();
  const name = parts[0] || (isAuthenticated() ? 'dashboard' : 'login');

  if (name === 'login') {
    if (isAuthenticated()) {
      location.hash = '#/dashboard';
      return;
    }
    renderLogin();
    return;
  }

  if (!isAuthenticated()) {
    location.hash = '#/login';
    return;
  }

  try {
    const user = await api.me();
    setUser(user);
  } catch (err) {
    clearSession();
    location.hash = '#/login';
    return;
  }

  const active = `/${name}`;
  document.getElementById('app').innerHTML = shell(active);
  document.getElementById('page-title').textContent = TITLES[name] || name;
  bindChrome();

  const view = qs('#view');
  const params = parts.slice(1);

  try {
    switch (name) {
      case 'dashboard':
        await renderDashboard(view, params);
        break;
      case 'projetos':
        await renderProjects(view, params);
        break;
      case 'fontes':
        await renderDatasources(view, params);
        break;
      case 'endpoints':
        await renderEndpoints(view, params);
        break;
      case 'endpoint':
        await renderEndpointDetail(view, params);
        break;
      case 'chaves':
        await renderApiKeys(view, params);
        break;
      case 'usuarios':
        await renderUsers(view, params);
        break;
      case 'logs':
        await renderLogs(view, params);
        break;
      case 'docs':
        await renderDocs(view, params);
        break;
      default:
        view.innerHTML = `<div class="empty">Rota desconhecida: ${esc(location.hash)}</div>`;
    }
  } catch (err) {
    showError(err);
    view.innerHTML = '<div class="empty">Falha ao carregar esta tela. Veja o aviso de erro.</div>';
  }
}

// Reexecuta o roteador atual (usado apos trocar senha, por exemplo).
async function boot() {
  await route();
}

window.addEventListener('hashchange', route);
route();
