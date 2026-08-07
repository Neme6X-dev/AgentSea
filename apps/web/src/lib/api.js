/**
 * Client du backend de génération de sites vitrines.
 *
 * Miroir du contrat décrit dans backend-jarvis/docs/API.md. Les fonctions renvoient
 * les objets du backend tels quels (SessionView, ReviewReport…) : ce module ne
 * remodèle pas les données, il ne gère que le transport et les erreurs.
 */
import { apiUrl } from './config.js';
import { getToken, redirectToLogin } from './auth.js';

/**
 * Erreur d'API portant de quoi décider quoi faire, et pas seulement quoi afficher.
 *
 * `retryable` distingue la panne amont (502 du fournisseur LLM) du refus définitif :
 * c'est le seul cas où réessayer a un sens. `detail` conserve le corps structuré du
 * backend — un 409 de publication y met le score et les findings bloquants.
 */
export class ApiError extends Error {
  constructor(message, { status, detail, retryable = false } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.retryable = retryable;
  }
}

async function request(path, { method = 'GET', body, auth = true, signal } = {}) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  if (auth) {
    const token = getToken();
    // Partir sans jeton produirait un 401 qu'on traiterait ensuite comme une panne.
    // Autant renvoyer tout de suite l'utilisateur se connecter.
    if (!token) {
      redirectToLogin();
      throw new ApiError('Session expirée', { status: 401 });
    }
    headers.Authorization = `Bearer ${token}`;
  }

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
    // Réseau coupé ou backend éteint : aucune réponse, donc aucun statut. C'est
    // réessayable, contrairement à un refus explicite du serveur.
    throw new ApiError('Backend injoignable.', { retryable: true });
  }

  if (response.status === 204) return null;

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    if (response.status === 401) {
      redirectToLogin();
      throw new ApiError('Session expirée', { status: 401 });
    }
    const detail = payload?.detail;
    throw new ApiError(errorMessage(response.status, detail), {
      status: response.status,
      detail,
      retryable: payload?.retryable === true,
    });
  }

  return payload;
}

function errorMessage(status, detail) {
  if (typeof detail === 'string') return detail;
  if (detail?.message) return detail.message;
  // 422 de FastAPI : liste d'erreurs de validation Pydantic.
  if (Array.isArray(detail) && detail[0]?.msg) return detail.map((e) => e.msg).join(', ');
  return `Erreur ${status}`;
}

/* --- Authentification ------------------------------------------------------ */

export const auth = {
  register: (email, password, name) =>
    request('/api/auth/register', { method: 'POST', auth: false, body: { email, password, name } }),

  login: (email, password) =>
    request('/api/auth/login', { method: 'POST', auth: false, body: { email, password } }),

  /** `id_token` obtenu via Google Identity Services côté navigateur. */
  google: (idToken) =>
    request('/api/auth/google', { method: 'POST', auth: false, body: { id_token: idToken } }),

  /** `code` de l'aller-retour OAuth GitHub ; l'échange se fait côté backend. */
  github: (code) =>
    request('/api/auth/github', { method: 'POST', auth: false, body: { code } }),

  me: () => request('/api/auth/me'),
};

/* --- Sessions (un site = une session) -------------------------------------- */

export const sessions = {
  create: (prompt) => request('/api/sessions', { method: 'POST', body: { prompt } }),

  list: () => request('/api/sessions'),

  get: (id, { signal } = {}) => request(`/api/sessions/${id}`, { signal }),

  artifacts: (id) => request(`/api/sessions/${id}/artifacts`),

  /**
   * Retouche ou refonte.
   *
   * Par défaut (`tweak`), le site actuel est transmis au codeur qui doit le
   * préserver. Fournir un `design_spec` — ou `mode: 'redesign'` — vaut refonte :
   * le site actuel n'est alors pas transmis, sans quoi le modèle recopierait le
   * design qu'on cherche justement à remplacer.
   */
  edit: (id, instruction, { mode, designSpec } = {}) =>
    request(`/api/sessions/${id}/edit`, {
      method: 'POST',
      body: {
        instruction,
        ...(mode ? { mode } : {}),
        ...(designSpec ? { design_spec: designSpec } : {}),
      },
    }),

  /**
   * Met une version en ligne. `version: null` publie la dernière générée ;
   * publier une version antérieure est le retour arrière.
   *
   * Lève une ApiError 409 si la version visée a le verdict `fail` — `detail`
   * contient alors `score` et `blocking_findings`, à montrer avant de rappeler
   * la fonction avec `force: true`.
   */
  publish: (id, { version = null, force = false } = {}) =>
    request(`/api/sessions/${id}/publish`, { method: 'POST', body: { version, force } }),

  retry: (id) => request(`/api/sessions/${id}/retry`, { method: 'POST' }),
};

/**
 * Cadrage conversationnel — relais vers l'agent n8n.
 *
 * L'agent mène l'entretien et ne rend un `design_spec` qu'une fois le besoin cerné :
 * tant qu'il est nul, il reste des questions à poser et il n'y a rien à générer.
 * `available: false` signale que n8n n'a pas répondu — `reply` porte alors un message
 * explicatif, à afficher tel quel.
 */
export const chat = {
  send: (message, conversationId = null) =>
    request('/api/chat', {
      method: 'POST',
      body: { message, ...(conversationId ? { conversation_id: conversationId } : {}) },
    }),
};

/** Pipeline complet en un appel : design → code → revue → publication. */
export const dev = {
  generate: (prompt, designSpec = null) =>
    request('/api/dev/generate', {
      method: 'POST',
      body: { prompt, ...(designSpec ? { design_spec: designSpec } : {}) },
    }),
};

export const health = () => request('/api/health', { auth: false });

/* --- Compte : offre, quotas, paiement --------------------------------------- */

export const account = {
  /** Offre, consommation et contexte pays du compte courant. */
  overview: () => request('/api/account'),

  /** Grille tarifaire complète, localisée dans la devise du compte (ou `country`). */
  plans: (country) => request(`/api/account/plans${country ? `?country=${encodeURIComponent(country)}` : ''}`),

  /** Moyens de paiement disponibles pour le pays du compte. */
  paymentOptions: () => request('/api/account/payment-options'),
};

/* --- Suivi de génération ---------------------------------------------------- */

const TERMINAL_STATUSES = ['deployed', 'ready', 'error', 'failed'];

/**
 * Interroge une session jusqu'à ce que son statut soit terminal.
 *
 * Le backend ne pousse rien : la génération dure des dizaines de secondes et le
 * seul moyen de suivre l'avancement est de relire la SessionView. `onUpdate` est
 * appelé à chaque réponse pour rafraîchir l'affichage des étapes.
 */
export async function pollSession(id, { onUpdate, intervalMs = 2000, timeoutMs = 300000, signal } = {}) {
  const deadline = Date.now() + timeoutMs;

  for (;;) {
    const view = await sessions.get(id, { signal });
    onUpdate?.(view);

    if (TERMINAL_STATUSES.includes(view.status)) return view;

    if (Date.now() > deadline) {
      throw new ApiError('La génération dépasse le délai attendu.', { detail: view });
    }

    await new Promise((resolve, reject) => {
      const timer = setTimeout(resolve, intervalMs);
      signal?.addEventListener('abort', () => {
        clearTimeout(timer);
        reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
      }, { once: true });
    });
  }
}
