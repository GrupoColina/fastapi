// Camada de acesso a API administrativa do Studio.
//
// Toda chamada passa por request(), que:
//   * anexa o cabecalho Authorization: Bearer <access>;
//   * em caso de 401, tenta renovar a sessao (POST /auth/refresh) uma unica vez
//     e repete a chamada original;
//   * converte o envelope de erro {"error": {code, message, details}} em ApiError.

import { clearSession, getAccessToken, getRefreshToken, setTokens } from '/session.js';

export class ApiError extends Error {
  constructor(message, options = {}) {
    super(message);
    this.name = 'ApiError';
    this.code = options.code || 'error';
    this.details = options.details ?? null;
    this.status = options.status || 0;
  }
}

// Rotas de autenticacao que nao devem disparar a renovacao automatica.
const AUTH_FREE = ['/api/admin/auth/login', '/api/admin/auth/refresh'];

function buildQuery(params) {
  const search = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    search.append(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : '';
}

async function parseBody(response) {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function errorFromResponse(response, body) {
  const envelope = body && typeof body === 'object' ? body.error : null;
  if (envelope && typeof envelope === 'object') {
    return new ApiError(envelope.message || 'erro desconhecido', {
      code: envelope.code || 'error',
      details: envelope.details ?? envelope.request_id ?? null,
      status: response.status,
    });
  }
  const message = typeof body === 'string' && body ? body : `falha HTTP ${response.status}`;
  return new ApiError(message, { code: 'http_error', status: response.status });
}

let refreshPromise = null;

async function refreshSession() {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    throw new ApiError('sessão expirada', { code: 'unauthorized', status: 401 });
  }
  const response = await fetch('/api/admin/auth/refresh', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  const body = await parseBody(response);
  if (!response.ok) {
    clearSession();
    throw errorFromResponse(response, body);
  }
  setTokens(body);
  return body.access_token;
}

export async function request(path, options = {}) {
  const { method = 'GET', body, auth = true, retry = true } = options;
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const token = getAccessToken();
  if (auth && token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (response.status === 401 && retry && !AUTH_FREE.includes(path)) {
    try {
      if (!refreshPromise) {
        refreshPromise = refreshSession().finally(() => {
          refreshPromise = null;
        });
      }
      await refreshPromise;
      return request(path, { method, body, auth, retry: false });
    } catch (err) {
      clearSession();
      throw err;
    }
  }

  const parsed = await parseBody(response);
  if (!response.ok) throw errorFromResponse(response, parsed);
  return parsed;
}

export const api = {
  // -- Autenticacao -------------------------------------------------------
  login: (email, password) =>
    request('/api/admin/auth/login', { method: 'POST', body: { email, password }, auth: false }),
  refresh: (refreshToken) =>
    request('/api/admin/auth/refresh', {
      method: 'POST',
      body: { refresh_token: refreshToken },
      auth: false,
    }),
  logout: (refreshToken) =>
    request('/api/admin/auth/logout', {
      method: 'POST',
      body: { refresh_token: refreshToken },
      auth: false,
    }),
  me: () => request('/api/admin/auth/me'),
  changePassword: (currentPassword, newPassword) =>
    request('/api/admin/auth/change-password', {
      method: 'POST',
      body: { current_password: currentPassword, new_password: newPassword },
    }),

  // -- Projetos -----------------------------------------------------------
  listProjects: () => request('/api/admin/projects'),
  getProject: (id) => request(`/api/admin/projects/${id}`),
  createProject: (payload) => request('/api/admin/projects', { method: 'POST', body: payload }),
  updateProject: (id, payload) =>
    request(`/api/admin/projects/${id}`, { method: 'PATCH', body: payload }),
  deleteProject: (id) => request(`/api/admin/projects/${id}`, { method: 'DELETE' }),
  listProjectAccess: (id) => request(`/api/admin/projects/${id}/access`),
  grantProjectAccess: (id, payload) =>
    request(`/api/admin/projects/${id}/access`, { method: 'POST', body: payload }),
  revokeProjectAccess: (id, userId) =>
    request(`/api/admin/projects/${id}/access/${userId}`, { method: 'DELETE' }),

  // -- Fontes de dados ----------------------------------------------------
  listDatasources: (projectId) =>
    request(`/api/admin/datasources${buildQuery({ project_id: projectId })}`),
  getDatasource: (id) => request(`/api/admin/datasources/${id}`),
  createDatasource: (payload) =>
    request('/api/admin/datasources', { method: 'POST', body: payload }),
  updateDatasource: (id, payload) =>
    request(`/api/admin/datasources/${id}`, { method: 'PATCH', body: payload }),
  deleteDatasource: (id) => request(`/api/admin/datasources/${id}`, { method: 'DELETE' }),
  testDatasource: (id) => request(`/api/admin/datasources/${id}/test`, { method: 'POST' }),
  discoverDatasource: (id, schemas) =>
    request(`/api/admin/datasources/${id}/discover`, {
      method: 'POST',
      body: { schemas: schemas || [] },
    }),
  listObjects: (id, opts = {}) =>
    request(
      `/api/admin/datasources/${id}/objects${buildQuery({
        object_type: opts.objectType,
        only_allowed: opts.onlyAllowed ? 'true' : undefined,
      })}`,
    ),
  authorizeObjects: (id, objectIds, allowed) =>
    request(`/api/admin/datasources/${id}/objects/authorize`, {
      method: 'POST',
      body: { object_ids: objectIds, allowed },
    }),

  // -- Endpoints ----------------------------------------------------------
  listEndpoints: (projectId) =>
    request(`/api/admin/endpoints${buildQuery({ project_id: projectId })}`),
  getEndpoint: (id) => request(`/api/admin/endpoints/${id}`),
  createEndpoint: (payload) => request('/api/admin/endpoints', { method: 'POST', body: payload }),
  updateEndpoint: (id, payload) =>
    request(`/api/admin/endpoints/${id}`, { method: 'PATCH', body: payload }),
  deleteEndpoint: (id) => request(`/api/admin/endpoints/${id}`, { method: 'DELETE' }),
  listVersions: (id) => request(`/api/admin/endpoints/${id}/versions`),
  createVersion: (id, payload) =>
    request(`/api/admin/endpoints/${id}/versions`, { method: 'POST', body: payload }),
  getVersion: (id, versionId) => request(`/api/admin/endpoints/${id}/versions/${versionId}`),
  validateVersion: (id, versionId) =>
    request(`/api/admin/endpoints/${id}/versions/${versionId}/validate`, { method: 'POST' }),
  publishVersion: (id, versionId) =>
    request(`/api/admin/endpoints/${id}/versions/${versionId}/publish`, { method: 'POST' }),
  rollbackVersion: (id, versionId) =>
    request(`/api/admin/endpoints/${id}/versions/${versionId}/rollback`, { method: 'POST' }),
  archiveVersion: (id, versionId) =>
    request(`/api/admin/endpoints/${id}/versions/${versionId}/archive`, { method: 'POST' }),
  diffVersions: (id, versionId, against) =>
    request(`/api/admin/endpoints/${id}/versions/${versionId}/diff${buildQuery({ against })}`),
  deactivateEndpoint: (id) =>
    request(`/api/admin/endpoints/${id}/deactivate`, { method: 'POST' }),
  playground: (id, payload) =>
    request(`/api/admin/endpoints/${id}/playground`, { method: 'POST', body: payload }),

  // -- API keys -----------------------------------------------------------
  listApiKeys: (projectId) =>
    request(`/api/admin/api-keys${buildQuery({ project_id: projectId })}`),
  createApiKey: (payload) => request('/api/admin/api-keys', { method: 'POST', body: payload }),
  revokeApiKey: (id) => request(`/api/admin/api-keys/${id}/revoke`, { method: 'POST' }),
  deleteApiKey: (id) => request(`/api/admin/api-keys/${id}`, { method: 'DELETE' }),

  // -- Usuarios -----------------------------------------------------------
  listUsers: () => request('/api/admin/users'),
  getUser: (id) => request(`/api/admin/users/${id}`),
  createUser: (payload) => request('/api/admin/users', { method: 'POST', body: payload }),
  updateUser: (id, payload) =>
    request(`/api/admin/users/${id}`, { method: 'PATCH', body: payload }),
  deleteUser: (id) => request(`/api/admin/users/${id}`, { method: 'DELETE' }),

  // -- Logs e runtime -----------------------------------------------------
  requestLogs: (filters = {}) =>
    request(
      `/api/admin/logs/requests${buildQuery({
        endpoint_id: filters.endpointId,
        project_id: filters.projectId,
        status_min: filters.statusMin,
        limit: filters.limit,
      })}`,
    ),
  auditLogs: (filters = {}) =>
    request(
      `/api/admin/logs/audit${buildQuery({ action: filters.action, limit: filters.limit })}`,
    ),
  stats: () => request('/api/admin/logs/stats'),
  runtime: () => request('/api/admin/logs/runtime'),
  rebuildRuntime: () => request('/api/admin/logs/runtime/rebuild', { method: 'POST' }),
  purgeLogs: (olderThanDays) =>
    request(`/api/admin/logs/purge${buildQuery({ older_than_days: olderThanDays })}`, {
      method: 'POST',
    }),

  // -- Sistema ------------------------------------------------------------
  health: () => request('/health', { auth: false }),
};
