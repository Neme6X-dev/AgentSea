/**
 * Projets : liste des sessions de l'utilisateur, chacune ouvrant l'éditeur.
 *
 * La page portait déjà sa grille et ses cartes de maquette ; il manquait le
 * branchement. Sans lui, un site généré n'était plus atteignable qu'en connaissant
 * l'URL de sa session — les projets existaient en base sans exister pour l'utilisateur.
 */
import '../main.js';
import { mountAppShell } from '../lib/app-shell.js';
import { sessions } from '../lib/api.js';
import { isAuthenticated, redirectToLogin } from '../lib/auth.js';
import { previewUrl } from '../lib/config.js';

const el = (id) => document.getElementById(id);

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = String(text);
  return div.innerHTML;
}

/** Ancienneté en clair — « il y a 2 h » se lit mieux qu'une date ISO. */
function since(iso) {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return '';
  const minutes = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `il y a ${hours} h`;
  const days = Math.round(hours / 24);
  if (days < 7) return `il y a ${days} j`;
  return `il y a ${Math.round(days / 7)} sem.`;
}

/** Pastille d'état, pour distinguer un site en ligne d'une génération en cours. */
function badge(view) {
  if (view.status === 'error') {
    return '<span class="bg-error/20 text-error border border-error/30 px-1.5 py-0.5 rounded text-[10px] font-label-md">Échec</span>';
  }
  if (view.published_version != null) {
    return '<span class="bg-surface text-on-surface border border-outline-variant/30 px-1.5 py-0.5 rounded text-[10px] font-label-md">En ligne</span>';
  }
  if (view.versions?.length) {
    return '<span class="bg-surface text-on-surface-variant border border-outline-variant/30 px-1.5 py-0.5 rounded text-[10px] font-label-md">Brouillon</span>';
  }
  return '<span class="bg-surface text-on-surface-variant border border-outline-variant/30 px-1.5 py-0.5 rounded text-[10px] font-label-md">En cours…</span>';
}

/**
 * Vignette d'un projet.
 *
 * Le site publié est affiché dans une iframe inerte plutôt qu'en image : le backend ne
 * produit pas de capture, et montrer une photo de banque d'images à la place ferait
 * passer un projet pour un autre.
 */
function thumbnail(view) {
  const url = view.site_url || view.previews?.at(-1)?.url;
  if (!url) {
    return `<div class="w-full h-full flex items-center justify-center bg-surface-container-high">
        <span class="material-symbols-outlined text-2xl text-on-surface-variant/40">hourglass_top</span>
      </div>`;
  }
  return `<iframe src="${escapeHtml(previewUrl(url))}" sandbox="" loading="lazy" tabindex="-1"
      class="w-full h-full border-0 bg-white pointer-events-none origin-top-left"
      style="width:400%;height:400%;transform:scale(0.25)"></iframe>`;
}

function card(view) {
  const title = view.slug || 'Sans titre';
  return `
  <a class="bg-surface-container border border-outline-variant/20 hover:border-outline-variant hover:bg-surface-container-high rounded-xl p-1.5 flex flex-col group cursor-pointer transition-all duration-300"
     href="editeur.html?session=${encodeURIComponent(view.id)}">
    <div class="relative w-full aspect-[4/3] rounded-lg overflow-hidden mb-1.5 bg-surface-container-high">
      ${thumbnail(view)}
      <div class="absolute inset-0 bg-gradient-to-t from-background/80 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300 flex items-end justify-between p-1.5">
        <span class="bg-surface text-on-surface border border-outline-variant/30 px-1.5 py-0.5 rounded text-[10px] font-label-md flex items-center gap-1">
          <span class="material-symbols-outlined text-xs">edit</span> Modifier
        </span>
        ${badge(view)}
      </div>
    </div>
    <div class="px-0.5 flex justify-between items-start gap-1">
      <div class="min-w-0">
        <h3 class="font-label-md text-label-md font-bold text-on-surface truncate group-hover:text-primary transition-colors">${escapeHtml(title)}</h3>
        <p class="text-[10.5px] text-on-surface-variant flex items-center gap-1 mt-0.5">
          <span class="material-symbols-outlined text-[12px]">schedule</span> ${escapeHtml(since(view.updated_at || view.created_at))}
        </p>
      </div>
    </div>
  </a>`;
}

function renderEmpty(list, text) {
  list.innerHTML = `<p class="col-span-full font-body-sm text-body-sm text-on-surface-variant/70 py-4">${escapeHtml(text)}</p>`;
}

async function init() {
  mountAppShell({ active: 'projets.html', title: 'Projets' });

  if (!isAuthenticated()) {
    redirectToLogin();
    return;
  }

  const list = el('projects-list');
  if (!list) return;

  try {
    const views = await sessions.list();
    if (!views.length) {
      renderEmpty(list, "Aucun projet pour l'instant. Décrivez votre site depuis l'accueil pour en créer un.");
      return;
    }
    // Le plus récemment touché d'abord : c'est celui qu'on revient consulter.
    views.sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
    list.innerHTML = views.map(card).join('');
  } catch (error) {
    renderEmpty(list, 'Impossible de charger vos projets pour le moment.');
    console.error(error);
  }
}

document.addEventListener('DOMContentLoaded', init);
