import { getAccessToken } from './auth.js';

const BASE = '';

async function authedFetch(path, options = {}) {
  const token = await getAccessToken();
  const headers = { 'Content-Type': 'application/json', ...(options.headers ?? {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const r = await fetch(BASE + path, { ...options, headers });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${r.status}`);
  }
  return r.json();
}

function buildQuery(params) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null) p.set(k, String(v));
  }
  const q = p.toString();
  return q ? '?' + q : '';
}

export const api = {
  // Teams
  teams: {
    list: () => authedFetch('/api/teams'),
    create: (data) => authedFetch('/api/teams', { method: 'POST', body: JSON.stringify(data) }),
    get: (id) => authedFetch(`/api/teams/${id}`),
    update: (id, data) => authedFetch(`/api/teams/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    del: (id) => authedFetch(`/api/teams/${id}`, { method: 'DELETE' }),
    invite: (teamId, data) => authedFetch(`/api/teams/${teamId}/members`, { method: 'POST', body: JSON.stringify(data) }),
    removeMember: (teamId, userId) => authedFetch(`/api/teams/${teamId}/members/${userId}`, { method: 'DELETE' }),
  },

  // Projects
  projects: {
    list: (teamId) => authedFetch(`/api/teams/${teamId}/projects`),
    create: (data) => authedFetch('/api/projects', { method: 'POST', body: JSON.stringify(data) }),
    get: (id) => authedFetch(`/api/projects/${id}`),
    update: (id, data) => authedFetch(`/api/projects/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
    del: (id) => authedFetch(`/api/projects/${id}`, { method: 'DELETE' }),
    import_algolia: (id, data) => authedFetch(`/api/projects/${id}/import`, { method: 'POST', body: JSON.stringify(data) }),
    progress: (id) => authedFetch(`/api/projects/${id}/progress`),
    qaStats: (id) => authedFetch(`/api/projects/${id}/qa/stats`),
  },

  // Tasks
  tasks: {
    list: (projectId, params) => authedFetch(`/api/projects/${projectId}/tasks` + buildQuery(params)),
    next: (projectId) => authedFetch(`/api/projects/${projectId}/tasks/next`),
    get: (taskId) => authedFetch(`/api/tasks/${taskId}`),
    claim: (taskId) => authedFetch(`/api/tasks/${taskId}/claim`, { method: 'POST' }),
    skip: (taskId) => authedFetch(`/api/tasks/${taskId}/skip`, { method: 'POST' }),
    submit: (taskId, data) => authedFetch(`/api/tasks/${taskId}/submit`, { method: 'POST', body: JSON.stringify(data) }),
  },

  // Exports
  exports: {
    list: (projectId) => authedFetch(`/api/projects/${projectId}/exports`),
    create: (projectId, data) => authedFetch(`/api/projects/${projectId}/exports`, { method: 'POST', body: JSON.stringify(data) }),
  },
};