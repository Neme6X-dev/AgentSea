/**
 * Stockage du jeton utilisateur.
 *
 * Le backend authentifie par en-tête `Authorization: Bearer`, pas par cookie —
 * il n'y a donc rien à envoyer automatiquement, et `allow_credentials` reste à
 * false côté CORS. On garde le JWT en localStorage : il survit à un rechargement,
 * ce qui est le comportement attendu d'un dashboard.
 *
 * Aucune décision de sécurité ne repose sur ce qui est lu ici : `isAuthenticated()`
 * sert à choisir quoi afficher, c'est le backend qui tranche à chaque appel.
 */
const TOKEN_KEY = 'jarvisToken';
const USER_KEY = 'jarvisUser';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

/** Enregistre la réponse d'un endpoint d'authentification (`TokenResponse`). */
export function setSession({ access_token, user }) {
  localStorage.setItem(TOKEN_KEY, access_token);
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getUser() {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    // Entrée corrompue (édition manuelle, changement de format) : on repart à zéro
    // plutôt que de laisser une exception casser le rendu de la page.
    localStorage.removeItem(USER_KEY);
    return null;
  }
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

/** Vrai si un jeton non expiré est présent. */
export function isAuthenticated() {
  const token = getToken();
  if (!token) return false;
  const expiry = tokenExpiry(token);
  return expiry === null || expiry > Date.now();
}

/** Date d'expiration du JWT en millisecondes, ou null si illisible. */
export function tokenExpiry(token = getToken()) {
  if (!token) return null;
  const payload = token.split('.')[1];
  if (!payload) return null;
  try {
    const json = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')));
    return typeof json.exp === 'number' ? json.exp * 1000 : null;
  } catch {
    return null;
  }
}

/**
 * Renvoie vers la page de connexion en mémorisant la destination voulue.
 *
 * La destination est stockée sans son `/` initial : `connexion.js` n'accepte qu'un
 * chemin relatif, pour qu'un `next` fabriqué ne puisse pas renvoyer l'utilisateur
 * fraîchement connecté vers un domaine tiers.
 */
export function redirectToLogin() {
  const target = (window.location.pathname + window.location.search).replace(/^\/+/, '');
  clearSession();
  window.location.href = `connexion.html?next=${encodeURIComponent(target)}`;
}
