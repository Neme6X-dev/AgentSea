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
