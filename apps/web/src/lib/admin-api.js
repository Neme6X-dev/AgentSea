/**
 * Client du back-office.
 *
 * Séparé de `api.js` volontairement : les deux ne s'adressent pas au même public et
 * n'ont pas le même contrat d'erreur. Un client qui reçoit un 403 doit voir « accès
 * refusé » ; un membre de l'équipe qui reçoit un 404 sur `/api/admin/...` doit
 * comprendre que son rôle ne suffit pas — le backend répond 404 plutôt que 403 pour
 * ne pas confirmer l'existence de ces routes à un compte ordinaire.
 *
 * Toutes les fonctions renvoient les objets du backend tels quels. Le calcul métier
 * (agrégats, pourcentages, libellés) est fait côté serveur : le dashboard dessine,
 * il ne recalcule pas — sans quoi deux écrans finiraient par afficher deux vérités.
 */
import { apiUrl } from './config.js';
import { getToken, redirectToLogin } from './auth.js';

export class AdminError extends Error {
  constructor(message, { status, detail, forbidden = false } = {}) {
    super(message);
    this.name = 'AdminError';
    this.status = status;
    this.detail = detail;
    /** Vrai quand le compte est authentifié mais n'a pas le rôle requis. */
    this.forbidden = forbidden;
  }
}

async function request(path, { method = 'GET', body, signal } = {}) {
  const token = getToken();
  if (!token) {
    redirectToLogin();
    throw new AdminError('Session expirée', { status: 401 });
  }

  const headers = { Authorization: `Bearer ${token}` };
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let response;
  try {
    response = await fetch(apiUrl(path), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
    });
  } catch (cause) {
    if (cause.name === 'AbortError') throw cause;
    throw new AdminError('Backend injoignable.');
  }

  if (response.status === 204) return null;
  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    if (response.status === 401) {
      redirectToLogin();
      throw new AdminError('Session expirée', { status: 401 });
    }
    // 404 sur une route d'administration signifie « rôle insuffisant » : le backend
    // ne confirme pas l'existence du back-office à un compte qui n'y a pas droit.
    // On le traduit ici pour que l'interface affiche un message juste.
    const forbidden = response.status === 403 || (response.status === 404 && path.startsWith('/api/admin'));
    throw new AdminError(message(response.status, payload?.detail, forbidden), {
      status: response.status,
      detail: payload?.detail,
      forbidden,
    });
  }

  return payload;
}

function message(status, detail, forbidden) {
  if (forbidden) return "Votre compte n'a pas accès à l'administration.";
  if (typeof detail === 'string') return detail;
  if (detail?.message) return detail.message;
  if (Array.isArray(detail) && detail[0]?.msg) return detail.map((e) => e.msg).join(', ');
  return `Erreur ${status}`;
}

function query(params = {}) {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') search.set(k, String(v));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : '';
}

/* --- Vue d'ensemble et analytics ------------------------------------------- */

export const analytics = {
  /** Tout l'écran d'accueil en un appel : KPIs, entonnoir, répartitions, file. */
  overview: (days = 30) => request(`/api/admin/overview${query({ days })}`),

  series: (metric, days = 30, granularity = 'day') =>
    request(`/api/admin/timeseries${query({ metric, days, granularity })}`),

  multiSeries: (metrics, days = 30, granularity = 'day') =>
    request(`/api/admin/timeseries/multi${query({ metrics: metrics.join(','), days, granularity })}`),

  geography: (days = 90) => request(`/api/admin/analytics/geography${query({ days })}`),
  funnel: (days = 30) => request(`/api/admin/analytics/funnel${query({ days })}`),
  cohorts: (months = 6) => request(`/api/admin/analytics/cohorts${query({ months })}`),
  businessTypes: (days = 90) => request(`/api/admin/analytics/business-types${query({ days })}`),
  traffic: (days = 30) => request(`/api/admin/analytics/traffic${query({ days })}`),
  quality: (days = 30) => request(`/api/admin/analytics/quality${query({ days })}`),
  agents: (days = 30) => request(`/api/admin/analytics/agents${query({ days })}`),
  topUsers: (days = 30) => request(`/api/admin/analytics/top-users${query({ days })}`),
  activity: (limit = 50) => request(`/api/admin/activity${query({ limit })}`),
};

/* --- Comptes ---------------------------------------------------------------- */

export const users = {
  list: (params = {}) => request(`/api/admin/users${query(params)}`),
  get: (id) => request(`/api/admin/users/${id}`),
  /** Modifie un compte. Le corps ne porte que ce qui change — l'audit n'enregistre que ça. */
  update: (id, changes) => request(`/api/admin/users/${id}`, { method: 'PATCH', body: changes }),
  suspend: (id, note) => request(`/api/admin/users/${id}`, { method: 'PATCH', body: { status: 'suspended', note } }),
  reactivate: (id) => request(`/api/admin/users/${id}`, { method: 'PATCH', body: { status: 'active' } }),
};

/* --- Sites ------------------------------------------------------------------ */

export const sites = {
  list: (params = {}) => request(`/api/admin/sites${query(params)}`),
};

/* --- File de travaux -------------------------------------------------------- */

export const jobs = {
  list: (params = {}) => request(`/api/admin/jobs${query(params)}`),
  stats: () => request('/api/admin/jobs/stats'),
  retry: (id) => request(`/api/admin/jobs/${id}/retry`, { method: 'POST' }),
  reclaim: () => request('/api/admin/jobs/reclaim', { method: 'POST' }),
};

/* --- Exploitation ----------------------------------------------------------- */

export const audit = (params = {}) => request(`/api/admin/audit${query(params)}`);
export const system = () => request('/api/admin/system');
export const config = () => request('/api/admin/config');

export const flags = {
  list: () => request('/api/admin/flags'),
  set: (key, value) => request(`/api/admin/flags/${key}`, { method: 'PUT', body: value }),
};
