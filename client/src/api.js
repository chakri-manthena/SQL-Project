const apiOrigin = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '');

export function apiUrl(path) {
  return `${apiOrigin}/api/v1${path}`;
}

export function apiFetch(path, options = {}) {
  return fetch(apiUrl(path), {
    ...options,
    credentials: 'include',
  });
}