"""Description d'image par un modèle vision local, avec repli explicite.

Deux protocoles essayés dans l'ordre, sans dépendance :

1. **OpenAI-compatible** (LM Studio, vLLM, Ollama récent) : ``/v1/chat/completions``
   avec l'image en data URI base64.
2. **Ollama natif** : ``/api/generate`` avec le tableau ``images``, quand le
   serveur n'accepte pas encore le format OpenAI multimodal.

Si aucun des deux ne répond, l'outil ne fabrique pas de description : il renvoie
``available: false`` et une consigne de repli, pour que l'agent continue en
s'appuyant sur le contexte HTML (nom de fichier, ``title``, texte du lien).
"""

from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}
MAX_BYTES = 8 * 1024 * 1024

DEFAULT_PROMPT = (
    "Décris cette image en une phrase courte et factuelle, en français, pour servir d'attribut alt HTML. "
    "Dis ce qu'elle montre réellement (objet, personne en action, lieu), pas le style de la photo. "
    "Pas de préambule, pas de guillemets, pas de point final. Maximum 120 caractères."
)

ANALYSE_PROMPT = (
    "Analyse cette image pour un audit d'accessibilité. Réponds exactement sur trois lignes, sans préambule :\n"
    "DESCRIPTION: description factuelle en français, maximum 120 caractères, utilisable comme attribut alt\n"
    "TEXTE: oui ou non, l'image contient-elle du texte lisible\n"
    "TYPE: photo, illustration, icone, graphique ou logo"
)

KIND_WORDS = ("photo", "illustration", "icone", "icône", "graphique", "logo")


def _target_bytes(target: Any) -> tuple[bytes, str]:
    """Accepte un chemin ou des octets déjà chargés (image distante incluse)."""
    if isinstance(target, (bytes, bytearray)):
        return bytes(target), "image/png"
    path = Path(target)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError(f"image trop lourde ({path.stat().st_size} octets, limite {MAX_BYTES})")
    mime = MIME.get(path.suffix.lower())
    if not mime:
        raise ValueError(f"format d'image non pris en charge : {path.suffix or 'aucun'}")
    return path.read_bytes(), mime


def _data_uri_bytes(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def parse_analyse(text: str) -> dict[str, Any]:
    """Lit la réponse balisée du VLM, avec repli sur le texte libre."""
    description = ""
    contains_text: bool | None = None
    kind = ""
    for line in str(text).splitlines():
        upper = line.strip().upper()
        if upper.startswith("DESCRIPTION:"):
            description = line.split(":", 1)[1].strip()
        elif upper.startswith("TEXTE:"):
            value = line.split(":", 1)[1].strip().lower()
            contains_text = value.startswith(("oui", "yes", "true", "1"))
        elif upper.startswith("TYPE:"):
            value = line.split(":", 1)[1].strip().lower()
            kind = next((word for word in KIND_WORDS if word in value), value)
    if not description:
        description = str(text)
    usable = clean_description(description)
    return {
        "description": usable,
        "brut": " ".join(description.split())[:300],
        "usable": bool(usable),
        "contains_text": contains_text,
        "kind": kind,
    }


def analyse_image(
    target: Any,
    base_url: str | None,
    model: str | None,
    api_key: str | None = None,
    timeout: int = 240,
) -> dict[str, Any]:
    """Décrit l'image et dit si elle contient du texte : la brique d'un audit complet."""
    data, mime = _target_bytes(target)
    started = time.perf_counter()

    if not base_url or not model:
        return {
            "available": False,
            "source": "fallback",
            "reason": "aucun modèle vision configuré (RGAA_VISION_URL / RGAA_VISION_MODEL)",
            "ms": 0,
        }

    base = _normalize_base(base_url)
    uri = _data_uri_bytes(data, mime)
    errors: list[str] = []

    try:
        text = _openai_call(base, model, ANALYSE_PROMPT, uri, api_key, timeout)
        parsed = parse_analyse(text)
        if parsed["description"]:
            return {
                "available": True,
                "source": "vlm-openai",
                "model": model,
                **parsed,
                "ms": round((time.perf_counter() - started) * 1000),
            }
        errors.append("réponse vide en protocole OpenAI")
    except (urllib.error.URLError, KeyError, IndexError, TypeError, json.JSONDecodeError, TimeoutError) as exc:
        errors.append(f"OpenAI: {type(exc).__name__}: {exc}")

    try:
        text = _ollama_call(base, model, ANALYSE_PROMPT, data, timeout)
        parsed = parse_analyse(text)
        if parsed["description"]:
            return {
                "available": True,
                "source": "vlm-ollama",
                "model": model,
                **parsed,
                "ms": round((time.perf_counter() - started) * 1000),
            }
        errors.append("réponse vide en protocole Ollama")
    except (urllib.error.URLError, KeyError, TypeError, json.JSONDecodeError, TimeoutError) as exc:
        errors.append(f"Ollama: {type(exc).__name__}: {exc}")

    return {
        "available": False,
        "source": "fallback",
        "reason": "aucun modèle vision n'a répondu",
        "errors": errors,
        "ms": round((time.perf_counter() - started) * 1000),
    }


def _data_uri(path: Path) -> str:
    mime = MIME.get(path.suffix.lower(), "application/octet-stream")
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{payload}"


def _post_json(url: str, payload: dict[str, Any], api_key: str | None, timeout: int) -> Any:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - endpoint local choisi
        return json.loads(response.read().decode("utf-8"))


def _normalize_base(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        raise ValueError("base_url vide")
    if not base.startswith(("http://", "https://")):
        base = "http://" + base
    return base


def _openai_call(base: str, model: str, prompt: str, uri: str, api_key: str | None, timeout: int) -> str:
    payload = {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 200,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": uri}},
                ],
            }
        ],
    }
    endpoint = base if base.endswith("/chat/completions") else (base if base.endswith("/v1") else base + "/v1") + "/chat/completions"
    response = _post_json(endpoint, payload, api_key, timeout)
    return str(response["choices"][0]["message"]["content"])


def _ollama_call(base: str, model: str, prompt: str, payload: "bytes | Path", timeout: int) -> str:
    data = payload.read_bytes() if isinstance(payload, Path) else payload
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "images": [base64.b64encode(data).decode("ascii")],
        "options": {"num_predict": 80, "temperature": 0},
    }
    root = base[:-3] if base.endswith("/v1") else base
    response = _post_json(root.rstrip("/") + "/api/generate", body, None, timeout)
    return str(response.get("response", ""))


ENGLISH_MARKERS = (" the ", " a ", " an ", " with ", " which ", " appears ", " image features ")


def looks_french(text: str) -> bool:
    """Un texte utile comme alt français : accents, mots outils, pas de tournure anglaise."""
    lowered = f" {text.lower()} "
    if any(marker in lowered for marker in ENGLISH_MARKERS):
        return False
    french = (" le ", " la ", " les ", " un ", " une ", " des ", " du ", " de ", " au ", " aux ", " sur ", " dans ", " avec ")
    if any(word in lowered for word in french):
        return True
    return any(char in text for char in "àâäéèêëîïôöùûüçÀÉÈÊÎÔÙÇ")


def clean_description(text: str, limit: int = 120) -> str:
    """Nettoie une description de modèle, et renvoie une chaîne vide si elle n'est pas utilisable."""
    cleaned = " ".join(str(text).split()).strip().strip('"').strip("«»").strip()
    lowered = cleaned.lower()
    for prefix in (
        "voici une image de ", "voici l'image de ", "voici ",
        "l'image montre ", "cette image montre ", "sur cette image, ", "cette image ",
        "the image features ", "the image shows ", "this image shows ", "an image of ", "image of ",
    ):
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
            lowered = cleaned.lower()
            break
    if not cleaned:
        return ""
    if cleaned.endswith("."):
        cleaned = cleaned[:-1]
    if len(cleaned) > limit:
        cut = cleaned[:limit]
        cleaned = cut[: cut.rfind(" ")] if " " in cut else cut
    if len(cleaned) < 4:
        return ""
    if not looks_french(cleaned):
        return ""
    return cleaned


def describe_image(
    path: Path,
    base_url: str | None,
    model: str | None,
    prompt: str = "",
    api_key: str | None = None,
    timeout: int = 240,
) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError(f"image trop lourde ({path.stat().st_size} octets, limite {MAX_BYTES})")
    if path.suffix.lower() not in MIME:
        raise ValueError(f"format d'image non pris en charge : {path.suffix or 'aucun'}")

    question = (prompt or DEFAULT_PROMPT).strip()
    started = time.perf_counter()

    if not base_url or not model:
        return {
            "available": False,
            "source": "fallback",
            "reason": "aucun modèle vision configuré (RGAA_VISION_URL / RGAA_VISION_MODEL)",
            "fallback_hint": "décrire depuis le contexte HTML : title de l'image, texte du lien parent, nom de fichier",
            "ms": 0,
        }

    base = _normalize_base(base_url)
    errors: list[str] = []
    uri = _data_uri(path)

    try:
        text = _openai_call(base, model, question, uri, api_key, timeout)
        description = clean_description(text)
        if description:
            return {
                "available": True,
                "source": "vlm-openai",
                "model": model,
                "description": description,
                "chars": len(description),
                "ms": round((time.perf_counter() - started) * 1000),
            }
        errors.append("réponse vide en protocole OpenAI")
    except (urllib.error.URLError, KeyError, IndexError, TypeError, json.JSONDecodeError, TimeoutError) as exc:
        errors.append(f"OpenAI: {type(exc).__name__}: {exc}")

    try:
        text = _ollama_call(base, model, question, path, timeout)
        description = clean_description(text)
        if description:
            return {
                "available": True,
                "source": "vlm-ollama",
                "model": model,
                "description": description,
                "chars": len(description),
                "ms": round((time.perf_counter() - started) * 1000),
            }
        errors.append("réponse vide en protocole Ollama")
    except (urllib.error.URLError, KeyError, TypeError, json.JSONDecodeError, TimeoutError) as exc:
        errors.append(f"Ollama: {type(exc).__name__}: {exc}")

    return {
        "available": False,
        "source": "fallback",
        "reason": "aucun modèle vision n'a répondu",
        "errors": errors,
        "fallback_hint": "décrire depuis le contexte HTML et signaler la description comme déduite",
        "ms": round((time.perf_counter() - started) * 1000),
    }


def probe(base_url: str, api_key: str | None = None, timeout: int = 10) -> dict[str, Any]:
    """Liste les modèles exposés, pour savoir si un VLM est réellement chargé."""
    base = _normalize_base(base_url)
    endpoint = (base if base.endswith("/v1") else base + "/v1") + "/models"
    request = urllib.request.Request(endpoint)
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    models = [entry.get("id") for entry in payload.get("data", []) if entry.get("id")]
    hints = [name for name in models if any(token in name.lower() for token in ("vl", "vision", "llava", "moondream", "gemma3"))]
    return {"base_url": base, "models": models, "vision_candidates": hints}
