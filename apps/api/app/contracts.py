"""Schémas partagés (Pydantic V2) — contrat entre le backend, n8n et le front.

Ce module est LA référence : Caleb (n8n) consomme ces formats via /docs, et le
front-end s'appuie dessus pour afficher les sessions.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
class RegisterRequest(BaseModel):
    """Inscription.

    Le pays est demandé dès l'inscription — pas plus tard — parce qu'il conditionne
    tout ce que l'utilisateur voit ensuite : devise des tarifs, indicatif proposé,
    moyens de paiement, langue par défaut. Le réclamer après coup obligerait à
    afficher une grille tarifaire dans une devise étrangère au premier écran.
    """

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    name: str | None = Field(default=None, max_length=120)
    country: str = Field(default="BJ", min_length=2, max_length=2)
    phone: str | None = Field(default=None, max_length=24)
    company: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def _normalize(self) -> "RegisterRequest":
        self.email = self.email.strip().lower()
        self.country = self.country.strip().upper()
        return self


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def _email_lower(self) -> "LoginRequest":
        self.email = self.email.strip().lower()
        return self


class GoogleAuthRequest(BaseModel):
    id_token: str = Field(min_length=10)


class GitHubAuthRequest(BaseModel):
    code: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserPublic"


class UserPublic(BaseModel):
    """Profil renvoyé au front après authentification.

    `role` y figure pour que l'interface sache s'il faut afficher l'entrée
    « Administration » — c'est un confort d'affichage, pas un contrôle : chaque
    endpoint du back-office revérifie le rôle côté serveur.
    """

    id: int
    email: str
    name: str | None = None
    provider: str
    role: str = "user"
    plan: str = "decouverte"
    country: str = "BJ"
    locale: str = "fr"
    company: str | None = None
    phone: str | None = None
    city: str | None = None
    created_at: str | None = None

    @classmethod
    def from_row(cls, user: dict) -> "UserPublic":
        return cls(
            id=user["id"],
            email=user["email"],
            name=user.get("name"),
            provider=user.get("provider") or "local",
            role=user.get("role") or "user",
            plan=user.get("plan") or "decouverte",
            country=user.get("country") or "BJ",
            locale=user.get("locale") or "fr",
            company=user.get("company"),
            phone=user.get("phone"),
            city=user.get("city"),
            created_at=user.get("created_at"),
        )


class UpdateProfileRequest(BaseModel):
    """Champs qu'un utilisateur peut modifier sur son propre compte.

    Ni `role` ni `plan` n'y figurent : un compte ne se promeut pas lui-même et ne
    change pas d'offre sans passer par le paiement.
    """

    name: str | None = Field(default=None, max_length=120)
    company: str | None = Field(default=None, max_length=160)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    city: str | None = Field(default=None, max_length=80)
    phone: str | None = Field(default=None, max_length=24)
    whatsapp: str | None = Field(default=None, max_length=24)
    locale: str | None = Field(default=None, max_length=5)


# --------------------------------------------------------------------------- #
# Design (sortie du designer n8n de Caleb → entrée de l'agent codeur)
# --------------------------------------------------------------------------- #
class DesignPalette(BaseModel):
    primary: str = "#2a5c8a"
    secondary: str = "#f5f5f0"
    accent: str = "#c96f32"
    bg: str = "#ffffff"
    text: str = "#1a1a1a"


class DesignTypography(BaseModel):
    heading_font: str = "Georgia, serif"
    body_font: str = "system-ui, sans-serif"
    base_size: str = "16px"


class DesignSection(BaseModel):
    id: str
    title: str
    content: str = ""
    order: int = 0


class DesignContact(BaseModel):
    """Coordonnées réelles du commerce. Rien ici ne doit être inventé par un modèle.

    `whatsapp` est un champ à part entière et non une variante du téléphone : sur nos
    marchés c'est le premier canal de contact, souvent avant l'appel et très loin
    devant l'e-mail. Un site vitrine africain sans bouton WhatsApp perd la majorité
    de ses prises de contact.
    """

    phone: str = ""
    whatsapp: str = ""
    email: str = ""
    address: str = ""
    #: Point de repère — l'adressage formel est minoritaire en Afrique de l'Ouest.
    #: « En face de la pharmacie Sainte-Rita » localise mieux qu'un numéro de rue.
    landmark: str = ""
    city: str = ""
    hours: str = ""
    maps_url: str = ""
    facebook: str = ""
    instagram: str = ""
    tiktok: str = ""


class DesignCommerce(BaseModel):
    """Ce qui touche à l'argent sur le site généré.

    Séparé du contact parce que ces informations conditionnent la structure des pages :
    un site qui accepte le mobile money affiche des badges de paiement et des prix,
    un site de service affiche un formulaire de devis.
    """

    currency: str = "XOF"
    #: Opérateurs affichés sur les badges de paiement, dans l'ordre d'usage local.
    mobile_money: list[str] = Field(default_factory=list)
    accepts_cash: bool = True
    accepts_card: bool = False
    delivery: bool = False
    delivery_zones: list[str] = Field(default_factory=list)
    price_range: str = ""


class DesignSpec(BaseModel):
    """Spécification complète d'un site à générer.

    Les champs régionaux (`country`, `commerce`) ne sont pas décoratifs : ils
    déterminent le format des prix, la présence d'un bouton WhatsApp, le groupage des
    numéros de téléphone, les jours d'ouverture affichés et les moyens de paiement
    listés. Ce sont eux qui font la différence entre un site « traduit en français »
    et un site qui parle à un client de Cotonou ou de Kumasi.
    """

    name: str
    tagline: str = ""
    business_type: str = "autre"
    description: str = ""
    tone: str = "moderne"
    audience: str = ""
    style: Literal["minimal", "moderne", "premium", "playful", "editorial"] = "moderne"
    language: str = "fr"

    # --- Ancrage régional ---------------------------------------------------- #
    country: str = "BJ"
    #: Langues secondaires du site. Deux au maximum : au-delà, le coût de génération
    #: double sans que le trafic suive.
    secondary_languages: list[str] = Field(default_factory=list)

    palette: DesignPalette = Field(default_factory=DesignPalette)
    typography: DesignTypography = Field(default_factory=DesignTypography)
    sections: list[DesignSection] = Field(default_factory=list)
    contact: DesignContact = Field(default_factory=DesignContact)
    commerce: DesignCommerce = Field(default_factory=DesignCommerce)
    cta: str = "Nous contacter"

    @model_validator(mode="after")
    def _apply_country_defaults(self) -> "DesignSpec":
        """Complète le contexte régional laissé vide par le designer.

        Le designer — modèle génératif ou workflow n8n — renseigne rarement la devise
        ou les opérateurs de paiement. Les déduire du pays ici, au lieu de le demander
        dans le prompt, garantit que l'information est **toujours** juste : un modèle
        à qui l'on demande les opérateurs mobile money du Togo répond régulièrement
        « Orange Money », qui n'y opère pas.
        """
        from app.africa import countries as _countries

        code = (self.country or "BJ").strip().upper()[:2]
        country = _countries.find(code) or _countries.get("BJ")
        self.country = country.code

        if not self.commerce.currency or self.commerce.currency == "XOF":
            self.commerce.currency = country.currency
        if not self.commerce.mobile_money:
            self.commerce.mobile_money = list(country.mobile_money)
        if not self.contact.city:
            self.contact.city = country.major_cities[0] if country.major_cities else ""
        return self


# --------------------------------------------------------------------------- #
# Agent codeur (sortie Gemini → fichiers sur disque)
# --------------------------------------------------------------------------- #
class GeneratedSite(BaseModel):
    html: str
    css: str
    js: str = ""


# --------------------------------------------------------------------------- #
# Agent review (sortie Gemini + findings SAST)
# --------------------------------------------------------------------------- #
FindingSeverity = Literal["critical", "high", "medium", "low", "info"]
FindingCategory = Literal["security", "quality", "accessibility", "responsive"]


class ReviewFinding(BaseModel):
    severity: FindingSeverity
    category: FindingCategory
    title: str
    detail: str = ""
    fix: str = ""
    file: str = ""
    # Champs additifs (défauts fournis) : n8n et le front les ignorent sans casser.
    rule: str = ""          # identifiant stable du check, ex. "js.eval" (vide côté LLM)
    line: int | None = None  # ligne concernée, quand le check sait la situer
    source: Literal["sast", "llm"] = "llm"  # qui a produit le finding


class ReviewDimensions(BaseModel):
    security: int = Field(default=0, ge=0, le=100)
    design_fidelity: int = Field(default=0, ge=0, le=100)
    accessibility: int = Field(default=0, ge=0, le=100)
    responsiveness: int = Field(default=0, ge=0, le=100)
    content: int = Field(default=0, ge=0, le=100)


class ReviewReport(BaseModel):
    score: int = Field(default=0, ge=0, le=100)
    verdict: Literal["pass", "warn", "fail"] = "warn"
    dimensions: ReviewDimensions = Field(default_factory=ReviewDimensions)
    findings: list[ReviewFinding] = Field(default_factory=list)
    summary: str = ""
    # Additifs : permettent de distinguer ce qui vient des checks déterministes de ce
    # qui vient du LLM, et de signaler une revue partielle (LLM indisponible).
    sast_findings_count: int = 0
    llm_findings_count: int = 0
    llm_available: bool = True


# --------------------------------------------------------------------------- #
# Sessions & artefacts
# --------------------------------------------------------------------------- #
class CreateSessionRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)
    #: Pays visé par le site. Absent, on prend celui du compte : un commerçant génère
    #: presque toujours pour son propre marché.
    country: str | None = Field(default=None, min_length=2, max_length=2)


class GenerateRequest(BaseModel):
    """Lancement de la génération complète depuis le front.

    `design_spec` est celui que l'agent conversationnel a fini par produire. Le fournir
    court-circuite l'étape de design : c'est la conversation de cadrage qui fait foi, et
    la relancer produirait un site différent de celui qui vient d'être validé avec
    l'utilisateur.
    """

    prompt: str = Field(min_length=3, max_length=8000)
    design_spec: DesignSpec | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)


# --------------------------------------------------------------------------- #
# Chat de cadrage (agent conversationnel n8n)
# --------------------------------------------------------------------------- #
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    # Fil de conversation côté n8n. Absent au premier message, le backend en ouvre un.
    conversation_id: str | None = Field(default=None, max_length=64)


class ChatResponse(BaseModel):
    """Réponse de l'agent de cadrage.

    `design_spec` n'apparaît qu'une fois le besoin cerné : tant qu'il est nul, l'agent
    pose encore des questions et il n'y a rien à générer.
    """

    conversation_id: str
    reply: str
    design_spec: DesignSpec | None = None
    available: bool = True

    @property
    def ready(self) -> bool:
        return self.design_spec is not None


class EditSessionRequest(BaseModel):
    """Modification d'un site existant.

    Deux intentions bien distinctes, car elles n'ont pas le même point de départ :

    - `tweak` (défaut) : on garde le design actuel et on retouche. Le site existant est
      transmis au codeur pour qu'il le conserve.
    - `redesign` : on repart d'un design neuf. Le site actuel n'est **pas** transmis,
      sinon le modèle le recopie ; et le spec de référence devient le nouveau, sans quoi
      l'instruction (« passe en sombre ») contredirait la palette exigée par l'ancien.

    `design_spec` fourni implique une refonte. S'il est absent en mode `redesign`, le
    backend régénère un spec depuis l'instruction.
    """

    instruction: str = Field(min_length=2, max_length=2000)
    mode: Literal["tweak", "redesign"] = "tweak"
    design_spec: DesignSpec | None = None


class SessionStep(BaseModel):
    step: str
    status: str
    detail: str = ""
    ts: str


class VersionPreview(BaseModel):
    """Une version générée et son URL de prévisualisation.

    Permet au front de proposer « prévisualiser » avant « publier » : chaque version
    reste servie à son URL propre, indépendamment de celle qui est en ligne.
    """

    version: int
    url: str
    score: int | None = None
    verdict: str | None = None
    published: bool = False


class PublishRequest(BaseModel):
    version: int | None = None  # None = la dernière version générée
    force: bool = False  # publier malgré un verdict `fail`


class SessionView(BaseModel):
    id: str
    slug: str
    prompt: str
    status: str
    current_step: str | None = None
    steps: list[SessionStep] = Field(default_factory=list)
    versions: list[str] = Field(default_factory=list)
    site_url: str | None = None
    # Additifs : le front peut afficher un cycle prévisualiser → publier, et savoir
    # laquelle des versions est actuellement en ligne.
    published_version: int | None = None
    previews: list[VersionPreview] = Field(default_factory=list)
    report: ReviewReport | None = None
    error: str | None = None
    country: str = "BJ"
    business_type: str | None = None
    #: Nombre de sites servis avant celui-ci. `None` quand rien n'attend. Sert à
    #: remplacer une animation d'attente muette par une information vérifiable.
    queue_position: int | None = None
    created_at: str
    updated_at: str


# --------------------------------------------------------------------------- #
# Endpoints agents (appelés par n8n)
# --------------------------------------------------------------------------- #
class AgentCodeRequest(BaseModel):
    session_id: str
    design_spec: DesignSpec
    instruction: str | None = Field(default=None, max_length=2000)  # édition IA


class AgentReviewRequest(BaseModel):
    session_id: str
    slug: str


class AgentCodeResponse(BaseModel):
    slug: str
    version: int
    files: dict[str, str]


class AgentReviewResponse(BaseModel):
    slug: str
    report: ReviewReport


class DeployRequest(BaseModel):
    session_id: str
    slug: str


class DeployResponse(BaseModel):
    slug: str
    version: int
    target: Literal["local", "vps"]
    url: str


class SessionCreated(BaseModel):
    id: str
    slug: str
    status: str = "pending"


class PublicSite(BaseModel):
    slug: str
    version: int
    url: str


class ArtifactRecord(BaseModel):
    kind: str
    version: int
    payload: Any = None
    created_at: str


# --------------------------------------------------------------------------- #
# Compte et consommation
# --------------------------------------------------------------------------- #
class QuotaUsage(BaseModel):
    """Consommation d'une ressource face à la limite du forfait.

    `-1` en limite signifie « sans plafond » ; le front affiche alors « illimité »
    plutôt qu'une jauge, qu'il serait absurde de dessiner.
    """

    resource: str
    label: str
    used: int
    limit: int
    percent: float = 0.0


class AccountOverview(BaseModel):
    """Ce que voit un client sur sa page « Mon compte »."""

    user: UserPublic
    plan: str
    plan_name: str
    period: str
    quotas: dict[str, Any] = Field(default_factory=dict)
    usage: list[QuotaUsage] = Field(default_factory=list)
    sites_count: int = 0
    published_count: int = 0
    renews_on: str | None = None
    country_profile: dict[str, Any] = Field(default_factory=dict)


class PlanOffer(BaseModel):
    """Une offre telle que la page de tarification l'affiche, prix localisé compris."""

    key: str
    name: str
    tagline: str
    audience: str = ""
    popular: bool = False
    highlights: list[str] = Field(default_factory=list)
    monthly: dict[str, Any] = Field(default_factory=dict)
    yearly: dict[str, Any] = Field(default_factory=dict)
    quotas: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Back-office
# --------------------------------------------------------------------------- #
class AdminUserRow(BaseModel):
    """Ligne de la liste des comptes du back-office."""

    id: int
    email: str
    name: str | None = None
    role: str
    plan: str
    status: str
    provider: str
    country: str
    country_name: str = ""
    flag: str = ""
    company: str | None = None
    phone: str | None = None
    sites: int = 0
    published: int = 0
    created_at: str
    last_seen_at: str | None = None


class AdminUserUpdate(BaseModel):
    """Modifications applicables à un compte depuis le back-office.

    Chaque champ est optionnel : la requête ne porte que ce qui change, et l'audit
    n'enregistre que la différence réelle. Un `PATCH` qui renverrait tout l'objet
    rendrait le journal illisible et masquerait ce qui a vraiment bougé.
    """

    role: Literal["user", "support", "admin", "owner"] | None = None
    plan: str | None = None
    plan_period: Literal["monthly", "yearly"] | None = None
    status: Literal["active", "suspended"] | None = None
    country: str | None = Field(default=None, min_length=2, max_length=2)
    name: str | None = Field(default=None, max_length=120)
    company: str | None = Field(default=None, max_length=160)
    note: str | None = Field(default=None, max_length=500)


class AdminSiteRow(BaseModel):
    """Ligne de la liste des sites du back-office."""

    id: str
    slug: str
    user_id: int
    user_email: str | None = None
    status: str
    country: str
    flag: str = ""
    business_type: str | None = None
    versions: int = 0
    score: int | None = None
    verdict: str | None = None
    site_url: str | None = None
    views: int = 0
    created_at: str
    published_at: str | None = None


class AdminJobRow(BaseModel):
    id: str
    kind: str
    status: str
    priority: int
    attempts: int
    max_attempts: int
    session_id: str | None = None
    user_id: int | None = None
    error: str | None = None
    duration_ms: int | None = None
    created_at: str
    finished_at: str | None = None


class AuditEntry(BaseModel):
    id: int
    ts: str
    actor_id: int | None = None
    actor_email: str | None = None
    action: str
    target_type: str | None = None
    target_id: str | None = None
    changes: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None


class FeatureFlagRow(BaseModel):
    key: str
    enabled: bool
    rollout_percent: int = 100
    description: str | None = None
    updated_at: str | None = None
    updated_by: str | None = None


class FeatureFlagUpdate(BaseModel):
    enabled: bool
    rollout_percent: int = Field(default=100, ge=0, le=100)
    description: str | None = Field(default=None, max_length=300)


class SystemHealth(BaseModel):
    """État d'exploitation affiché sur l'écran « Système » du back-office."""

    status: Literal["ok", "degraded", "down"] = "ok"
    database: bool = True
    queue: dict[str, Any] = Field(default_factory=dict)
    llm_configured: bool = False
    payments_configured: bool = False
    vps_configured: bool = False
    job_mode: str = "queue"
    environment: str = "development"
    version: str = ""
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Ingestion publique (sites générés)
# --------------------------------------------------------------------------- #
class VisitBeacon(BaseModel):
    """Signal émis par un site publié vers l'API.

    Volontairement minimal : ni identifiant de visiteur, ni URL complète, ni
    empreinte de navigateur. On veut savoir qu'un site est consulté et qu'on y clique
    pour appeler — pas qui l'a consulté. Ce qu'on ne collecte pas ne fuite pas.
    """

    slug: str = Field(min_length=1, max_length=120)
    event: Literal["view", "whatsapp", "call"] = "view"
    #: Nouveau visiteur du jour, décidé par le site lui-même (marqueur local).
    unique: bool = False
