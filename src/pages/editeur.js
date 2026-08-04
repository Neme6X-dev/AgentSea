/**
 * Éditeur : prompt → génération → aperçu → mise en ligne.
 *
 * Câble les maquettes de `editeur.html` sur le backend via `lib/api.js`. La page
 * portait déjà les identifiants et les états visuels ; il ne manquait que le
 * branchement.
 */
import '../main.js';
import { dev, sessions, ApiError } from '../lib/api.js';
import { isAuthenticated, redirectToLogin } from '../lib/auth.js';
import { apiUrl } from '../lib/config.js';

/** Session courante, conservée pour publier la bonne après génération. */
let current = null;

const el = (id) => document.getElementById(id);
const prompt = () => document.querySelector('textarea');

/* --- Affichage -------------------------------------------------------------- */

function showGenerating(on) {
  el('toolbar-generating')?.classList.toggle('hidden', !on);
  el('toolbar-done')?.classList.toggle('hidden', on);
  el('gen-status-block')?.classList.toggle('hidden', !on);
}

/** Remplace le squelette d'attente par l'avancement réel des étapes. */
function renderSteps(steps = [], fallback = '') {
  const box = el('gen-status-content');
  if (!box) return;
  const lines = steps.length
    ? steps.map((s) => `${s.status === 'done' ? '✓' : '…'} ${s.detail || s.step}`)
    : [fallback];
  box.innerHTML = lines
    .map(
      (line) =>
        `<div class="text-on-surface-variant text-label-md font-label-md">${escapeHtml(line)}</div>`,
    )
    .join('');
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = String(text);
  return div.innerHTML;
}

/** Affiche le site dans la fenêtre de navigateur simulée. */
function showPreview(url) {
  const pane = el('view-apercu');
  if (!pane || !url) return;

  let frame = pane.querySelector('iframe');
  if (!frame) {
    frame = document.createElement('iframe');
    frame.className = 'w-full flex-1 border-0 bg-white';
    // Le site vient d'un modèle : on le confine, il n'a aucune raison d'accéder
    // à la page qui l'héberge.
    frame.setAttribute('sandbox', 'allow-scripts');
    pane.appendChild(frame);
  }
  frame.src = url;

  pane.classList.remove('hidden');
  pane.classList.add('flex');
  el('view-code')?.classList.add('hidden');
  el('view-scene3d')?.classList.add('hidden');
}

function setDeployed(url) {
  el('deploy-disconnected')?.classList.add('hidden');
  el('deploy-connected')?.classList.remove('hidden');
  el('deploy-success')?.classList.remove('hidden');
  const label = el('deploy-status-label');
  if (label) label.textContent = 'En ligne';
  const pop = el('deploy-pop');
  if (pop && url) {
    pop.innerHTML = `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer"
      class="underline break-all">${escapeHtml(url)}</a>`;
  }
}

/* --- Actions ---------------------------------------------------------------- */

async function generate() {
  const text = prompt()?.value.trim();
  if (!text) {
    prompt()?.focus();
    return;
  }

  showGenerating(true);
  renderSteps([], 'Analyse de votre demande…');

  try {
    // `/api/dev/generate` enchaîne designer → codeur → revue → publication et ne
    // rend la main qu'à la fin : il n'y a rien à interroger pendant ce temps.
    current = await dev.generate(text);
    renderSteps(current.steps);

    const preview = current.previews?.at(-1);
    showPreview(preview?.url || current.site_url);
    if (current.published_version != null) setDeployed(current.site_url);

    if (prompt()) prompt().value = '';
  } catch (error) {
    renderSteps([], message(error));
  } finally {
    showGenerating(false);
  }
}

async function publish({ force = false } = {}) {
  if (!current) return;
  try {
    current = await sessions.publish(current.id, { force });
    setDeployed(current.site_url);
  } catch (error) {
    // 409 : la version a le verdict `fail`. On montre ce qui bloque et on laisse
    // l'utilisateur trancher plutôt que de publier dans son dos.
    if (error instanceof ApiError && error.status === 409) {
      const blocking = error.detail?.blocking_findings?.join('\n• ') || 'aucun détail';
      const ok = window.confirm(
        `${error.detail?.message || 'Cette version présente des problèmes.'}\n\n• ${blocking}\n\nPublier quand même ?`,
      );
      if (ok) await publish({ force: true });
      return;
    }
    window.alert(message(error));
  }
}

function message(error) {
  if (error instanceof ApiError) {
    return error.retryable ? `${error.message} Réessayez dans un instant.` : error.message;
  }
  return 'Une erreur inattendue est survenue.';
}

/* --- Démarrage -------------------------------------------------------------- */

function init() {
  if (!isAuthenticated()) {
    redirectToLogin();
    return;
  }

  // Entrée envoie, Maj+Entrée passe à la ligne.
  prompt()?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      generate();
    }
  });

  el('publish-btn')?.addEventListener('click', () => (current ? publish() : generate()));
  el('deploy-btn')?.addEventListener('click', () => publish());

  // Reprise d'une session existante : ?session=<id>
  const id = new URLSearchParams(window.location.search).get('session');
  if (id) {
    sessions
      .get(id)
      .then((view) => {
        current = view;
        renderSteps(view.steps);
        showPreview(view.previews?.at(-1)?.url || view.site_url);
        if (view.published_version != null) setDeployed(view.site_url);
      })
      .catch(() => {});
  }

  // Utile en console pour vérifier la cible du backend.
  console.info('Backend :', apiUrl('/api/health'));
}

document.addEventListener('DOMContentLoaded', init);
