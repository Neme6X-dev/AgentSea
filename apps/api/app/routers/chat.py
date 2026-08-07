"""Chat de cadrage — relais vers l'agent conversationnel n8n (Caleb).

Le front ne parle pas directement au webhook : le passer par le backend évite un
préflight CORS vers un domaine tiers et garde l'URL n8n côté serveur, où elle se
change sans reconstruire le bundle.

Ce cadrage n'est pas une politesse. Sans lui, un simple « bonjour » partirait au
designer et produirait un site que personne n'a demandé : l'agent interroge
l'utilisateur jusqu'à cerner le besoin, et ne rend un DesignSpec qu'ensuite.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter

import logging

from app.agents import designer, designer_n8n
from app.contracts import ChatRequest, ChatResponse
from app.security import CurrentUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

INDISPONIBLE = (
    "Décrivez votre projet en une phrase et lancez la génération avec le bouton "
    "ci-dessous : le designer interne prendra le relais."
)


@router.post("", response_model=ChatResponse)
async def chat(payload: ChatRequest, user: CurrentUser) -> ChatResponse:
    """Transmet un message à l'agent de cadrage et retourne sa réponse.

    Une panne de n8n n'est pas une erreur HTTP : le front doit pouvoir afficher le
    message et proposer de continuer sans cadrage, plutôt que de laisser l'utilisateur
    devant un échec dont il ne peut rien faire.
    """
    conversation_id = payload.conversation_id or uuid.uuid4().hex

    reply, spec, plan, erreur = await designer_n8n.chat(
        payload.message, conversation_id=conversation_id
    )

    if reply is None:
        # La cause est montrée telle quelle : « injoignable » envoyait chercher le
        # problème côté réseau alors que le workflow amont répondait une erreur.
        return ChatResponse(
            conversation_id=conversation_id,
            reply=f"{erreur or 'Assistant de cadrage indisponible.'}\n\n{INDISPONIBLE}",
            available=False,
        )

    # Le workflow ne rend pas un spec complet : il tranche un template et des pages.
    # Le contenu, la palette et la typographie restent à composer côté backend.
    if spec is None and plan is not None:
        try:
            spec = await designer.spec_from_plan(payload.message, plan)
        except Exception as exc:
            # Le cadrage a abouti : mieux vaut rendre la réponse de l'agent et laisser
            # l'utilisateur lancer la génération que de perdre tout l'entretien.
            logger.warning("Composition du spec depuis le plan n8n impossible (%s).", exc)
            # Sans cette précision, le front affiche tel quel le message de l'agent
            # (« je lance la construction… ») sans qu'aucune génération ne démarre :
            # rien ne distingue alors un échec silencieux d'un blocage. `design_spec`
            # reste `None`, donc l'auto-enchaînement ne se déclenche pas côté front ;
            # on dit explicitement pourquoi et comment reprendre la main.
            reply = (
                f"{reply}\n\nLa préparation automatique du site a rencontré un problème "
                "technique. Cliquez sur « Générer le site » ci-dessous pour lancer la "
                "génération avec les informations recueillies."
            )

    return ChatResponse(conversation_id=conversation_id, reply=reply, design_spec=spec)
