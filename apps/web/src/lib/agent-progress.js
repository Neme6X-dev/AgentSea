/**
 * Traduction de l'avancement backend vers les six agents de la scène 3D.
 *
 * Le backend raisonne en étapes de pipeline (`design`, `code`, `review`, `deploy`),
 * la scène en agents. Ce module fait la correspondance à un seul endroit, pour que la
 * scène affiche le travail réel plutôt qu'une animation décorative.
 *
 * Deux agents n'ont pas d'étape dédiée côté backend :
 * - **Orchestration** ouvre la session et pilote la séquence : il travaille tant que
 *   le reste n'est pas terminé.
 * - **Contenu** est produit par l'agent codeur en même temps que la mise en page ;
 *   il suit donc l'étape `code`.
 */

/** Ordre des agents dans `agents-scene.js`. */
export const AGENT_ORDER = [
  'Orchestration',
  'Conception & Design',
  'Contenu',
  'Gestion & Build',
  'Qualité & Sécurité',
  'Déploiement',
];

/** Étape backend pilotant chaque agent, et libellés par défaut. */
const MAPPING = [
  { step: null, idle: 'En attente du brief', working: 'Coordination des agents', done: 'Séquence terminée' },
  { step: 'design', idle: 'En attente', working: 'Choix des couleurs et de la mise en page', done: 'Spécification prête' },
  { step: 'code', idle: 'En attente', working: 'Rédaction des textes et des sections', done: 'Contenu intégré' },
  { step: 'code', idle: 'En attente', working: 'Génération du HTML, CSS et JavaScript', done: 'Site construit' },
  { step: 'review', idle: 'En attente', working: 'Analyse qualité, accessibilité et sécurité', done: 'Revue passée' },
  { step: 'deploy', idle: 'En attente', working: 'Publication du site', done: 'Site en ligne' },
];

const TERMINAL = ['deployed', 'ready', 'error', 'failed'];

/**
 * État de repos : aucune génération en cours.
 *
 * Laisser tourner l'animation décorative avant le premier prompt donnerait à voir des
 * agents affairés sur un projet qui n'existe pas.
 */
export function idleStatuses() {
  return MAPPING.map((agent) => ({ state: 'idle', detail: agent.idle }));
}

/**
 * Dernier état connu d'une étape, d'après l'historique de la session.
 *
 * On parcourt à rebours : `steps` est un journal, une étape relancée y figure
 * plusieurs fois et c'est la dernière entrée qui décrit l'état courant.
 */
function lastEntry(steps, name) {
  for (let i = steps.length - 1; i >= 0; i--) {
    if (steps[i]?.step === name) return steps[i];
  }
  return null;
}

/**
 * Construit l'état des six agents depuis une `SessionView`.
 *
 * Retourne un tableau `{state, detail}` aligné sur `AGENT_ORDER`, directement
 * consommable par `applyStatuses()` de la scène.
 */
export function agentStatuses(view) {
  const steps = view?.steps || [];
  const finished = TERMINAL.includes(view?.status);
  const failed = view?.status === 'error' || view?.status === 'failed';

  return MAPPING.map((agent) => {
    if (agent.step === null) {
      // Orchestration : au travail tant que la séquence n'est pas close.
      if (!steps.length) return { state: 'working', detail: agent.working };
      return finished
        ? { state: 'done', detail: failed ? 'Séquence interrompue' : agent.done }
        : { state: 'working', detail: agent.working };
    }

    const entry = lastEntry(steps, agent.step);
    if (!entry) return { state: 'idle', detail: agent.idle };

    if (entry.status === 'done') {
      // Le détail du backend est plus précis que le libellé générique (numéro de
      // version, score de revue, URL publiée) : on le préfère quand il existe.
      return { state: 'done', detail: entry.detail || agent.done };
    }
    if (entry.status === 'failed') {
      return { state: 'done', detail: entry.detail || 'Échec' };
    }
    return { state: 'working', detail: entry.detail || agent.working };
  });
}
