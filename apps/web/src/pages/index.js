/**
 * Accueil : la saisie du prompt ouvre le cadrage dans l'éditeur.
 *
 * Le prompt voyage dans l'URL plutôt que d'être perdu à la navigation : c'est la
 * première phrase de l'utilisateur, et la lui refaire taper après un détour par la
 * connexion est le meilleur moyen de lui faire abandonner.
 */
import '../main.js';
import { isAuthenticated } from '../lib/auth.js';
import { mountAppShell } from '../lib/app-shell.js';

function init() {
  mountAppShell({
    active: 'index.html',
    title: 'Accueil',
    // « Nouvelle application » depuis l'accueil ne recharge pas l'accueil : le
    // champ est déjà là, on y met le curseur.
    onNewApp: () => document.getElementById('prompt-input')?.focus(),
  });

  const form = document.getElementById('prompt-form');
  const input = document.getElementById('prompt-input');
  if (!form || !input) return;

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    start(input.value.trim());
  });

  // Entrée envoie, Maj+Entrée passe à la ligne — même convention que l'éditeur.
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      start(input.value.trim());
    }
  });

  // Le texte des suggestions vit en `data-prompt`. Il portait un `onclick` inline,
  // où l'apostrophe de « domaines d'intervention » fermait la chaîne JavaScript :
  // le bouton « Cabinet » levait une erreur de syntaxe au lieu de remplir le champ.
  for (const button of document.querySelectorAll('.jarvis-suggestion')) {
    button.addEventListener('click', () => {
      input.value = button.dataset.prompt || '';
      input.focus();
    });
  }
}

function start(prompt) {
  const target = prompt ? `editeur.html?prompt=${encodeURIComponent(prompt)}` : 'editeur.html';

  // Sans jeton, l'éditeur renverrait aussitôt vers la connexion : autant y aller
  // directement, en gardant le prompt dans la destination de retour.
  if (!isAuthenticated()) {
    window.location.href = `connexion.html?next=${encodeURIComponent(target)}`;
    return;
  }
  window.location.href = target;
}

document.addEventListener('DOMContentLoaded', init);
