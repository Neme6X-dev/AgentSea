/**
 * Connexion et inscription.
 *
 * Les deux formulaires de `connexion.html` sont déjà en place ; ce module les
 * soumet au backend et mémorise le jeton. Après succès, on repart vers la page
 * demandée initialement (`?next=`), sinon vers l'éditeur.
 */
import '../main.js';
import { auth, ApiError } from '../lib/api.js';
import { setSession, isAuthenticated } from '../lib/auth.js';

const el = (id) => document.getElementById(id);

function destination() {
  const next = new URLSearchParams(window.location.search).get('next');
  // On n'accepte qu'un chemin relatif : un `next` absolu permettrait de renvoyer
  // l'utilisateur connecté vers un domaine tiers.
  return next && next.startsWith('/') === false && !next.includes('//') ? next : 'editeur.html';
}

function showError(form, text) {
  let box = form.querySelector('[data-auth-error]');
  if (!box) {
    box = document.createElement('p');
    box.setAttribute('data-auth-error', '');
    box.className = 'text-error text-label-md font-label-md';
    form.prepend(box);
  }
  box.textContent = text;
}

function busy(form, on) {
  const submit = form.querySelector('button[type="submit"]');
  if (submit) {
    submit.disabled = on;
    submit.classList.toggle('opacity-60', on);
  }
}

async function submit(form, action) {
  busy(form, true);
  try {
    const response = await action();
    setSession(response);
    window.location.href = destination();
  } catch (error) {
    showError(
      form,
      error instanceof ApiError ? error.message : 'Connexion impossible. Réessayez.',
    );
  } finally {
    busy(form, false);
  }
}

function init() {
  if (isAuthenticated()) {
    window.location.href = destination();
    return;
  }

  const login = el('panel-login');
  login?.addEventListener('submit', (event) => {
    event.preventDefault();
    submit(login, () =>
      auth.login(el('login-email').value.trim(), el('login-password').value),
    );
  });

  // Le panneau d'inscription suit la même convention d'identifiants.
  const signup = el('panel-signup');
  signup?.addEventListener('submit', (event) => {
    event.preventDefault();
    const email = el('signup-email')?.value.trim();
    const password = el('signup-password')?.value;
    // Le backend n'a qu'un champ `name` : on recompose depuis prénom et nom.
    const name =
      [el('signup-firstname')?.value.trim(), el('signup-lastname')?.value.trim()]
        .filter(Boolean)
        .join(' ') || null;
    submit(signup, () => auth.register(email, password, name));
  });
}

document.addEventListener('DOMContentLoaded', init);
