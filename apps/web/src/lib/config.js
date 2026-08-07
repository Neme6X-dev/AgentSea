/**
 * Origine du backend.
 *
 * Laissée vide en développement : les appels partent alors en relatif (`/api/...`)
 * et le proxy déclaré dans vite.config.js les transmet à FastAPI. On évite ainsi
 * le préflight CORS et la divergence entre l'origine du front et celle des aperçus.
 *
 * En production, renseigner VITE_API_BASE_URL avec l'origine publique du backend
 * (sans slash final) — c'est aussi elle que le backend utilise pour construire les
 * URLs de sites via son PUBLIC_BASE_URL.
 */
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '');

/** Construit une URL d'API absolue ou relative selon la configuration. */
export function apiUrl(path) {
  return `${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`;
}

/**
 * Ramène l'URL d'un site généré sur l'origine du front.
 *
 * Le backend construit ses `site_url` depuis son propre `PUBLIC_BASE_URL`, qui vaut
 * `127.0.0.1:8000` en local — une origine tierce pour la page servie par Vite sur
 * `:5173`. Repasser par le proxy garde l'aperçu sur la même origine, ce qui évite
 * qu'un backend joignable par le navigateur mais pas par cette origine affiche une
 * iframe vide sans le moindre message.
 */
export function previewUrl(url) {
  if (!url) return url;
  const path = url.replace(/^https?:\/\/[^/]+/, '');
  return path.startsWith('/sites/') ? apiUrl(path) : url;
}
