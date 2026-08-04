/**
 * Thème Material 3 du dashboard Jarvis.
 *
 * Ce fichier remplace les blocs `<script id="tailwind-config">` qui étaient inline
 * dans chaque page à l'époque du CDN. Les huit pages en portaient cinq variantes,
 * fusionnées ici sans aucun conflit de valeur : les écarts n'étaient que des clés
 * présentes sur certaines pages seulement (`2xl`, `container-max`, la police `code`).
 * Une clé inutilisée sur une page ne coûte rien — le purge de Tailwind ne génère
 * que les utilitaires réellement présents dans le markup.
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
        "tertiary-fixed-dim": "#bcc7de"
      },
      "borderRadius": {
        "DEFAULT": "0.25rem",
        "lg": "0.5rem",
        "xl": "0.75rem",
        "full": "9999px",
        "2xl": "1rem"
      },
      "spacing": {
        "sm": "10px",
        "lg": "24px",
        "base": "4px",
        "xl": "32px",
        "xs": "6px",
        "gutter": "16px",
        "margin": "20px",
        "md": "16px",
        "container-max": "1200px"
      },
      "fontFamily": {
        "body-sm": [
          "Manrope"
        ],
        "label-md": [
          "Manrope"
        ],
        "body-lg": [
          "Manrope"
        ],
        "headline-md": [
          "Manrope"
        ],
        "headline-lg-mobile": [
          "Manrope"
        ],
        "headline-xl": [
          "Manrope"
        ],
        "body-md": [
          "Manrope"
        ],
        "headline-lg": [
          "Manrope"
        ],
        "code": [
          "JetBrains Mono"
        ]
      },
      "fontSize": {
        "body-sm": [
          "12px",
          {
            "lineHeight": "17px",
            "fontWeight": "400"
          }
        ],
        "label-md": [
          "12px",
          {
            "lineHeight": "16px",
            "letterSpacing": "0em",
            "fontWeight": "500"
          }
        ],
        "body-lg": [
          "14.5px",
          {
            "lineHeight": "21px",
            "fontWeight": "400"
          }
        ],
        "headline-md": [
          "15px",
          {
            "lineHeight": "20px",
            "fontWeight": "600"
          }
        ],
        "headline-lg-mobile": [
          "18px",
          {
            "lineHeight": "24px",
            "fontWeight": "600"
          }
        ],
        "headline-xl": [
          "26px",
          {
            "lineHeight": "32px",
            "letterSpacing": "-0.02em",
            "fontWeight": "600"
          }
        ],
        "body-md": [
          "13px",
          {
            "lineHeight": "19px",
            "fontWeight": "400"
          }
        ],
        "headline-lg": [
          "20px",
          {
            "lineHeight": "26px",
            "letterSpacing": "-0.01em",
            "fontWeight": "600"
          }
        ],
        "code": [
          "11px",
          {
            "lineHeight": "15px",
            "fontWeight": "400"
          }
        ]
      }
    },
  },
  plugins: [forms, containerQueries],
};
