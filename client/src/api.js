export function apiUrl(path) {
  return `/api/v1${path}`;
}

export function apiFetch(path, options = {}) {
  return fetch(apiUrl(path), {
    ...options,
    credentials: 'include',
  });
}