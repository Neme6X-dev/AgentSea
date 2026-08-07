/**
 * Aide : questions fréquentes.
 *
 * La page était la seule, avec les ressources, à pointer directement sur `main.js` —
 * elle n'avait donc pas de module propre et ne pouvait rien monter.
 *
 * Le dépliement et le filtre des questions restent dans le script inline de la page :
 * ils fonctionnent, ne dépendent d'aucun import, et les déplacer ici n'apporterait
 * rien qu'un risque de régression sur un comportement déjà correct.
 */
import '../main.js';
import { mountAppShell } from '../lib/app-shell.js';

document.addEventListener('DOMContentLoaded', () => {
  mountAppShell({ active: 'aide.html', title: 'Aide' });
});
