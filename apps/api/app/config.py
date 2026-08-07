"""Configuration de la plateforme (lecture depuis l'environnement / .env).

Un seul objet `settings`, figé au démarrage. Deux règles suivies partout :

- **Aucun défaut dangereux.** Une valeur absente donne le comportement le plus
  restreint, jamais le plus permissif. `JWT_SECRET` vide ne génère pas un secret
  aléatoire « pour dépanner » : chaque redémarrage invaliderait les jetons émis, et
  le problème n'apparaîtrait qu'en production, sous forme de déconnexions inexpliquées.
- **Les incohérences sont signalées au démarrage**, par `validate()`. Une plateforme
  qui démarre avec `CORS_ORIGINS=*` et un domaine public en HTTPS est configurée pour
  échouer plus tard ; autant le dire tout de suite.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
#: Racine du monorepo — `packages/templates`, `packages/brand` y sont partagés
#: entre l'API et le front. Résolue depuis le fichier plutôt que via une variable
#: d'environnement : la structure du dépôt est un fait, pas un réglage.
REPO_ROOT = BASE_DIR.parent.parent

load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _list(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


def _gemini_keys() -> list[str]:
    """Clé(s) Gemini, dans l'ordre où le client doit les essayer."""
    primary = os.environ.get("GEMINI_API_KEY", "").strip()
    fallbacks = _list("GEMINI_API_KEY_FALLBACKS")
    keys = [primary] if primary else []
    for k in fallbacks:
        if k not in keys:
            keys.append(k)
    return keys


@dataclass(frozen=True)
class Settings:
    # ----------------------------------------------------------- Application -- #
    env: str = field(default_factory=lambda: os.environ.get("APP_ENV", "development"))
    app_host: str = field(default_factory=lambda: os.environ.get("APP_HOST", "0.0.0.0"))
    app_port: int = field(default_factory=lambda: _int("APP_PORT", 8000))
    data_dir: Path = field(default_factory=lambda: BASE_DIR / os.environ.get("DATA_DIR", "data"))
    sites_dir: Path = field(default_factory=lambda: BASE_DIR / os.environ.get("SITES_DIR", "sites"))
    public_base_url: str = field(default_factory=lambda: os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000"))
    #: Origine du tableau de bord, pour les liens envoyés par e-mail et les redirections OAuth.
    app_base_url: str = field(default_factory=lambda: os.environ.get("APP_BASE_URL", "http://localhost:5173"))
    # Origines autorisées pour le front. `*` en dev ; liste explicite en production.
    cors_origins: list[str] = field(default_factory=lambda: _list("CORS_ORIGINS", "*") or ["*"])
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO").upper())
    #: Journal en JSON une ligne par événement — indispensable dès qu'un agrégateur
    #: (Loki, CloudWatch) lit les logs. En développement, le texte reste plus lisible.
    log_json: bool = field(default_factory=lambda: _bool("LOG_JSON", False))

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"production", "prod"}

    # -------------------------------------------------------- Base de données -- #
    database_url: str = field(
        default_factory=lambda: os.environ.get("DATABASE_URL", "postgresql://localhost:5432/sites")
    )
    db_pool_size: int = field(default_factory=lambda: _int("DB_POOL_SIZE", 5))
    db_max_overflow: int = field(default_factory=lambda: _int("DB_MAX_OVERFLOW", 10))
    #: Les hébergeurs africains coupent volontiers les connexions inactives via NAT.
    #: Recycler avant leur seuil évite les « server closed the connection unexpectedly »
    #: au premier appel du matin.
    db_pool_recycle_s: int = field(default_factory=lambda: _int("DB_POOL_RECYCLE_S", 1800))

    # ------------------------------------------------------------ Régionalisation -- #
    #: Pays par défaut d'un compte sans indication : notre marché d'origine.
    default_country: str = field(default_factory=lambda: os.environ.get("DEFAULT_COUNTRY", "BJ").upper())
    default_currency: str = field(default_factory=lambda: os.environ.get("DEFAULT_CURRENCY", "XOF").upper())
    default_locale: str = field(default_factory=lambda: os.environ.get("DEFAULT_LOCALE", "fr"))
    default_timezone: str = field(default_factory=lambda: os.environ.get("DEFAULT_TIMEZONE", "Africa/Porto-Novo"))
    #: Pays ouverts à l'inscription. Vide = tous ceux du registre.
    enabled_countries: list[str] = field(default_factory=lambda: [c.upper() for c in _list("ENABLED_COUNTRIES")])

    # ------------------------------------------------------------------ Gemini -- #
    gemini_api_key: str = field(default_factory=lambda: os.environ.get("GEMINI_API_KEY", ""))
    # Bascule de clés : quand celle en tête épuise son quota (HTTP 429), le client passe
    # à la suivante plutôt que d'échouer la génération. GEMINI_API_KEY reste la clé
    # principale ; GEMINI_API_KEY_FALLBACKS ajoute les autres, séparées par des virgules.
    gemini_api_keys: list[str] = field(default_factory=_gemini_keys)
    gemini_coder_model: str = field(default_factory=lambda: os.environ.get("GEMINI_CODER_MODEL", "gemini-2.5-flash"))
    gemini_reviewer_model: str = field(default_factory=lambda: os.environ.get("GEMINI_REVIEWER_MODEL", "gemini-2.5-flash"))
    gemini_temperature: float = field(default_factory=lambda: _float("GEMINI_TEMPERATURE", 0.7))
    # Un site complet (html + css + js dans un seul objet JSON) dépasse largement le
    # plafond de sortie par défaut de l'API. Sans ce réglage, la réponse est coupée en
    # plein milieu et n'apparaît que sous la forme d'un JSON invalide.
    gemini_max_output_tokens: int = field(default_factory=lambda: _int("GEMINI_MAX_OUTPUT_TOKENS", 32768))
    gemini_timeout_s: float = field(default_factory=lambda: _float("GEMINI_TIMEOUT_S", 180))
    gemini_mock: bool = field(default_factory=lambda: _bool("GEMINI_MOCK", False))
    #: Coût du million de jetons, en FCFA, pour valoriser les appels dans le
    #: back-office. Deux valeurs distinctes : l'entrée est bien moins chère que la
    #: sortie, et un site généré produit beaucoup plus qu'il ne consomme.
    llm_cost_per_mtok_in_xof: float = field(default_factory=lambda: _float("LLM_COST_PER_MTOK_IN_XOF", 180.0))
    llm_cost_per_mtok_out_xof: float = field(default_factory=lambda: _float("LLM_COST_PER_MTOK_OUT_XOF", 1500.0))

    # ------------------------------------------------------------- Designer n8n -- #
    # Vide = designer interne uniquement. Le timeout est court devant celui de Gemini :
    # n8n est un maillon optionnel, la génération ne doit pas attendre longtemps un
    # service qui a de bonnes chances de ne pas répondre.
    n8n_designer_url: str = field(default_factory=lambda: os.environ.get("N8N_DESIGNER_URL", ""))
    n8n_timeout_s: float = field(default_factory=lambda: _float("N8N_TIMEOUT_S", 45))
    # Le chat est bien plus patient que la tentative de spec : l'utilisateur attend
    # devant sa réponse, alors qu'un repli de designer doit rester imperceptible. Le
    # tour final du workflow — celui qui tranche template et pages — met 4 à 5 minutes.
    # 10 minutes laissent donc une marge confortable. Attention : ce délai ne protège
    # que de notre côté ; si un intermédiaire (Cloudflare devant n8n) coupe avant, on
    # reçoit son erreur sans avoir attendu.
    n8n_chat_timeout_s: float = field(default_factory=lambda: _float("N8N_CHAT_TIMEOUT_S", 600))

    # -------------------------------------------------------- File de travaux -- #
    #: `inline` exécute le travail dans le processus web — pratique en développement,
    #: à proscrire en production : une génération de 90 secondes y monopolise un worker
    #: uvicorn, et un redémarrage la perd. `queue` confie le travail à `app.jobs.worker`.
    job_mode: str = field(default_factory=lambda: os.environ.get("JOB_MODE", "queue").lower())
    job_poll_interval_s: float = field(default_factory=lambda: _float("JOB_POLL_INTERVAL_S", 2.0))
    job_concurrency: int = field(default_factory=lambda: _int("JOB_CONCURRENCY", 2))
    #: Au-delà, un travail « en cours » est considéré comme orphelin (worker tué) et
    #: remis en file. Doit rester nettement supérieur à la plus longue génération.
    job_lock_timeout_s: int = field(default_factory=lambda: _int("JOB_LOCK_TIMEOUT_S", 900))
    job_max_attempts: int = field(default_factory=lambda: _int("JOB_MAX_ATTEMPTS", 3))
    job_retention_days: int = field(default_factory=lambda: _int("JOB_RETENTION_DAYS", 30))

    # ------------------------------------------------------------ Sécurité / Auth -- #
    jwt_secret: str = field(default_factory=lambda: os.environ.get("JWT_SECRET", ""))
    jwt_expire_minutes: int = field(default_factory=lambda: _int("JWT_EXPIRE_MINUTES", 120))
    internal_api_key: str = field(default_factory=lambda: os.environ.get("INTERNAL_API_KEY", ""))
    auth_max_attempts: int = field(default_factory=lambda: _int("AUTH_MAX_ATTEMPTS", 10))
    auth_window_minutes: int = field(default_factory=lambda: _int("AUTH_WINDOW_MINUTES", 15))
    #: Comptes promus administrateurs à la création. Sert à amorcer la plateforme :
    #: sans lui, personne ne peut ouvrir le back-office sur une base neuve.
    admin_emails: list[str] = field(default_factory=lambda: [e.lower() for e in _list("ADMIN_EMAILS")])
    #: Sel du condensat d'IP des événements. Le changer rend les anciens visiteurs
    #: non rapprochables des nouveaux — c'est voulu : ce n'est pas un identifiant.
    analytics_ip_salt: str = field(default_factory=lambda: os.environ.get("ANALYTICS_IP_SALT", "jarvis"))
    #: Requêtes par minute et par IP sur les endpoints publics (ingestion de visites).
    public_rate_limit_per_min: int = field(default_factory=lambda: _int("PUBLIC_RATE_LIMIT_PER_MIN", 120))

    # -------------------------------------------------------------- OAuth -------- #
    google_client_id: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_ID", ""))
    google_client_secret: str = field(default_factory=lambda: os.environ.get("GOOGLE_CLIENT_SECRET", ""))
    github_client_id: str = field(default_factory=lambda: os.environ.get("GITHUB_CLIENT_ID", ""))
    github_client_secret: str = field(default_factory=lambda: os.environ.get("GITHUB_CLIENT_SECRET", ""))

    @property
    def github_oauth_configured(self) -> bool:
        return bool(self.github_client_id and self.github_client_secret)

    @property
    def google_oauth_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    # --------------------------------------------------------------- Paiement --- #
    #: Agrégateur retenu pour encaisser les abonnements (cf. app.africa.payments).
    payment_provider: str = field(default_factory=lambda: os.environ.get("PAYMENT_PROVIDER", ""))
    payment_public_key: str = field(default_factory=lambda: os.environ.get("PAYMENT_PUBLIC_KEY", ""))
    payment_secret_key: str = field(default_factory=lambda: os.environ.get("PAYMENT_SECRET_KEY", ""))
    payment_webhook_secret: str = field(default_factory=lambda: os.environ.get("PAYMENT_WEBHOOK_SECRET", ""))
    payment_sandbox: bool = field(default_factory=lambda: _bool("PAYMENT_SANDBOX", True))

    @property
    def payments_configured(self) -> bool:
        return bool(self.payment_provider and self.payment_secret_key)

    # ------------------------------------------------------------------- VPS ---- #
    vps_host: str = field(default_factory=lambda: os.environ.get("VPS_HOST", ""))
    vps_port: int = field(default_factory=lambda: _int("VPS_PORT", 22))
    vps_user: str = field(default_factory=lambda: os.environ.get("VPS_USER", ""))
    vps_key_path: str = field(default_factory=lambda: os.environ.get("VPS_KEY_PATH", ""))
    vps_base_dir: str = field(default_factory=lambda: os.environ.get("VPS_BASE_DIR", "/var/www/sites"))
    vps_use_subdomain: bool = field(default_factory=lambda: _bool("VPS_USE_SUBDOMAIN", False))
    vps_domain: str = field(default_factory=lambda: os.environ.get("VPS_DOMAIN", ""))

    @property
    def vps_configured(self) -> bool:
        return bool(self.vps_host and self.vps_user)

    # ------------------------------------------------------------- Ressources --- #
    @property
    def templates_dir(self) -> Path:
        """Catalogue de templates, partagé avec le front depuis `packages/`.

        Un repli sur l'ancien emplacement interne est conservé : l'image Docker de
        l'API peut être construite sans le reste du monorepo, et le catalogue y est
        alors copié à côté du code.
        """
        shared = REPO_ROOT / "packages" / "templates" / "catalog"
        return shared if shared.is_dir() else BASE_DIR / "app" / "templates"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sites_dir.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------------- Contrôles -- #
    def validate(self) -> list[str]:
        """Anomalies de configuration, de la plus grave à la plus anodine.

        Retourne des messages plutôt que de lever : le démarrage doit rester possible
        en développement avec une configuration incomplète, tandis que `main.py`
        refuse de démarrer en production si l'un de ces points touche à la sécurité.
        """
        problems: list[str] = []

        if not self.jwt_secret:
            problems.append("CRITIQUE : JWT_SECRET est vide — aucune authentification ne fonctionnera.")
        elif len(self.jwt_secret) < 32:
            problems.append("CRITIQUE : JWT_SECRET fait moins de 32 caractères (générez : openssl rand -hex 32).")

        if self.is_production:
            if "*" in self.cors_origins:
                problems.append("CRITIQUE : CORS_ORIGINS=* en production — listez les origines réelles.")
            if not self.internal_api_key:
                problems.append("CRITIQUE : INTERNAL_API_KEY vide — les endpoints /api/agents sont ouverts à n8n sans clé.")
            if self.public_base_url.startswith("http://"):
                problems.append("CRITIQUE : PUBLIC_BASE_URL en HTTP — les sites publiés seront servis sans TLS.")
            if self.gemini_mock:
                problems.append("CRITIQUE : GEMINI_MOCK=true en production — les sites générés seront factices.")
            if self.job_mode == "inline":
                problems.append(
                    "JOB_MODE=inline en production : chaque génération monopolisera un worker web "
                    "et sera perdue au redémarrage. Lancez `python -m app.jobs.worker` et passez en `queue`."
                )
            if not self.admin_emails:
                problems.append("ADMIN_EMAILS est vide : personne ne pourra ouvrir le back-office sur une base neuve.")

        if self.public_base_url.startswith(("http://localhost", "http://127.0.0.1")):
            problems.append(
                f"PUBLIC_BASE_URL vaut {self.public_base_url} : les URLs de sites renvoyées aux "
                "clients pointeront vers cette machine."
            )
        if self.vps_configured:
            problems.append(
                f"VPS_HOST/VPS_USER renseignés : les sites partiront par SFTP vers {self.vps_host} "
                "au lieu d'être servis depuis ce serveur."
            )
        if not self.gemini_api_keys and not self.gemini_mock:
            problems.append("Aucune clé Gemini : toute génération répondra 502.")

        return problems


settings = Settings()
