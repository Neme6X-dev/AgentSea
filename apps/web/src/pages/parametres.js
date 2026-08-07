/**
 * Paramètres : remplit la section « Détails du profil » avec l'utilisateur réellement
 * connecté (jusqu'ici la page affichait un profil de démonstration figé en dur, quel
 * que soit le compte connecté), et la section « Abonnement & Facturation » avec le
 * forfait, la consommation et les moyens de paiement réels du compte (jusqu'ici
 * « Constructeur Pro », « 49 $ / mois » et une carte Visa •••• 4242 en dur — le même
 * écran pour tout le monde, quel que soit le forfait ou le pays réellement souscrits).
 *
 * `getUser()` sert un affichage immédiat depuis la session locale ; `auth.me()`
 * rafraîchit en tâche de fond au cas où le nom aurait changé depuis un autre appareil.
 * Le backend n'expose qu'un seul champ `name` (pas prénom/nom séparés) : on le
 * scinde sur le premier espace, seule heuristique possible sans casser la mise en
 * page à deux colonnes existante.
 */
import '../main.js';
import { mountAppShell } from '../lib/app-shell.js';
import { auth, account } from '../lib/api.js';
import { getUser, isAuthenticated, redirectToLogin } from '../lib/auth.js';

const el = (id) => document.getElementById(id);

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = String(text);
  return div.innerHTML;
}

function splitName(name) {
  const trimmed = (name || '').trim();
  if (!trimmed) return { firstName: '', lastName: '' };
  const [firstName, ...rest] = trimmed.split(/\s+/);
  return { firstName, lastName: rest.join(' ') };
}

function initials({ firstName, lastName }, email) {
  const source = `${firstName?.[0] || ''}${lastName?.[0] || ''}` || email?.[0] || '?';
  return source.toUpperCase();
}

function renderProfile(user) {
  if (!user) return;
  const { firstName, lastName } = splitName(user.name);
  const firstnameInput = el('profile-firstname');
  const lastnameInput = el('profile-lastname');
  const emailInput = el('profile-email');
  const avatar = el('profile-avatar-initials');

  if (firstnameInput) firstnameInput.value = firstName;
  if (lastnameInput) lastnameInput.value = lastName;
  if (emailInput) emailInput.value = user.email || '';
  if (avatar) avatar.textContent = initials({ firstName, lastName }, user.email);
}

/* --- Abonnement & Facturation ------------------------------------------------ */

/** Ligne de consommation (générations, sites, collaborateurs), en barre si bornée. */
function usageRow({ label, used, limit, percent }) {
  const unlimited = limit < 0;
  const row = document.createElement('div');
  row.className = 'flex flex-col gap-1';

  const top = document.createElement('div');
  top.className = 'flex items-center justify-between font-label-md text-label-md text-on-surface-variant';
  const left = document.createElement('span');
  left.textContent = label;
  const right = document.createElement('span');
  right.className = 'text-on-surface';
  right.textContent = unlimited ? 'Illimité' : `${used} / ${limit}`;
  top.append(left, right);
  row.appendChild(top);

  if (!unlimited) {
    const track = document.createElement('div');
    track.className = 'h-1.5 rounded-full bg-surface-container-highest overflow-hidden';
    const fill = document.createElement('div');
    fill.className = 'h-full rounded-full bg-on-surface transition-[width] duration-300';
    fill.style.width = `${Math.min(100, Math.max(0, percent))}%`;
    track.appendChild(fill);
    row.appendChild(track);
  }
  return row;
}

/** Remplit la carte « Forfait actuel » : nom, prix localisé, avantages, consommation. */
function renderBillingPlan(overview, planOffer) {
  const nameEl = el('billing-plan-name');
  const priceEl = el('billing-plan-price');
  const highlightsEl = el('billing-plan-highlights');
  const usageEl = el('billing-usage');
  if (!nameEl || !priceEl || !highlightsEl || !usageEl) return;

  nameEl.textContent = overview.plan_name;

  const price = planOffer?.monthly;
  priceEl.textContent = !price || price.amount === 0
    ? 'Gratuit'
    : `${price.formatted} / ${price.period}`;

  highlightsEl.innerHTML = '';
  for (const highlight of (planOffer?.highlights || []).slice(0, 4)) {
    const row = document.createElement('div');
    row.className = 'flex items-center gap-1.5 font-label-md text-label-md text-on-surface-variant';
    row.innerHTML = `<span class="material-symbols-outlined text-sm text-on-surface shrink-0">check</span> <span>${escapeHtml(highlight)}</span>`;
    highlightsEl.appendChild(row);
  }

  usageEl.innerHTML = '';
  for (const usage of overview.usage || []) {
    usageEl.appendChild(usageRow(usage));
  }
}

/** Remplit la carte « Moyens de paiement » : devise du compte + options réelles du pays. */
function renderPaymentOptions(options) {
  const intro = el('billing-payment-intro');
  const list = el('billing-payment-methods');
  if (!intro || !list) return;

  intro.textContent = `Pour régler votre abonnement depuis ${options.country} (${options.currency}) :`;

  list.innerHTML = '';
  for (const operator of options.mobile_money || []) {
    const chip = document.createElement('span');
    chip.className =
      'inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-surface-container border border-outline-variant/25 font-label-md text-label-md text-on-surface';
    chip.innerHTML =
      `<span class="w-2 h-2 rounded-full shrink-0" style="background:${escapeHtml(operator.color || '#888')}"></span> ${escapeHtml(operator.name)}`;
    list.appendChild(chip);
  }
  // Moyens hors mobile money (virement, espèces…) : mêmes chips, sans pastille de couleur.
  const named = new Set((options.mobile_money || []).map((o) => o.name));
  for (const method of options.methods || []) {
    if (named.has(method)) continue;
    const chip = document.createElement('span');
    chip.className =
      'inline-flex items-center px-2.5 py-1.5 rounded-lg bg-surface-container border border-outline-variant/25 font-label-md text-label-md text-on-surface-variant';
    chip.textContent = method;
    list.appendChild(chip);
  }
}

async function loadBilling() {
  try {
    const overview = await account.overview();
    // Le prix n'est pas dans l'aperçu du compte (`AccountOverview` ne porte pas de
    // tarif) : il vient de la grille complète, localisée dans la devise du compte.
    const catalog = await account.plans().catch(() => []);
    const planOffer = catalog.find((p) => p.key === overview.plan) || null;
    renderBillingPlan(overview, planOffer);
  } catch {
    // Panne réseau ou backend éteint : les autres sections restent utilisables,
    // la carte de forfait garde son état « … » plutôt que de casser la page.
  }

  try {
    renderPaymentOptions(await account.paymentOptions());
  } catch {
    // Idem : pas de panneau de paiement plutôt qu'une page qui casse.
  }
}

function init() {
  mountAppShell({ active: 'parametres.html', title: 'Paramètres' });

  if (!isAuthenticated()) {
    redirectToLogin();
    return;
  }

  // Affichage immédiat depuis la session locale, avant même la réponse réseau.
  renderProfile(getUser());

  auth
    .me()
    .then(renderProfile)
    .catch(() => {
      // Le cache local suffit à afficher la page ; une panne réseau ici ne doit pas
      // empêcher de consulter le reste des paramètres.
    });

  loadBilling();
}

document.addEventListener('DOMContentLoaded', init);
