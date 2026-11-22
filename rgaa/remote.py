"""Analyse d'une page distante : récupération, nettoyage minimal, inspection.

Une seule requête HTTP, sans dépendance, sans JavaScript exécuté : on récupère
le HTML tel que le serveur l'envoie, on retire les balises `script` et `noscript`
(elles ne changent rien à l'audit et alourdissent le journal), et on enregistre
la page sous un nom stable dans le bac à sable.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

MAX_BYTES = 3 * 1024 * 1024
USER_AGENT = "RGAAGent/1.0 (+analyse locale, une requete par page)"
BLOCKED_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


class RemoteError(Exception):
    pass


def page_name(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "page").replace(".", "-")
    leaf = Path(parsed.path).name or "index"
    if not leaf.endswith((".html", ".htm")):
        leaf = f"{leaf}.html"
    return f"{host}-{leaf}"


def fetch(url: str, timeout: int = 20, allow_private: bool = False, keep_scripts: bool = False) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise RemoteError("seules les URL http et https sont acceptées")
    if not parsed.hostname:
        raise RemoteError("URL sans nom d'hôte")
    if parsed.hostname in BLOCKED_HOSTS and not allow_private:
        raise RemoteError("hôte local refusé : relancer avec autorisation explicite ou analyser un fichier")

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL fournie par l'utilisateur
            raw = response.read(MAX_BYTES + 1)
            content_type = response.headers.get("Content-Type", "")
            status = response.status
    except urllib.error.HTTPError as exc:
        raise RemoteError(f"HTTP {exc.code} sur {url}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RemoteError(f"injoignable : {exc}") from exc

    if len(raw) > MAX_BYTES:
        raise RemoteError(f"page trop lourde (plus de {MAX_BYTES // 1024} ko)")
    charset = "utf-8"
    match = re.search(r"charset=([\w-]+)", content_type, re.I)
    if match:
        charset = match.group(1)
    try:
        html = raw.decode(charset, "replace")
    except LookupError:
        html = raw.decode("utf-8", "replace")

    if not keep_scripts:
        html = re.sub(r"(?is)<script[^>]*>.*?</script>", "", html)
        html = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", "", html)

    return {
        "url": url,
        "status": status,
        "content_type": content_type,
        "bytes": len(raw),
        "chars": len(html),
        "html": html,
        "name": page_name(url),
    }


def save(result: dict[str, Any], sandbox: Path) -> Path:
    sandbox = Path(sandbox)
    sandbox.mkdir(parents=True, exist_ok=True)
    target = sandbox / result["name"]
    target.write_text(result["html"], encoding="utf-8")
    return target


MAX_IMAGE_BYTES = 4 * 1024 * 1024


def fetch_image(url: str, timeout: int = 20) -> bytes:
    """Récupère une image distante pour l'envoyer à un modèle vision local."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - URL issue de la page analysée
            payload = response.read(MAX_IMAGE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise RemoteError(f"HTTP {exc.code} sur l'image {url}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RemoteError(f"image injoignable {url} : {exc}") from exc
    if len(payload) > MAX_IMAGE_BYTES:
        raise RemoteError(f"image trop lourde (plus de {MAX_IMAGE_BYTES // 1024} ko) : {url}")
    return payload
