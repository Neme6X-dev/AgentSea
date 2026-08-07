/**
 * Éditeur : cadrage conversationnel → génération → aperçu → mise en ligne.
 *
 * Le prompt de l'utilisateur n'part pas directement au générateur. Il ouvre une
 * conversation avec l'agent de cadrage (n8n), qui pose les questions nécessaires pour
 * cerner le besoin. Sans cette étape, un simple « bonjour » suffirait à produire un
 * site que personne n'a demandé.
 *
 * La génération se déclenche quand l'agent a rendu son `design_spec`, ou quand
 * l'utilisateur décide explicitement qu'il en a assez dit.
 */
import '../main.js';
import { chat, dev, sessions, pollSession, ApiError } from '../lib/api.js';
import { agentStatuses, idleStatuses } from '../lib/agent-progress.js';
import { isAuthenticated, redirectToLogin } from '../lib/auth.js';
import { apiUrl, previewUrl } from '../lib/config.js';
import { mountAppShell } from '../lib/app-shell.js';

/** Session de génération courante, conservée pour publier la bonne version. */
let current = null;

/** Fil de cadrage : identifiant côté n8n, transcription, et spec une fois obtenu. */
const conversation = {
  id: null,
  transcript: [],
  spec: null,
  busy: false,
};

const el = (id) => document.getElementById(id);

/* --- Affichage du chat ------------------------------------------------------ */

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = String(text);
  return div.innerHTML;
}

/** Ajoute un message au fil et fait défiler jusqu'à lui. */
function addMessage(role, text) {
  const list = el('chat-messages');
  if (!list) return;

  const row = document.createElement('div');
  row.className = role === 'user' ? 'flex gap-2 flex-row-reverse' : 'flex gap-2';
  row.innerHTML =
    role === 'user'
      ? `<div class="w-6 h-6 rounded-full bg-surface-container flex items-center justify-center shrink-0 border border-outline-variant/20">
           <span class="material-symbols-outlined text-sm text-on-surface-variant">person</span>
         </div>
         <div class="flex flex-col gap-1 pt-0.5 bg-surface-container-high rounded-xl rounded-tr-sm p-2.5 max-w-[85%] border border-outline-variant/10">
           <div class="text-on-surface text-body-md font-body-md whitespace-pre-wrap">${escapeHtml(text)}</div>
         </div>`
      : `<div class="w-6 h-6 rounded-full bg-surface-container flex items-center justify-center shrink-0 border border-outline-variant/30">
           <span class="material-symbols-outlined text-sm text-on-surface-variant">auto_awesome</span>
         </div>
         <div class="flex flex-col gap-1.5 pt-0.5 max-w-[85%]">
           <div class="text-on-surface text-body-md font-body-md leading-relaxed whitespace-pre-wrap">${escapeHtml(text)}</div>
         </div>`;

  // Le bloc d'état de génération reste en dernier : les messages s'insèrent avant lui.
  const status = el('gen-status-block');
  if (status && status.parentElement === list) list.insertBefore(row, status);
  else list.appendChild(row);

  list.scrollTop = list.scrollHeight;
}

/**
 * Indicateur « l'agent réfléchit », avec le temps écoulé.
 *
 * Les tours de cadrage prennent une vingtaine de secondes, mais celui qui tranche le
 * template et les pages met **plusieurs minutes**. Sans compteur ni avertissement,
 * cette attente est indiscernable d'un blocage et l'utilisateur recharge la page.
 */
let thinkingTimer = null;

function showThinking(on) {
  const list = el('chat-messages');
  if (!list) return;

  if (!on) {
    if (thinkingTimer != null) {
      window.clearInterval(thinkingTimer);
      thinkingTimer = null;
    }
    el('chat-thinking')?.remove();
    return;
  }
  if (el('chat-thinking')) return;

  const row = document.createElement('div');
  row.id = 'chat-thinking';
  row.className = 'flex gap-2';
  row.innerHTML = `
    <div class="w-6 h-6 rounded-full bg-surface-container flex items-center justify-center shrink-0 border border-outline-variant/50 glow-active">
      <span class="material-symbols-outlined text-sm text-on-surface-variant animate-pulse" style="font-variation-settings: 'FILL' 1;">auto_awesome</span>
    </div>
    <div class="flex flex-col gap-1.5 pt-0.5 w-full max-w-[85%]">
      <div class="text-on-surface-variant text-label-md font-label-md animate-pulse" id="chat-thinking-label">L'assistant analyse votre demande…</div>
      <div class="h-10 rounded-lg ai-shimmer border border-outline-variant/10 w-full"></div>
    </div>`;

  const status = el('gen-status-block');
  if (status && status.parentElement === list) list.insertBefore(row, status);
  else list.appendChild(row);
  list.scrollTop = list.scrollHeight;

  const startedAt = Date.now();
  thinkingTimer = window.setInterval(() => {
    const label = el('chat-thinking-label');
    if (!label) return;
    const seconds = Math.round((Date.now() - startedAt) / 1000);
    const clock = seconds < 60 ? `${seconds} s` : `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
    label.textContent =
      seconds < 45
        ? `L'assistant analyse votre demande… (${clock})`
        : `L'assistant compose votre projet — cette étape prend plusieurs minutes. (${clock})`;
  }, 1000);
}

/**
 * Reflète l'état du cadrage sur le bouton de génération.
 *
 * Il n'apparaît qu'après un premier échange : proposer de générer avant d'avoir dit
 * quoi que ce soit reviendrait à contourner le cadrage qu'on vient de mettre en place.
 */
function refreshGenerateButton() {
  const button = el('generate-btn');
  const label = el('generate-btn-label');
  if (!button) return;

  // Une fois le site généré, le chat sert à le retoucher : un bouton « Générer »
  // n'aurait plus de sens, et inviterait à repartir de zéro.
  const started = conversation.transcript.length > 0 && !current;
  button.classList.toggle('hidden', !started);
  button.classList.toggle('flex', started);
  button.disabled = conversation.busy;
  if (label) {
    label.textContent = conversation.spec
      ? `Générer le site — ${conversation.spec.name}`
      : 'Générer le site avec ces éléments';
  }
}

function setChatBusy(on) {
  conversation.busy = on;
  const input = el('chat-input');
  const send = el('chat-send');
  if (input) {
    input.disabled = on;
    // L'invite dit ce que le prochain message va faire : cadrer, ou retoucher.
    input.placeholder = current
      ? 'Décrivez la modification à apporter…'
      : "Décrivez votre projet — l'assistant vous posera quelques questions…";
  }
  if (send) send.disabled = on;
  refreshGenerateButton();
}

/* --- Cadrage ---------------------------------------------------------------- */

async function sendMessage(text) {
  if (!text || conversation.busy) return;

  addMessage('user', text);
  const input = el('chat-input');
  if (input) input.value = '';

  // Un site existe déjà : le message est une demande de retouche, pas un nouveau
  // projet. Le repasser au cadrage produirait un second site au lieu de modifier
  // celui que l'utilisateur a sous les yeux.
  if (current) {
    await applyEdit(text);
    return;
  }

  conversation.transcript.push({ role: 'user', text });
  setChatBusy(true);
  showThinking(true);
  try {
    const response = await chat.send(text, conversation.id);
    conversation.id = response.conversation_id;
    showThinking(false);
    addMessage('agent', response.reply);
    conversation.transcript.push({ role: 'agent', text: response.reply });

    if (response.design_spec) {
      conversation.spec = response.design_spec;
      // L'agent a tranché : on enchaîne sans demander une confirmation de plus.
      await generate();
      return;
    }
  } catch (error) {
    showThinking(false);
    addMessage('agent', message(error));
  } finally {
    setChatBusy(false);
  }
}

/* --- Retouche d'un site existant -------------------------------------------- */

/**
 * Applique une instruction au site courant et produit une nouvelle version.
 *
 * Tant que rien n'est publié, la nouvelle version part directement en ligne. Dès qu'un
 * site est publié, l'édition s'arrête en prévisualisation : c'est le backend qui
 * tranche, et le front se contente de le refléter.
 */
async function applyEdit(instruction) {
  setChatBusy(true);
  showGenerating(true);
  renderSteps([], 'Application de votre demande…');
  window.jarvisSetPreviewTab?.('scene3d');

  try {
    await sessions.edit(current.id, instruction);

    current = await pollSession(current.id, {
      intervalMs: 1500,
      onUpdate: (view) => {
        renderSteps(view.steps);
        driveScene(view);
      },
    });
    driveScene(current);

    if (current.status === 'error') {
      const detail = current.error || 'La modification a échoué.';
      renderSteps(current.steps, detail);
      addMessage('agent', detail);
      return;
    }

    const preview = current.previews?.at(-1);
    showPreview(preview?.url || current.site_url);
    renderCode(preview?.url || current.site_url);
    window.jarvisFinishGeneration?.();

    // Une version prête mais non publiée doit être annoncée comme telle : laisser
    // croire qu'elle est en ligne enverrait l'utilisateur vérifier une URL inchangée.
    const pending = preview && preview.published === false;
    addMessage(
      'agent',
      pending
        ? `Nouvelle version prête (v${preview.version}). Elle n'est pas encore en ligne — utilisez « Publier » pour remplacer le site actuel.`
        : `C'est fait. Votre site est à jour : ${current.site_url || ''}`.trim(),
    );
  } catch (error) {
    renderSteps([], message(error));
    addMessage('agent', message(error));
  } finally {
    showGenerating(false);
    setChatBusy(false);
  }
}

/**
 * Brief transmis au backend quand le cadrage n'a pas produit de `design_spec`.
 *
 * On envoie la transcription entière plutôt que le seul premier message : les
 * précisions arrachées par l'agent sont justement ce qui distingue un bon site d'un
 * site générique.
 */
function briefFromConversation() {
  const lines = conversation.transcript.map(
    ({ role, text }) => `${role === 'user' ? 'Client' : 'Assistant'} : ${text}`,
  );
  // Le backend borne le prompt à 8000 caractères ; on garde la fin, plus précise.
  return lines.join('\n').slice(-7500);
}

/* --- Génération ------------------------------------------------------------- */

function showGenerating(on) {
  el('toolbar-generating')?.classList.toggle('hidden', !on);
  el('gen-status-block')?.classList.toggle('hidden', !on);

  // `toolbar-done` est authoré en `hidden items-center` : lui retirer `hidden` ne
  // suffit pas, il lui faut aussi son display, sinon les onglets s'empilent.
  const done = el('toolbar-done');
  done?.classList.toggle('hidden', on);
  done?.classList.toggle('flex', !on);
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
  frame.src = previewUrl(url);

  pane.classList.remove('hidden');
  pane.classList.add('flex');
  el('view-code')?.classList.add('hidden');
  el('view-scene3d')?.classList.add('hidden');

  // Sur téléphone, l'aperçu est derrière la conversation : le site vient d'être
  // produit, l'afficher sans y amener l'utilisateur reviendrait à ne rien lui
  // montrer du résultat qu'il attend.
  focusPreviewPane();
}

/* --- Code source du site généré --------------------------------------------- */

// Fixé par le backend (app/services.py: write_site_files) : un site généré a
// toujours exactement ces trois fichiers, jamais plus, jamais moins.
const CODE_FILES = ['index.html', 'style.css', 'script.js'];

let codeFiles = {};       // nom de fichier -> contenu texte
let codeActiveFile = null;

/**
 * Récupère et affiche le code source de la version courante dans l'onglet Code.
 *
 * `base` est l'URL du dossier de version (`.../sites/<slug>/v<N>/`) : les fichiers
 * y sont servis en statique par le backend, comme le site lui-même. Silencieux en cas
 * d'échec — l'onglet garde alors son état vide plutôt que d'afficher du code faux.
 */
async function renderCode(base) {
  const empty = el('code-empty');
  const viewer = el('code-viewer');
  const tabs = el('code-file-tabs');
  if (!base || !empty || !viewer || !tabs) return;

  const racine = base.endsWith('/') ? base : `${base}/`;
  const résultats = await Promise.all(
    CODE_FILES.map(async (nom) => {
      try {
        const res = await fetch(previewUrl(`${racine}${nom}`));
        if (!res.ok) return null;
        return [nom, await res.text()];
      } catch {
        return null;
      }
    }),
  );

  codeFiles = Object.fromEntries(résultats.filter(Boolean));
  const disponibles = CODE_FILES.filter((nom) => nom in codeFiles);
  if (!disponibles.length) return; // rien d'exploitable : on laisse l'état vide affiché

  tabs.innerHTML = disponibles
    .map((nom) => `<button type="button" class="code-tab-btn px-2.5 py-1 rounded-md text-label-md font-label-md transition-colors hover:text-on-surface" data-file="${nom}">${nom}</button>`)
    .join('');
  tabs.querySelectorAll('.code-tab-btn').forEach((btn) => {
    btn.addEventListener('click', () => selectCodeFile(btn.dataset.file));
  });

  empty.classList.add('hidden');
  viewer.classList.remove('hidden');
  viewer.classList.add('flex');
  selectCodeFile(disponibles[0]);
}

function selectCodeFile(nom) {
  if (!(nom in codeFiles)) return;
  codeActiveFile = nom;
  const content = el('code-content');
  if (content) content.textContent = codeFiles[nom];
  document.querySelectorAll('.code-tab-btn').forEach((btn) => {
    const actif = btn.dataset.file === nom;
    btn.classList.toggle('bg-surface-container-high', actif);
    btn.classList.toggle('text-on-surface', actif);
    btn.classList.toggle('text-on-surface-variant', !actif);
  });
}

/**
 * Affiche l'URL en ligne dans le popover de déploiement.
 *
 * Écrit dans le texte du statut plutôt que de remplacer tout `#deploy-pop` : une
 * édition génère des versions non publiées qu'on republie ensuite depuis ce même
 * popover (« Nouvelle version prête… utilisez Publier »), donc `#deploy-btn` doit
 * rester dans le DOM après le premier déploiement, pas être écrasé avec le lien.
 */
function setDeployed(url) {
  const label = el('deploy-status-label');
  if (!label) return;
  if (url) {
    label.innerHTML = `En ligne · <a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" class="underline break-all">${escapeHtml(url)}</a>`;
  } else {
    label.textContent = 'En ligne';
  }
}

/**
 * Reflète l'avancement réel sur la scène 3D des agents.
 *
 * La scène se charge de façon asynchrone (modèles glTF) et peut n'être pas prête quand
 * les premiers statuts arrivent. On retient alors le dernier état connu et on le
 * rejoue dès qu'elle apparaît, plutôt que de perdre les premières étapes.
 */
let pendingStatuses = null;
let flushTimer = null;

function applyToScene(statuses) {
  const scene = window.jarvisAgentsScene;
  if (scene?.applyStatuses) {
    scene.applyStatuses(statuses);
    return true;
  }
  pendingStatuses = statuses;
  if (flushTimer == null) {
    flushTimer = window.setInterval(() => {
      if (window.jarvisAgentsScene?.applyStatuses && pendingStatuses) {
        window.jarvisAgentsScene.applyStatuses(pendingStatuses);
        pendingStatuses = null;
        window.clearInterval(flushTimer);
        flushTimer = null;
      }
    }, 400);
  }
  return false;
}

function driveScene(view) {
  applyToScene(agentStatuses(view));
}

async function generate() {
  if (!conversation.transcript.length) {
    el('chat-input')?.focus();
    return;
  }

  setChatBusy(true);
  showGenerating(true);
  renderSteps([], 'Lancement de la génération…');
  addMessage('agent', 'Je lance la génération de votre site. Suivez le travail des agents dans la scène 3D.');

  // On regarde les agents travailler : c'est la vue qui a du sens pendant l'attente.
  window.jarvisSetPreviewTab?.('scene3d');

  try {
    // La génération est asynchrone : cet appel rend la main dès la session ouverte,
    // et le pipeline se poursuit côté serveur. C'est ce qui permet de suivre
    // l'avancement réel plutôt que d'animer une barre dans le vide.
    current = await dev.generate(briefFromConversation(), conversation.spec);
    renderSteps(current.steps, 'Génération lancée…');
    driveScene(current);

    current = await pollSession(current.id, {
      intervalMs: 1500,
      onUpdate: (view) => {
        renderSteps(view.steps);
        driveScene(view);
      },
    });

    driveScene(current);

    if (current.status === 'error') {
      const detail = current.error || 'La génération a échoué.';
      renderSteps(current.steps, detail);
      addMessage('agent', detail);
      return;
    }

    const preview = current.previews?.at(-1);
    showPreview(preview?.url || current.site_url);
    renderCode(preview?.url || current.site_url);
    if (current.published_version != null) setDeployed(current.site_url);

    // Bascule la barre d'outils sur l'état « terminé » et bascule sur l'aperçu :
    // la transition est définie dans la page, on ne la réécrit pas ici.
    window.jarvisFinishGeneration?.();

    addMessage(
      'agent',
      current.site_url
        ? `Votre site est en ligne : ${current.site_url}\nDites-moi ce que vous voulez ajuster.`
        : 'Le site est généré. Dites-moi ce que vous voulez ajuster.',
    );
  } catch (error) {
    renderSteps([], message(error));
    addMessage('agent', message(error));
  } finally {
    showGenerating(false);
    setChatBusy(false);
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

/* --- Bascule conversation / aperçu (sous 768 px) ---------------------------- */

/**
 * Sur téléphone, les deux panneaux occupent l'écran chacun à leur tour.
 *
 * Ils se partageaient la hauteur moitié-moitié : sur un écran de 640 px, cela
 * laissait 320 px à chacun, dont la moitié consommée côté conversation par
 * l'en-tête et la zone de saisie. L'aperçu d'un site dans 320 px de haut ne montre
 * rien qu'on puisse juger, et c'est pourtant le seul objet de la page.
 *
 * La bascule est ajoutée à la barre supérieure montée par l'ossature partagée —
 * c'est le seul endroit toujours visible, quel que soit le panneau affiché.
 */
function mountPaneSwitch() {
  const topbar = document.querySelector('.app-topbar');
  if (!topbar) return;

  const group = document.createElement('div');
  group.className =
    'ml-auto flex items-center gap-0.5 p-0.5 rounded-full bg-surface-container/80 ' +
    'border border-outline-variant/25 shrink-0';
  group.setAttribute('role', 'tablist');
  group.setAttribute('aria-label', "Panneau affiché");

  const panes = [
    { key: 'chat', icon: 'forum', label: 'Discussion' },
    { key: 'preview', icon: 'visibility', label: 'Aperçu' },
  ];

  const buttons = panes.map(({ key, icon, label }) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.role = 'tab';
    button.dataset.pane = key;
    button.className =
      'editor-switch-btn flex items-center gap-1 px-2.5 py-1.5 rounded-full ' +
      'font-label-md text-label-md text-on-surface-variant transition-colors';
    button.innerHTML =
      `<span class="material-symbols-outlined text-base">${icon}</span>` +
      `<span class="sr-only sm:not-sr-only">${label}</span>`;
    button.setAttribute('aria-label', label);
    button.addEventListener('click', () => show(key));
    group.appendChild(button);
    return button;
  });

  function show(key) {
    const root = document.documentElement;
    root.classList.toggle('editor-view-chat', key === 'chat');
    root.classList.toggle('editor-view-preview', key === 'preview');
    for (const button of buttons) {
      button.setAttribute('aria-selected', String(button.dataset.pane === key));
    }
  }

  topbar.appendChild(group);
  // On démarre sur la conversation : tant que rien n'est généré, l'aperçu n'a
  // rien à montrer, et c'est bien dans le fil que la première action se passe.
  show('chat');

  // Un site fraîchement publié ou généré mérite d'être vu : on bascule pour
  // l'utilisateur plutôt que de compter sur lui pour découvrir l'onglet.
  return { show };
}

/** Bascule mobile ; `null` tant que l'ossature n'est pas montée. */
let paneSwitch = null;

/** Amène l'aperçu au premier plan sur téléphone. Sans effet au format bureau. */
export function focusPreviewPane() {
  paneSwitch?.show('preview');
}

function init() {
  if (!isAuthenticated()) {
    redirectToLogin();
    return;
  }

  mountAppShell({ active: 'editeur.html', title: 'Éditeur', variant: 'rail' });
  paneSwitch = mountPaneSwitch();

  showGenerating(false);
  renderSteps([], '');
  // Agents au repos tant qu'aucun projet n'est lancé.
  applyToScene(idleStatuses());

  const input = el('chat-input');
  input?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendMessage(input.value.trim());
    }
  });
  el('chat-send')?.addEventListener('click', () => sendMessage(input?.value.trim()));
  el('generate-btn')?.addEventListener('click', () => generate());

  // « Publier » ouvre le popover de confirmation (géré par le script classique
  // d'editeur.html, exposé sur `window`) ; c'est son bouton « Déployer maintenant »
  // qui déclenche la publication réelle. Les deux gestes appelaient publish()
  // séparément avant ce correctif : la popover s'ouvrait sur un état encore factice
  // pendant que la publication réelle partait déjà en arrière-plan.
  // Tant qu'aucune session n'existe, l'action est le cadrage.
  el('publish-btn')?.addEventListener('click', () => {
    if (!current) {
      el('chat-input')?.focus();
      return;
    }
    window.jarvisTogglePublish?.();
  });
  el('deploy-btn')?.addEventListener('click', () => publish());

  const params = new URLSearchParams(window.location.search);

  // Reprise d'une session existante : ?session=<id>
  const id = params.get('session');
  if (id) {
    sessions
      .get(id)
      .then((view) => {
        current = view;
        renderSteps(view.steps);
        driveScene(view);
        showPreview(view.previews?.at(-1)?.url || view.site_url);
        renderCode(view.previews?.at(-1)?.url || view.site_url);
        if (view.published_version != null) setDeployed(view.site_url);
        if (view.published_version != null) window.jarvisFinishGeneration?.();
      })
      .catch(() => {});
  }

  // Prompt saisi sur l'accueil : il ouvre le cadrage sans que l'utilisateur ait à le
  // retaper. On nettoie l'URL pour qu'un rechargement ne renvoie pas deux fois le
  // même message à l'agent.
  const prompt = params.get('prompt');
  if (prompt) {
    window.history.replaceState({}, '', window.location.pathname);
    sendMessage(prompt.trim());
  } else if (!id) {
    addMessage(
      'agent',
      "Bonjour ! Décrivez-moi votre projet de site — activité, ambiance, ce que vos visiteurs doivent y trouver. Je vous poserai quelques questions avant de lancer la génération.",
    );
  }

  // Utile en console pour vérifier la cible du backend.
  console.info('Backend :', apiUrl('/api/health'));
}

document.addEventListener('DOMContentLoaded', init);
