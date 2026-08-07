"""Client Gemini (API HTTP directe, generateContent).

Chaque appel est mesuré et consigné (`app.analytics.events.record_llm_call`) : jetons
consommés, latence, issue, clé utilisée. C'est la seule façon de répondre à « combien
me coûte un site généré », qui est la question dont dépend toute la tarification — et
sans instrumentation, la réponse n'arrive qu'avec la facture du fournisseur.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextvars import ContextVar
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("app.gemini")

#: Session et compte rattachés aux appels en cours. Passés par contexte plutôt qu'en
#: paramètre : les agents appellent `complete_json` à plusieurs niveaux d'imbrication,
#: et faire descendre un `session_id` dans chaque signature polluerait tout le
#: pipeline pour un besoin purement analytique.
_call_session: ContextVar[str | None] = ContextVar("llm_session", default=None)
_call_user: ContextVar[int | None] = ContextVar("llm_user", default=None)
_call_agent: ContextVar[str] = ContextVar("llm_agent", default="inconnu")


def attribute_calls(*, agent: str, session_id: str | None = None, user_id: int | None = None) -> None:
    """Rattache les appels suivants du même contexte à un agent et une session."""
    _call_agent.set(agent)
    _call_session.set(session_id)
    _call_user.set(user_id)


def _record(*, model: str, usage: dict[str, Any] | None, latency_ms: int, ok: bool,
            error: str | None, key_index: int) -> None:
    """Consigne l'appel. Absorbe ses propres erreurs : mesurer ne doit rien casser."""
    try:
        from app.analytics import events

        usage = usage or {}
        events.record_llm_call(
            agent=_call_agent.get(),
            model=model,
            input_tokens=int(usage.get("promptTokenCount") or 0),
            output_tokens=int(usage.get("candidatesTokenCount") or 0),
            latency_ms=latency_ms,
            ok=ok,
            error=error,
            session_id=_call_session.get(),
            user_id=_call_user.get(),
            key_index=key_index,
        )
    except Exception:
        logger.debug("Mesure d'appel LLM non enregistrée", exc_info=True)


class LLMError(RuntimeError):
    """Erreur d'appel au modèle (déclenche un retry dans le pipeline)."""


class _KeyPool:
    """Tourniquet entre plusieurs clés Gemini.

    Une clé qui a épuisé son quota (HTTP 429) n'est pas fautive pour toujours : les
    quotas Gemini se réinitialisent (par minute ou par jour selon le palier). La
    rotation avance donc simplement à la clé suivante plutôt que d'en écarter une
    définitivement — de quoi revenir dessus plus tard sans logique de retrait séparée.
    Le verrou protège l'index contre les requêtes concurrentes du même processus.
    """

    def __init__(self, keys: list[str]) -> None:
        self._keys = keys
        self._index = 0
        self._lock = asyncio.Lock()

    def __len__(self) -> int:
        return len(self._keys)

    def current(self) -> str:
        return self._keys[self._index]

    @property
    def index(self) -> int:
        """Rang de la clé en cours — consigné pour repérer une clé qui sature seule."""
        return self._index

    async def rotate(self) -> None:
        async with self._lock:
            exhausted = self._index + 1
            self._index = (self._index + 1) % len(self._keys)
            logger.warning(
                "Clé Gemini #%d en quota épuisé, bascule sur la clé #%d/%d.",
                exhausted,
                self._index + 1,
                len(self._keys),
            )


class GeminiClient:
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self) -> None:
        self._keys = _KeyPool(settings.gemini_api_keys)

    async def complete(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        json_mode: bool = False,
        response_schema: dict[str, Any] | None = None,
    ) -> str:
        """Appelle generateContent et retourne le texte de réponse."""
        if settings.gemini_mock:
            return _mock_complete(system, user, json_mode=json_mode)
        if not len(self._keys):
            raise LLMError(
                "GEMINI_API_KEY manquante. Copiez .env.example vers .env et renseignez la clé."
            )
        url = f"{self.BASE_URL}/models/{model or settings.gemini_coder_model}:generateContent"
        payload: dict[str, Any] = {
            "contents": [
                {"role": "user", "parts": [{"text": user}]},
            ],
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {
                "temperature": settings.gemini_temperature,
                # Sans plafond explicite, l'API applique un défaut bas : un site complet
                # (html + css + js dans un même objet JSON) était coupé en plein milieu,
                # et la troncature ne se manifestait que par un JSON invalide.
                "maxOutputTokens": settings.gemini_max_output_tokens,
            },
        }
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        if response_schema is not None:
            # `responseMimeType` seul n'est qu'une consigne de forme : sur un objet volumineux
            # (site complet avec attributs HTML entre guillemets), Gemini échouait encore à
            # échapper correctement les guillemets internes, produisant un JSON invalide
            # ("Expecting ',' delimiter") après 3 tentatives. `responseSchema` bascule sur le
            # décodage contraint par grammaire, qui garantit une syntaxe JSON valide.
            payload["generationConfig"]["responseMimeType"] = "application/json"
            payload["generationConfig"]["responseSchema"] = response_schema

        # Une tentative par clé du pool : si toutes rendent 429, la génération échoue
        # réellement (plus aucun quota disponible) plutôt que de tourner indéfiniment.
        quota_errors: list[str] = []
        resolved_model = model or settings.gemini_coder_model
        for _ in range(len(self._keys)):
            key = self._keys.current()
            key_index = self._keys.index
            started = time.perf_counter()
            try:
                async with httpx.AsyncClient(timeout=settings.gemini_timeout_s) as client:
                    resp = await client.post(
                        url,
                        params={"key": key},
                        json=payload,
                    )
            except httpx.HTTPError as exc:
                _record(model=resolved_model, usage=None, latency_ms=_ms(started),
                        ok=False, error=f"réseau: {exc}"[:200], key_index=key_index)
                raise LLMError(f"Réseau: échec de l'appel Gemini ({exc})") from exc

            latency = _ms(started)

            if resp.status_code == 429:
                _record(model=resolved_model, usage=None, latency_ms=latency,
                        ok=False, error="429 quota épuisé", key_index=key_index)
                quota_errors.append(resp.text[:200])
                await self._keys.rotate()
                continue

            if resp.status_code != 200:
                detail = resp.text[:300]
                _record(model=resolved_model, usage=None, latency_ms=latency,
                        ok=False, error=f"HTTP {resp.status_code}", key_index=key_index)
                raise LLMError(f"Gemini HTTP {resp.status_code}: {detail}")

            data = resp.json()
            _record(model=resolved_model, usage=data.get("usageMetadata"), latency_ms=latency,
                    ok=True, error=None, key_index=key_index)
            try:
                candidate = data["candidates"][0]
                text = candidate["content"]["parts"][0]["text"]
            except (KeyError, IndexError) as exc:
                raise LLMError(f"Réponse Gemini inattendue: {json.dumps(data)[:300]}") from exc

            # Une réponse coupée par le plafond de sortie reste un texte valide côté HTTP :
            # sans ce contrôle, elle ne se manifeste que par un « JSON invalide » à un
            # caractère arbitraire, et les tentatives suivantes échouent à l'identique.
            if candidate.get("finishReason") == "MAX_TOKENS":
                raise LLMError(
                    "Réponse Gemini tronquée (plafond de sortie atteint). "
                    f"Augmentez GEMINI_MAX_OUTPUT_TOKENS (actuellement {settings.gemini_max_output_tokens})."
                )

            if json_mode:
                text = _extract_json(text)
            return text

        raise LLMError(
            f"Quota Gemini épuisé sur les {len(self._keys)} clé(s) configurée(s): "
            f"{quota_errors[-1] if quota_errors else 'inconnu'}"
        )

    async def complete_json(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Appelle Gemini en mode JSON et retourne un dict."""
        text = await self.complete(
            system, user, model=model, json_mode=True, response_schema=response_schema
        )
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Réponse non-JSON de Gemini: {exc}") from exc


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _extract_json(text: str) -> str:
    """Récupère le bloc JSON d'une réponse (résilient au markdown/fences)."""
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


# --------------------------------------------------------------------------- #
# Mode mock (GEMINI_MOCK=true) : réponses déterministes, sans réseau.
# Utile pour les tests, la CI, et comme plan B en démo si l'API est indisponible.
# --------------------------------------------------------------------------- #
def _mock_complete(system: str, user: str, *, json_mode: bool) -> str:
    if "# AGENT CODEUR" in system:
        return json.dumps(_mock_site(user))
    if "# AGENT REVUE" in system:
        return json.dumps(_mock_report(user))
    if "# DESIGNER" in system:
        return json.dumps(_mock_spec(user))
    return json.dumps({"ok": True, "note": "mock"}) if json_mode else "OK"


def _field(user: str, key: str, default: str = "") -> str:
    import re

    m = re.search(rf'"{key}"\s*:\s*"([^"]*)"', user)
    return m.group(1) if m else default


def _mock_spec(user: str) -> dict:
    name = _field(user, "name") or "Mon entreprise"
    return {
        "name": name,
        "tagline": "Votre partenaire de confiance",
        "business_type": "autre",
        "description": f"{name} propose des services de qualité à sa clientèle.",
        "tone": "moderne",
        "audience": "particuliers et professionnels",
        "style": "moderne",
        "language": "fr",
        "palette": {"primary": "#1d4ed8", "secondary": "#f1f5f9", "accent": "#f59e0b", "bg": "#ffffff", "text": "#0f172a"},
        "typography": {"heading_font": "Georgia, serif", "body_font": "system-ui, sans-serif", "base_size": "16px"},
        "sections": [
            {"id": "apropos", "title": "À propos", "content": f"Découvrez {name} et son savoir-faire.", "order": 1},
            {"id": "services", "title": "Services", "content": "Des prestations adaptées à vos besoins.", "order": 2},
            {"id": "contact", "title": "Contact", "content": "Contactez-nous pour un devis gratuit.", "order": 3},
        ],
        "contact": {"phone": "", "email": "", "address": "", "hours": ""},
        "cta": "Nous contacter",
    }


def _mock_site(user: str) -> dict:
    name = _field(user, "name") or "Mon entreprise"
    tagline = _field(user, "tagline") or "Bienvenue"
    primary = _field(user, "primary", "#1d4ed8")
    bg = _field(user, "bg", "#ffffff")
    text = _field(user, "text", "#0f172a")
    language = _field(user, "language", "fr")
    html = f"""<!DOCTYPE html>
<html lang="{language}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{name}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <header class="site-header">
    <a class="brand" href="#top">{name}</a>
    <nav aria-label="principal">
      <a href="#apropos">À propos</a>
      <a href="#services">Services</a>
      <a href="#contact">Contact</a>
    </nav>
  </header>
  <main>
    <section id="top" class="hero">
      <h1>{name}</h1>
      <p class="tagline">{tagline}</p>
      <a class="cta" href="#contact">Nous contacter</a>
    </section>
    <section id="apropos"><h2>À propos</h2><p>Découvrez notre savoir-faire.</p></section>
    <section id="services"><h2>Services</h2><p>Des prestations adaptées à vos besoins.</p></section>
    <section id="contact"><h2>Contact</h2><p>Demandez un devis gratuit.</p></section>
  </main>
  <footer><p>&copy; {name}</p></footer>
  <script src="script.js"></script>
</body>
</html>"""
    css = f""":root {{ --c-primary: {primary}; --c-bg: {bg}; --c-text: {text}; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: system-ui, sans-serif; color: var(--c-text); background: var(--c-bg); line-height: 1.6; }}
.site-header {{ display: flex; justify-content: space-between; align-items: center; padding: 1rem 2rem; background: var(--c-primary); color: #fff; position: sticky; top: 0; }}
.site-header a {{ color: #fff; text-decoration: none; margin-left: 1rem; }}
.hero {{ padding: 6rem 2rem; text-align: center; background: linear-gradient(135deg, var(--c-primary), color-mix(in srgb, var(--c-primary) 60%, #000)); color: #fff; }}
.tagline {{ font-size: 1.25rem; margin: 1rem 0 2rem; }}
.cta {{ display: inline-block; padding: .8rem 1.6rem; background: #fff; color: var(--c-primary); border-radius: 8px; font-weight: 700; text-decoration: none; }}
section {{ padding: 4rem 2rem; max-width: 960px; margin: 0 auto; }}
h2 {{ margin-bottom: 1rem; color: var(--c-primary); }}
footer {{ text-align: center; padding: 2rem; background: #f1f5f9; }}
@media (max-width: 640px) {{ .site-header {{ flex-direction: column; gap: .5rem; }} }}"""
    js = """document.querySelectorAll('a[href^="#"]').forEach(a => {
  a.addEventListener('click', e => {
    const t = document.querySelector(a.getAttribute('href'));
    if (t) { e.preventDefault(); t.scrollIntoView({ behavior: 'smooth' }); }
  });
});"""
    return {"html": html, "css": css, "js": js}


def _mock_report(user: str) -> dict:
    html = user[user.find("## Site généré") :] if "## Site généré" in user else ""
    findings = []
    if "eval(" in html:
        findings.append({"severity": "critical", "category": "security", "title": "eval() détecté", "detail": "Code arbitraire.", "fix": "Supprimer.", "file": "index.html"})
    if "<!DOCTYPE" not in html.upper() and "<!doctype" not in html:
        findings.append({"severity": "high", "category": "quality", "title": "Doctype manquant", "detail": "HTML incomplet.", "fix": "Ajouter le doctype.", "file": "index.html"})
    if not findings:
        findings.append({"severity": "info", "category": "quality", "title": "Aucun problème critique", "detail": "Le site est sain.", "fix": "", "file": "index.html"})
    sev = findings[0]["severity"]
    score = 95 if sev == "info" else 60
    return {
        "score": score,
        "verdict": "pass" if sev == "info" else "warn",
        "dimensions": {"security": 95 if sev == "info" else 55, "design_fidelity": 88, "accessibility": 82, "responsiveness": 90, "content": 85},
        "findings": findings,
        "summary": "Rapport mock : le site est globalement sain et conforme à la spécification.",
    }


gemini = GeminiClient()
