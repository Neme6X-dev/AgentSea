"""Déploiement des sites générés : écriture versionnée, live local, SFTP VPS."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from app.config import settings
from app.contracts import GeneratedSite

_FILES = ("index.html", "style.css", "script.js", "jarvis-metrics.js")

#: Balise de fréquentation, écrite dans un fichier servi à côté du site.
#:
#: Injectée par la plateforme, et non demandée à l'agent codeur : un modèle omet ou
#: déforme régulièrement un bloc technique de ce genre, et une mesure absente sur un
#: site sur cinq rend toutes les statistiques inexploitables. Ici, elle est identique
#: partout et vérifiable.
#:
#: Ce qu'elle envoie tient en trois champs : le site, le type d'événement, et un
#: drapeau « première visite du jour » décidé localement. Ni identifiant de visiteur,
#: ni URL complète, ni empreinte de navigateur — ce qu'on ne collecte pas ne fuite pas.
#:
#: `sendBeacon` plutôt que `fetch` : la requête part même si le visiteur quitte la
#: page dans la foulée, ce qui est précisément le cas quand il clique sur WhatsApp.
#:
#: Fichier externe et non script inline : la politique de sécurité appliquée aux sites
#: publiés interdit le script inline (`script-src 'self'`), et l'assouplir pour cette
#: balise rouvrirait la voie à toute injection dans du HTML produit par un modèle.
_BEACON_TEMPLATE = """(function () {
  var API = %(api)s, SLUG = %(slug)s;
  function envoyer(type, unique) {
    try {
      var corps = JSON.stringify({ slug: SLUG, event: type, unique: !!unique });
      if (navigator.sendBeacon) {
        navigator.sendBeacon(API, new Blob([corps], { type: 'application/json' }));
      } else {
        fetch(API, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: corps, keepalive: true });
      }
    } catch (e) { /* la mesure ne doit jamais casser le site */ }
  }
  var jour = new Date().toISOString().slice(0, 10), cle = 'jv_' + SLUG, premiere = false;
  try { premiere = localStorage.getItem(cle) !== jour; if (premiere) localStorage.setItem(cle, jour); } catch (e) {}
  envoyer('view', premiere);
  document.addEventListener('click', function (e) {
    var lien = e.target && e.target.closest ? e.target.closest('a[href]') : null;
    if (!lien) return;
    var href = lien.getAttribute('href') || '';
    if (href.indexOf('wa.me') !== -1 || href.indexOf('whatsapp') !== -1) envoyer('whatsapp');
    else if (href.indexOf('tel:') === 0) envoyer('call');
  }, true);
})();
"""


def slug_dir(slug: str) -> Path:
    return settings.sites_dir / slug


def version_dir(slug: str, version: int) -> Path:
    return slug_dir(slug) / f"v{version}"


def live_dir(slug: str) -> Path:
    return slug_dir(slug) / "live"


BEACON_FILE = "jarvis-metrics.js"


def beacon_script(slug: str) -> str:
    """Contenu du fichier de mesure pour un site donné.

    L'URL de l'API est absolue et construite depuis `PUBLIC_BASE_URL` : le site peut
    être servi depuis un domaine personnalisé ou un sous-domaine, une URL relative n'y
    résoudrait pas vers l'API.
    """
    api = f"{settings.public_base_url.rstrip('/')}/api/public/beacon"
    return _BEACON_TEMPLATE % {"api": json.dumps(api), "slug": json.dumps(slug)}


def inject_beacon(html: str, slug: str) -> str:
    """Référence le fichier de mesure avant `</body>`, sans jamais le dupliquer.

    Le repli en fin de document couvre le cas d'un HTML sans `</body>` — rare, mais
    un site publié sans mesure est une donnée manquante qu'on ne rattrape jamais.
    """
    if BEACON_FILE in html:
        return html
    balise = f'<script src="{BEACON_FILE}" defer></script>'
    if re.search(r"</body\s*>", html, re.IGNORECASE):
        return re.sub(r"</body\s*>", f"{balise}\n</body>", html, count=1, flags=re.IGNORECASE)
    return f"{html}\n{balise}"


def write_site_files(slug: str, version: int, site: GeneratedSite) -> Path:
    """Écrit le site versionné sur disque et retourne son dossier.

    La mesure est ajoutée ici, à l'écriture : toutes les versions la portent, y compris
    celles qu'on republie lors d'un retour arrière.
    """
    dest = version_dir(slug, version)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "index.html").write_text(inject_beacon(site.html, slug), encoding="utf-8")
    (dest / "style.css").write_text(site.css, encoding="utf-8")
    (dest / "script.js").write_text(site.js, encoding="utf-8")
    (dest / BEACON_FILE).write_text(beacon_script(slug), encoding="utf-8")
    return dest


def deploy_local(slug: str, version: int | None = None) -> str:
    """Met en 'live' une version locale et retourne son URL publique.

    Args:
        version: version à publier. `None` prend la plus récente. Publier une version
            antérieure est exactement ce qui permet un retour arrière : toutes les
            versions restent sur disque.
    """
    if version is not None:
        latest = version_dir(slug, version)
        if not latest.is_dir():
            raise FileNotFoundError(f"Version v{version} introuvable pour {slug}")
    else:
        versions = sorted(
            (d for d in slug_dir(slug).iterdir() if d.is_dir() and d.name.startswith("v")),
            key=lambda d: int(d.name[1:]),
        )
        if not versions:
            raise FileNotFoundError(f"Aucune version pour {slug}")
        latest = versions[-1]
    live = live_dir(slug)
    live.mkdir(parents=True, exist_ok=True)
    for fname in _FILES:
        source = latest / fname
        # Un fichier absent n'interrompt pas la publication : les versions générées
        # avant l'ajout de la mesure n'ont pas de `jarvis-metrics.js`, et un retour
        # arrière vers l'une d'elles doit rester possible. Le HTML de ces versions ne
        # le référence pas non plus, l'ensemble reste cohérent.
        if source.is_file():
            shutil.copy2(source, live / fname)
        else:
            (live / fname).unlink(missing_ok=True)
    return f"{settings.public_base_url.rstrip('/')}/sites/{slug}/live/"


def deploy_vps(slug: str) -> str:
    """Téléverse le site live vers le VPS via SFTP (paramiko). Retourne l'URL publique."""
    if not settings.vps_configured:
        raise RuntimeError("VPS non configuré (VPS_HOST/VPS_USER manquants).")

    import paramiko

    key_path = Path(settings.vps_key_path).expanduser()
    remote_dir = f"{settings.vps_base_dir.rstrip('/')}/{slug}"
    hostname = settings.vps_domain or settings.vps_host

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(
            hostname=settings.vps_host,
            port=settings.vps_port,
            username=settings.vps_user,
            key_filename=str(key_path) if key_path.is_file() else None,
            timeout=30,
        )
        with ssh.open_sftp() as sftp:
            _ensure_remote_dir(sftp, remote_dir)
            live = live_dir(slug)
            for fname in _FILES:
                source = live / fname
                # Même tolérance qu'en local : une version antérieure à l'ajout de la
                # mesure ne porte pas ce fichier, et son absence ne doit pas faire
                # échouer une publication par ailleurs valide.
                if source.is_file():
                    sftp.put(str(source), f"{remote_dir}/{fname}")
    finally:
        ssh.close()

    if settings.vps_use_subdomain and settings.vps_domain:
        return f"https://{slug}.{settings.vps_domain}/"
    return f"https://{hostname}/{slug}/"


def _ensure_remote_dir(sftp, remote_dir: str) -> None:
    parts = remote_dir.split("/")
    current = ""
    for part in parts:
        if not part:
            continue
        current = f"{current}/{part}"
        try:
            sftp.stat(current)
        except FileNotFoundError:
            sftp.mkdir(current)
