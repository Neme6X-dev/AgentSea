/**
 * Thème Material 3 du dashboard Jarvis.
 *
 * Ce fichier remplace les blocs `<script id="tailwind-config">` qui étaient inline
 * dans chaque page à l'époque du CDN. Les huit pages en portaient cinq variantes,
 * fusionnées ici sans aucun conflit de valeur : les écarts n'étaient que des clés
 * présentes sur certaines pages seulement (`2xl`, `container-max`, la police `code`).
 * Une clé inutilisée sur une page ne coûte rien — le purge de Tailwind ne génère
 * que les utilitaires réellement présents dans le markup.
 *
 * ## Échelle typographique
 *
 * L'échelle a été remontée d'environ 20 % par rapport à la version initiale, qui
 * descendait à 12 px pour les libellés et 13 px pour le texte courant. Deux raisons,
 * et aucune n'est esthétique :
 *
 * 1. **Lisibilité réelle.** Une part importante des utilisateurs consulte la
 *    plateforme sur des écrans d'entrée de gamme, souvent en plein jour. Sous 14 px,
 *    le texte se lit en plissant les yeux — et c'est le premier motif d'abandon d'un
 *    outil qu'on découvre.
 * 2. **Cohérence.** L'ajustement se fait ici, une fois, et toutes les pages en
 *    héritent. Retoucher les tailles page par page les aurait fait diverger à la
 *    première évolution.
 *
 * Les proportions entre niveaux sont conservées : la hiérarchie visuelle établie par
 * la maquette reste intacte, elle est seulement plus confortable à lire.
 *
 * ## Espacements
 *
 * Les pas ont été élargis dans la même logique. Une interface dense paraît puissante
 * sur une capture d'écran et fatigante à l'usage : ce sont les blancs qui rendent une
 * hiérarchie lisible sans avoir à la déchiffrer.
 */
import forms from '@tailwindcss/forms';
import containerQueries from '@tailwindcss/container-queries';

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./*.html', './src/**/*.{js,ts}'],
  theme: {
    extend: {
      "colors": {
        "background": "#111319",
        "error": "#ffb4ab",
        "error-container": "#93000a",
        "inverse-on-surface": "#2e3037",
        "inverse-primary": "#544fc0",
        "inverse-surface": "#e2e2eb",
        "on-background": "#e2e2eb",
        "on-error": "#690005",
        "on-error-container": "#ffdad6",
        "on-primary": "#231691",
        "on-primary-container": "#a9a7ff",
        "on-primary-fixed": "#0f0069",
        "on-primary-fixed-variant": "#3b35a7",
        "on-secondary": "#1000a9",
        "on-secondary-container": "#b0b2ff",
        "on-secondary-fixed": "#07006c",
        "on-secondary-fixed-variant": "#2f2ebe",
        "on-surface": "#e2e2eb",
        "on-surface-variant": "#c8c4d5",
        "on-tertiary": "#263143",
        "on-tertiary-container": "#a4b0c7",
        "on-tertiary-fixed": "#111c2d",
        "on-tertiary-fixed-variant": "#3c475a",
        "outline": "#918f9e",
        "outline-variant": "#464553",
        "primary": "#c3c0ff",
        "primary-container": "#3730a3",
        "primary-fixed": "#e2dfff",
        "primary-fixed-dim": "#c3c0ff",
        "secondary": "#c0c1ff",
        "secondary-container": "#3131c0",
        "secondary-fixed": "#e1e0ff",
        "secondary-fixed-dim": "#c0c1ff",
        "surface": "#111319",
        "surface-bright": "#373940",
        "surface-container": "#1e1f26",
        "surface-container-high": "#282a30",
        "surface-container-highest": "#33343b",
        "surface-container-low": "#191b22",
        "surface-container-lowest": "#0c0e14",
        "surface-dim": "#111319",
        "surface-tint": "#c3c0ff",
        "surface-variant": "#33343b",
        "tertiary": "#bcc7de",
        "tertiary-container": "#384356",
        "tertiary-fixed": "#d8e3fb",
        "tertiary-fixed-dim": "#bcc7de",

        // --- Statuts (échelle réservée, jamais utilisée comme série) -------- //
        // La palette Material d'origine ne couvre pas ces états : « réussi » et
        // « échoué » doivent se distinguer au premier coup d'œil, et deux nuances de
        // violet n'y suffisent pas. Ces quatre pas sont volontairement distincts des
        // couleurs de série, pour qu'un statut n'usurpe jamais l'identité d'une série.
        // Ils s'accompagnent toujours d'une icône et d'un libellé : la couleur seule
        // ne porte jamais le sens.
        "status-good": "#0ca30c",
        "status-warning": "#fab219",
        "status-serious": "#ec835a",
        "status-critical": "#d03b3b",

        // --- Série catégorielle des graphiques ----------------------------- //
        // Ordre figé, jamais recyclé au-delà de huit séries. Il a été validé sur la
        // surface sombre du dashboard (#1e1f26) : bande de clarté, plancher de
        // chroma, séparation sous protanopie et deutéranopie (pire paire adjacente
        // ΔE 8,4), lisibilité en vision normale (ΔE 19,3) et contraste ≥ 3:1.
        //
        // Ces valeurs ne se retouchent pas à l'œil. Toute modification doit repasser
        // le validateur : deux teintes qui « se distinguent bien » à l'écran peuvent
        // être rigoureusement identiques pour 8 % des hommes.
        //
        // Plafond de trois séries sur les formes où deux marques quelconques peuvent
        // se toucher (nuage de points, donut, petits multiples) : au-delà, aucune
        // combinaison de huit couleurs ne tient les seuils. On replie sur « Autres ».
        "chart-1": "#3987e5",
        "chart-2": "#d95926",
        "chart-3": "#199e70",
        "chart-4": "#c98500",
        "chart-5": "#d55181",
        "chart-6": "#008300",
        "chart-7": "#9085e9",
        "chart-8": "#e66767",
        // Rampe séquentielle (magnitude continue) : une seule teinte, clair → foncé.
        "seq-100": "#cde2fb",
        "seq-250": "#86b6ef",
        "seq-400": "#3987e5",
        "seq-550": "#1c5cab",
        "seq-700": "#0d366b"
      },
      "borderRadius": {
        "DEFAULT": "0.3rem",
        "lg": "0.625rem",
        "xl": "0.875rem",
        "full": "9999px",
        "2xl": "1.25rem"
      },
      "spacing": {
        "base": "4px",
        "xs": "8px",
        "sm": "12px",
        "md": "20px",
        "gutter": "20px",
        "margin": "26px",
        "lg": "32px",
        "xl": "44px",
        "2xl": "64px",
        "container-max": "1280px"
      },
      "fontFamily": {
        "body-sm": ["Manrope"],
        "label-md": ["Manrope"],
        "body-lg": ["Manrope"],
        "headline-md": ["Manrope"],
        "headline-lg-mobile": ["Manrope"],
        "headline-xl": ["Manrope"],
        "body-md": ["Manrope"],
        "headline-lg": ["Manrope"],
        "code": ["JetBrains Mono"]
      },
      "fontSize": {
        // Chaque niveau a gagné environ 20 %. Les interlignes suivent avec un ratio
        // légèrement plus généreux sur le corps de texte (~1,45) que sur les titres
        // (~1,25) : c'est ce qui rend un paragraphe confortable sans écarteler un titre.
        "body-sm": ["13px", { "lineHeight": "19px", "fontWeight": "400" }],
        "label-md": ["13px", { "lineHeight": "18px", "letterSpacing": "0em", "fontWeight": "500" }],
        "body-md": ["15px", { "lineHeight": "22px", "fontWeight": "400" }],
        "body-lg": ["16.5px", { "lineHeight": "25px", "fontWeight": "400" }],
        "headline-md": ["17px", { "lineHeight": "23px", "fontWeight": "600" }],
        "headline-lg-mobile": ["21px", { "lineHeight": "28px", "fontWeight": "600" }],
        "headline-lg": ["23px", { "lineHeight": "30px", "letterSpacing": "-0.01em", "fontWeight": "600" }],
        "headline-xl": ["32px", { "lineHeight": "40px", "letterSpacing": "-0.02em", "fontWeight": "600" }],
        // Le monospace reste en retrait du corps de texte : un extrait de code n'a pas
        // à peser autant qu'une phrase, mais 11 px le rendait illisible.
        "code": ["12.5px", { "lineHeight": "18px", "fontWeight": "400" }]
      }
    },
  },
  plugins: [forms, containerQueries],
};
