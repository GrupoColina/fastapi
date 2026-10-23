// Estado da sessao: guarda os tokens e o usuario autenticado no localStorage.
// Nao depende de nenhum outro modulo para evitar ciclos de importacao.

const ACCESS_KEY = 'studio.access_token';
const REFRESH_KEY = 'studio.refresh_token';
const USER_KEY = 'studio.user';

export function getAccessToken() {
  return localStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY);
}

export function getStoredUser() {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function setUser(user) {
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function setTokens(tokenResponse) {
  localStorage.setItem(ACCESS_KEY, tokenResponse.access_token);
  localStorage.setItem(REFRESH_KEY, tokenResponse.refresh_token);
  if (tokenResponse.user) setUser(tokenResponse.user);
}

export function clearSession() {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
  localStorage.removeItem(USER_KEY);
}

export function isAuthenticated() {
  return Boolean(getAccessToken() && getRefreshToken());
}
