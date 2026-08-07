"""DesignSpec figés pour l'évaluation du seul agent codeur.

En production le spec vient du designer n8n de Caleb. Le figer ici **isole le codeur** :
deux runs partent exactement de la même entrée, donc leurs écarts viennent du codeur et
non d'un designer qui aurait changé d'avis. C'est ce qui rend le comparatif avant/après
interprétable.

Trois specs laissent `contact` vide (piège anti-hallucination : le site ne doit inventer
ni téléphone ni email) et deux le renseignent (le site doit alors les utiliser).
"""
from __future__ import annotations

from typing import Any

RESTAURANT: dict[str, Any] = {
    "name": "Chez Amara",
    "tagline": "Cuisine ouest-africaine, recettes de famille",
    "business_type": "restaurant",
    "description": "Restaurant familial installé à Lyon depuis 2015. Tout est préparé sur place, du mafé au poulet yassa.",
    "tone": "chaleureux",
    "audience": "familles et groupes d'amis du quartier",
    "style": "moderne",
    "language": "fr",
    "palette": {"primary": "#b23a17", "secondary": "#f7ede2", "accent": "#e8a33d", "bg": "#fffaf5", "text": "#2b1a12"},
    "typography": {"heading_font": "Georgia, serif", "body_font": "system-ui, sans-serif", "base_size": "17px"},
    "sections": [
        {"id": "hero", "title": "Accueil", "content": "Chez Amara, la cuisine d'Afrique de l'Ouest comme à la maison.", "order": 0},
        {"id": "apropos", "title": "À propos", "content": "Amara cuisine depuis vingt ans les plats de son enfance à Bamako.", "order": 1},
        {"id": "carte", "title": "La carte", "content": "Mafé, poulet yassa, thieboudienne, jus de bissap maison.", "order": 2},
        {"id": "contact", "title": "Nous trouver", "content": "Au cœur de la Guillotière, à cinq minutes du métro.", "order": 3},
    ],
    "contact": {"phone": "04 78 12 34 56", "email": "bonjour@chez-amara.fr", "address": "12 rue Pasteur, 69007 Lyon", "hours": "Mardi au dimanche, 12h-14h30 et 19h-22h30"},
    "cta": "Réserver une table",
}

AVOCAT: dict[str, Any] = {
    "name": "Cabinet Falcon",
    "tagline": "Droit des affaires et contentieux commercial",
    "business_type": "cabinet",
    "description": "Cabinet d'avocats lyonnais accompagnant dirigeants et PME sur leurs opérations et leurs litiges.",
    "tone": "premium",
    "audience": "dirigeants de PME et directions juridiques",
    "style": "premium",
    "language": "fr",
    "palette": {"primary": "#1b2a41", "secondary": "#e8e6e1", "accent": "#a68a5b", "bg": "#ffffff", "text": "#14181f"},
    "typography": {"heading_font": "Georgia, serif", "body_font": "Georgia, serif", "base_size": "16px"},
    "sections": [
        {"id": "hero", "title": "Accueil", "content": "Un accompagnement juridique exigeant, de la négociation au contentieux.", "order": 0},
        {"id": "apropos", "title": "Le cabinet", "content": "Fondé en 2008, le cabinet réunit quatre avocats associés.", "order": 1},
        {"id": "expertises", "title": "Expertises", "content": "Fusions-acquisitions, contrats commerciaux, contentieux, droit des sociétés.", "order": 2},
        {"id": "equipe", "title": "L'équipe", "content": "Quatre associés et deux collaborateurs, tous inscrits au barreau de Lyon.", "order": 3},
        {"id": "contact", "title": "Contact", "content": "Premier rendez-vous d'évaluation sans engagement.", "order": 4},
    ],
    "contact": {"phone": "", "email": "", "address": "", "hours": ""},
    "cta": "Demander un rendez-vous",
}

FREELANCE: dict[str, Any] = {
    "name": "Nadia Berrada",
    "tagline": "Développeuse web indépendante",
    "business_type": "freelance",
    "description": "Conception et développement d'applications web sur mesure pour startups et PME.",
    "tone": "sobre",
    "audience": "startups et responsables produit",
    "style": "minimal",
    "language": "fr",
    "palette": {"primary": "#0f766e", "secondary": "#f1f5f9", "accent": "#f97316", "bg": "#fdfdfc", "text": "#111827"},
    "typography": {"heading_font": "system-ui, sans-serif", "body_font": "system-ui, sans-serif", "base_size": "16px"},
    "sections": [
        {"id": "hero", "title": "Accueil", "content": "Je conçois et développe des applications web qui tiennent la charge.", "order": 0},
        {"id": "services", "title": "Services", "content": "Développement full-stack, reprise de code existant, audit technique.", "order": 1},
        {"id": "portfolio", "title": "Réalisations", "content": "Une plateforme logistique, un back-office SaaS, deux sites e-commerce.", "order": 2},
        {"id": "contact", "title": "Travaillons ensemble", "content": "Disponible pour des missions de trois mois ou plus.", "order": 3},
    ],
    "contact": {"phone": "", "email": "", "address": "", "hours": ""},
    "cta": "Me contacter",
}

ASSOCIATION: dict[str, Any] = {
    "name": "Les Jardins de Vaise",
    "tagline": "Jardin partagé et ateliers de quartier",
    "business_type": "association",
    "description": "Association de quartier animant un jardin partagé et des ateliers de jardinage ouverts à tous.",
    "tone": "chaleureux",
    "audience": "habitants du quartier, familles, écoles",
    "style": "playful",
    "language": "fr",
    "palette": {"primary": "#3f7d20", "secondary": "#fdf6e3", "accent": "#e4572e", "bg": "#fffdf7", "text": "#1f2d16"},
    "typography": {"heading_font": "Georgia, serif", "body_font": "system-ui, sans-serif", "base_size": "17px"},
    "sections": [
        {"id": "hero", "title": "Accueil", "content": "Un jardin partagé au cœur de Vaise, ouvert à tous les habitants.", "order": 0},
        {"id": "apropos", "title": "L'association", "content": "Créée en 2019 par des habitants, l'association compte aujourd'hui 120 adhérents.", "order": 1},
        {"id": "ateliers", "title": "Nos ateliers", "content": "Compostage, semis de printemps, taille des arbres fruitiers, cuisine des récoltes.", "order": 2},
        {"id": "adherer", "title": "Nous rejoindre", "content": "L'adhésion annuelle donne accès à une parcelle et à tous les ateliers.", "order": 3},
    ],
    "contact": {"phone": "", "email": "contact@jardins-de-vaise.org", "address": "", "hours": "Permanence le samedi matin"},
    "cta": "Adhérer",
}

BOUTIQUE: dict[str, Any] = {
    "name": "Papeterie Lune",
    "tagline": "Papiers, carnets et objets d'écriture",
    "business_type": "boutique",
    "description": "Papeterie indépendante proposant carnets reliés main, encres et stylos plume.",
    "tone": "premium",
    "audience": "amateurs de papeterie et de calligraphie",
    "style": "editorial",
    "language": "fr",
    "palette": {"primary": "#2f3e46", "secondary": "#f4f1ea", "accent": "#9b6a6c", "bg": "#fbfaf7", "text": "#1c2529"},
    "typography": {"heading_font": "Georgia, serif", "body_font": "Georgia, serif", "base_size": "16px"},
    "sections": [
        {"id": "hero", "title": "Accueil", "content": "Des papiers choisis un par un, pour ceux qui écrivent encore à la main.", "order": 0},
        {"id": "apropos", "title": "La boutique", "content": "Une sélection resserrée de papeteries japonaises, italiennes et françaises.", "order": 1},
        {"id": "collections", "title": "Collections", "content": "Carnets reliés main, encres d'artisan, plumes anciennes restaurées.", "order": 2},
        {"id": "contact", "title": "Nous rendre visite", "content": "La boutique se visite sans rendez-vous, du mardi au samedi.", "order": 3},
    ],
    "contact": {"phone": "", "email": "", "address": "", "hours": ""},
    "cta": "Découvrir la sélection",
}

SPECS: dict[str, dict[str, Any]] = {
    "restaurant": RESTAURANT,
    "avocat": AVOCAT,
    "freelance": FREELANCE,
    "association": ASSOCIATION,
    "boutique": BOUTIQUE,
}
