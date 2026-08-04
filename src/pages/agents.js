// Page Agents : styles communs + montage de la scène 3D.
import '../main.js';

const block = document.getElementById('agents-scene-block');
const viewport = document.getElementById('agents-scene-viewport');

/**
 * WebGL manque sur certaines machines (rendu logiciel désactivé, GPU en liste
 * noire, navigateur durci). La page Agents reste utilisable sans la scène : on
 * laisse alors le bloc caché plutôt que d'afficher un cadre vide.
 */
function webglAvailable() {
  try {
    return Boolean(document.createElement('canvas').getContext('webgl2')
      || document.createElement('canvas').getContext('webgl'));
  } catch {
    return false;
  }
}

if (block && viewport && webglAvailable()) {
  block.classList.remove('hidden');

  // Import dynamique : three et la scène pèsent ~650 ko, à ne pas faire porter au
  // premier rendu d'une page dont le contenu utile est la grille de configuration.
  import('../scene/agents-scene.js')
    .then(({ initAgentsScene }) => initAgentsScene(viewport))
    .catch((error) => {
      // Un échec de chargement des modèles ne doit pas laisser le spinner tourner
      // indéfiniment ni casser le reste de la page.
      console.error('Scène 3D des agents indisponible :', error);
      block.classList.add('hidden');
    });
}
