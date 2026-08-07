import { defineConfig } from 'vite';
import { resolve } from 'node:path';

const PAGES = [
  // Produit
  'index',
  'projets',
  'editeur',
  'agents',
  'ressources',
  'parametres',
  'aide',
  'connexion',
  // Back-office. Ces pages partagent leur ossature (`src/lib/admin-shell.js`) mais
  // restent des entrées distinctes : chacune a son URL, et un lien vers un écran
  // d'administration doit ouvrir cet écran, pas une application à router côté client.
  'admin',
  'admin-analytics',
  'admin-utilisateurs',
  'admin-sites',
  'admin-agents',
  'admin-systeme',
  'admin-journal',
];

export default defineConfig({
  // Application multi-pages : chaque écran reste un vrai fichier HTML servi à son
  // URL propre, il n'y a pas de routeur côté client.
  appType: 'mpa',

  build: {
    // Les bundles générés vont dans `bundle/` et non `assets/` : `public/assets/`
    // contient déjà les modèles 3D et le décodeur Draco, qui sont copiés tels quels
    // à la racine du build. Sans ce renommage les deux se retrouveraient dans le
    // même dossier de sortie.
    assetsDir: 'bundle',

    // three pèse ~650 ko à lui seul. Il est isolé dans son propre chunk, chargé
    // en import dynamique uniquement quand une scène 3D est montée : l'avertir à
    // chaque build n'apporte rien.
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      input: Object.fromEntries(
        PAGES.map((page) => [page, resolve(import.meta.dirname, `${page}.html`)]),
      ),
    },
  },

  server: {
    port: 5173,
    // Le backend tourne séparément (FastAPI sur :8000). Ce proxy fait passer les
    // appels d'API par l'origine du front en développement, ce qui évite le
    // préflight CORS et permet de garder VITE_API_BASE_URL vide en local.
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // Aperçus des sites générés, servis en statique par le backend.
      '/sites': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});
