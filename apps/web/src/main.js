// Entrée commune à toutes les pages du dashboard.
//
// Son seul rôle est de faire passer la feuille Tailwind par le build : jusqu'ici
// le thème était recompilé dans le navigateur par le CDN `cdn.tailwindcss.com`,
// ce qui interdisait tout import npm et rechargeait la config à chaque page.
//
// La logique de repli de la navigation reste volontairement inline dans les pages :
// elle doit s'exécuter avant le premier rendu pour éviter que la barre latérale
// s'affiche dépliée puis saute, or un module ES est toujours différé.
import './styles/tailwind.css';
import { clearSession } from './lib/auth.js';

// Le lien « Déconnexion » de la nav est un `<a href="connexion.html">` statique sur
// chaque page : sans ceci, le jeton restait en localStorage et `connexion.js`
// renvoyait aussitôt l'utilisateur « déconnecté » dans l'app (isAuthenticated()
// toujours vrai), comme si le bouton n'avait rien fait.
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('a[href="connexion.html"]').forEach((link) => {
    link.addEventListener('click', () => clearSession());
  });
});
