"""Collecte : événements produit, journal d'audit, coût des modèles, visites de sites.

Principe directeur : **la collecte ne doit jamais casser le produit.** Un graphique
manquant est un désagrément ; une génération de site qui échoue parce que l'écriture
d'un événement a échoué est une faute. Toutes les fonctions d'écriture de ce module
absorbent donc leurs exceptions et se contentent de les journaliser.

Le journal d'audit fait exception : une action d'administration dont la trace n'a pas
pu être écrite doit échouer. On ne suspend pas le compte d'un client sans laisser de
trace de qui l'a fait.

Sur la vie privée : aucune adresse IP n'est stockée en clair. Seul un condensat salé
et tronqué l'est, pour distinguer deux visiteurs sur une même journée — il ne permet
pas de remonter à une personne, et la rotation du sel le rend inexploitable au-delà.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from app import db
from app.config import settings

logger = logging.getLogger("app.analytics")

# Vocabulaire d'événements. Fermé volontairement : une chaîne libre à l'appel produit
# en six mois quinze variantes de « site_created » qu'aucune requête ne rapproche.
SIGNUP = "user.signup"
LOGIN = "user.login"
SITE_CREATED = "site.created"
SITE_GENERATED = "site.generated"
SITE_EDITED = "site.edited"
SITE_PUBLISHED = "site.published"
JOB_FAILED = "job.failed"
PLAN_CHANGED = "billing.plan_changed"
QUOTA_HIT = "billing.quota_hit"
CHAT_MESSAGE = "chat.message"

KNOWN_EVENTS = frozenset(
    {SIGNUP, LOGIN, SITE_CREATED, SITE_GENERATED, SITE_EDITED, SITE_PUBLISHED,
     JOB_FAILED, PLAN_CHANGED, QUOTA_HIT, CHAT_MESSAGE}
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_ip(ip: str | None) -> str | None:
    """Condensat court et salé d'une adresse IP.

    Seize caractères hexadécimaux suffisent à séparer des visiteurs sur une journée
    et rendent toute table arc-en-ciel inutile en pratique — pour un espace d'entrée
    aussi petit que celui des adresses IPv4, c'est le sel qui fait le travail, pas la
    longueur.
    """
    if not ip:
        return None
    digest = hashlib.sha256(f"{settings.analytics_ip_salt}:{ip}".encode()).hexdigest()
    return digest[:16]


def track(
    name: str,
    *,
    user_id: int | None = None,
    session_id: str | None = None,
    country: str | None = None,
    props: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Enregistre un événement produit. N'échoue jamais.

    Args:
        name: une des constantes du module. Un nom hors vocabulaire est accepté mais
            signalé : mieux vaut un événement inattendu dans la base qu'un appelant
            qui plante en production pour une faute de frappe.
    """
    if name not in KNOWN_EVENTS:
        logger.warning("Événement hors vocabulaire : %s", name)

    try:
        with db.session_scope() as s:
            s.add(
                db.Event(
                    ts=_utcnow(),
                    name=name[:48],
                    user_id=user_id,
                    session_id=session_id,
                    country=(country or "").upper()[:2] or None,
                    props=json.dumps(props or {}, ensure_ascii=False, default=str),
                    ip_hash=hash_ip(ip),
                    user_agent=(user_agent or "")[:200] or None,
                )
            )
    except Exception:
        # Une mesure perdue ne vaut pas une requête perdue.
        logger.exception("Événement %s non enregistré", name)


def audit(
    action: str,
    *,
    actor: dict[str, Any] | None,
    target_type: str | None = None,
    target_id: str | int | None = None,
    changes: dict[str, Any] | None = None,
    ip: str | None = None,
    note: str | None = None,
) -> None:
    """Consigne une action d'administration. **Laisse remonter ses erreurs.**

    Contrairement à `track`, l'échec n'est pas absorbé : le back-office appelle cette
    fonction *avant* d'appliquer une modification sensible, et une trace impossible à
    écrire doit empêcher l'action plutôt que de la laisser passer anonymement.
    """
    with db.session_scope() as s:
        s.add(
            db.AuditLog(
                ts=_utcnow(),
                actor_id=(actor or {}).get("id"),
                actor_email=(actor or {}).get("email"),
                action=action[:48],
                target_type=target_type,
                target_id=str(target_id) if target_id is not None else None,
                changes=json.dumps(changes or {}, ensure_ascii=False, default=str),
                ip=(ip or "")[:45] or None,
                note=note,
            )
        )
    logger.info(
        "AUDIT %s par %s sur %s#%s", action, (actor or {}).get("email", "système"), target_type, target_id,
        extra={"audit_action": action, "target_type": target_type, "target_id": str(target_id)},
    )


def record_llm_call(
    *,
    agent: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_ms: int = 0,
    ok: bool = True,
    error: str | None = None,
    session_id: str | None = None,
    user_id: int | None = None,
    key_index: int = 0,
) -> None:
    """Enregistre un appel au fournisseur de modèle et son coût estimé.

    Le coût est calculé à l'écriture, avec le tarif en vigueur, et figé. Le recalculer
    à la lecture ferait varier rétroactivement le coût des mois passés au moindre
    changement de tarif — et un historique qui bouge ne sert à aucune décision.
    """
    cost = (
        input_tokens / 1_000_000 * settings.llm_cost_per_mtok_in_xof
        + output_tokens / 1_000_000 * settings.llm_cost_per_mtok_out_xof
    )
    try:
        with db.session_scope() as s:
            s.add(
                db.LlmCall(
                    ts=_utcnow(), agent=agent[:32], model=model[:64],
                    session_id=session_id, user_id=user_id,
                    input_tokens=input_tokens, output_tokens=output_tokens,
                    latency_ms=latency_ms, ok=ok, error=(error or "")[:200] or None,
                    cost_xof=round(cost, 4), key_index=key_index,
                )
            )
    except Exception:
        logger.exception("Appel LLM non enregistré (%s/%s)", agent, model)


def record_visit(
    session_id: str,
    *,
    country: str | None = None,
    views: int = 1,
    visitors: int = 0,
    whatsapp_clicks: int = 0,
    call_clicks: int = 0,
    day: str | None = None,
) -> None:
    """Incrémente la fréquentation agrégée d'un site publié.

    Une ligne par (site, jour, pays) : un site à succès ne doit pas produire des
    millions de lignes dont on ne tire qu'une courbe journalière. Le compteur de
    clics de contact est traité à part des vues parce que c'est *lui* la conversion
    qui compte pour un site vitrine — un client qui appuie sur « WhatsApp » vaut cent
    pages vues.
    """
    today = day or _utcnow().strftime("%Y-%m-%d")
    code = (country or "??").upper()[:2]
    try:
        with db.session_scope() as s:
            row = (
                s.query(db.SiteVisit)
                .filter_by(session_id=session_id, day=today, country=code)
                .first()
            )
            if row is None:
                row = db.SiteVisit(session_id=session_id, day=today, country=code)
                s.add(row)
            row.views += views
            row.visitors += visitors
            row.whatsapp_clicks += whatsapp_clicks
            row.call_clicks += call_clicks
    except Exception:
        logger.exception("Visite non enregistrée pour %s", session_id)


# --------------------------------------------------------------------------- #
# Interrupteurs de fonctionnalité
# --------------------------------------------------------------------------- #
def is_enabled(key: str, *, default: bool = False, user_id: int | None = None) -> bool:
    """État d'un interrupteur, avec déploiement progressif éventuel.

    Le tirage progressif est déterministe et adossé à l'identifiant de l'utilisateur :
    un compte qui voit la nouveauté continue de la voir aux appels suivants. Un tirage
    aléatoire ferait apparaître et disparaître la fonctionnalité d'une page à l'autre,
    ce qui est plus déroutant que de ne pas l'avoir du tout.
    """
    try:
        with db.session_scope() as s:
            flag = s.get(db.FeatureFlag, key)
            if flag is None:
                return default
            if not flag.enabled:
                return False
            if flag.rollout_percent >= 100 or user_id is None:
                return flag.rollout_percent >= 100
            bucket = int(hashlib.sha256(f"{key}:{user_id}".encode()).hexdigest()[:8], 16) % 100
            return bucket < flag.rollout_percent
    except Exception:
        logger.exception("Lecture de l'interrupteur %s en échec", key)
        return default


def set_flag(
    key: str, *, enabled: bool, rollout_percent: int = 100,
    description: str | None = None, actor_email: str | None = None,
) -> dict[str, Any]:
    """Crée ou met à jour un interrupteur depuis le back-office."""
    with db.session_scope() as s:
        flag = s.get(db.FeatureFlag, key)
        if flag is None:
            flag = db.FeatureFlag(key=key)
            s.add(flag)
        flag.enabled = enabled
        flag.rollout_percent = max(0, min(100, rollout_percent))
        if description is not None:
            flag.description = description
        flag.updated_at = _utcnow()
        flag.updated_by = actor_email
        s.flush()
        return db._dict(flag)


def list_flags() -> list[dict[str, Any]]:
    with db.session_scope() as s:
        return [db._dict(f) for f in s.query(db.FeatureFlag).order_by(db.FeatureFlag.key).all()]
