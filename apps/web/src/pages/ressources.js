/**
 * Ressources : galerie de gabarits de démarrage.
 *
 * La page était la seule, avec l'aide, à pointer directement sur `main.js` — elle
 * n'avait donc pas de module propre et ne pouvait rien monter. Elle en a un
 * maintenant, ne serait-ce que pour l'ossature de navigation.
 */
import '../main.js';
import { mountAppShell } from '../lib/app-shell.js';

document.addEventListener('DOMContentLoaded', () => {
  mountAppShell({ active: 'ressources.html', title: 'Ressources' });
});
