// Modèle d'état du pipeline de génération — SOURCE DE VÉRITÉ de l'animation.
//
// Ce module ne connaît rien de la 3D. Il expose, pour chaque tâche du pipeline,
// un statut ('idle' | 'working' | 'done') et une progression (0..1) à un instant
// donné. La scène 3D lit ce statut à chaque frame ; elle ne génère JAMAIS de
// mouvement aléatoire.
//
// Le pipeline est SÉRIE (les tâches s'enchaînent), ce qui reflète le vrai flux
// de génération (Orchestration → Design → Contenu → Build → Qualité →
// Déploiement). La timeline est déterministe : mêmes entrées → mêmes sorties.
//
// Faute de backend, la timeline est simulée, mais l'API est pensée pour pouvoir
// être pilotée par de vrais statuts (setStatus / complete) si une source réelle
// est branchée plus tard.

export function createPipeline(taskIds, opts = {}) {
  const {
    stepDuration = 0.85, // durée de « travail » de base par tâche (s)
    weights = null,      // durées relatives par tâche (optionnel)
    gap = 0.12,          // pause de passation entre deux tâches (s)
    overlap = 0.12,      // fraction de la tâche précédente où la suivante démarre
    hold = 1.8,          // temps « tout terminé » avant rebouclage (s)
    loop = true,
  } = opts;

  const n = taskIds.length;
  const w = weights && weights.length === n ? weights : taskIds.map(() => 1);

  // Fenêtres [start, end] de chaque tâche sur la timeline, calculées une fois.
  const windows = [];
  let cursor = 0;
  for (let i = 0; i < n; i++) {
    const dur = stepDuration * w[i];
    const start = i === 0 ? 0 : Math.max(0, cursor - dur * overlap);
    const end = start + dur;
    windows.push({ start, end });
    cursor = end + gap;
  }

  const workEnd = windows[n - 1].end;
  const total = workEnd + hold;

  let startTime = null;                 // défini par start()
  let forcedDone = false;               // « tout terminé » forcé (fin de génération réelle)
  const external = new Array(n).fill(null); // statuts réels optionnels par tâche

  function start(now) { startTime = now; forcedDone = false; }
  function reset() { startTime = null; forcedDone = false; external.fill(null); }
  function complete() { forcedDone = true; }
  function setStatus(i, state) { external[i] = state; }

  function statusAt(i, now) {
    if (external[i]) {
      const s = external[i];
      return { state: s, progress: s === 'done' ? 1 : s === 'working' ? 0.5 : 0 };
    }
    if (forcedDone) return { state: 'done', progress: 1 };
    if (startTime == null) return { state: 'idle', progress: 0 };

    const t = now - startTime;
    const { start: s, end: e } = windows[i];
    if (t < s) return { state: 'idle', progress: 0 };
    if (t < e) return { state: 'working', progress: (t - s) / (e - s) };
    return { state: 'done', progress: 1 };
  }

  return {
    get total() { return total; },
    get workEnd() { return workEnd; },
    loop,
    start,
    reset,
    complete,
    setStatus,
    statusAt,
    elapsed(now) { return startTime == null ? 0 : now - startTime; },
    isFinished(now) { return startTime != null && now - startTime >= total; },
  };
}
