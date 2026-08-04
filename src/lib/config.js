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
