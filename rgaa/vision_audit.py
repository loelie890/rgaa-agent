"""Audit des images par le modèle vision : ce que le HTML ne peut pas dire.

Trois constats sont impossibles sur le seul balisage :

* l'image est-elle réellement informative ou décorative ;
* l'alternative décrit-elle ce que l'image montre, ou répète-t-elle « image » ;
* l'image contient-elle du texte lisible, qui doit alors se retrouver dans
  l'alternative.

Le modèle vision répond à ces questions. Sans modèle, la fonction ne produit
aucun constat et le dit : l'audit reste celui des douze règles HTML.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from .dom import Document, apply_patch, parse, select
from .kernel import normalize
from .remote import fetch_image
from .vision import analyse_image

GENERIC_ALT = {
    "image",
    "photo",
    "picture",
    "img",
    "logo",
    "icone",
    "icon",
    "illustration",
    "banniere",
    "banner",
    "graphique",
    "hero",
    "cliquez ici",
    "cliquez-ici",
    "lien",
    "bouton",
    "image de",
}

RULES = {
    "vision-alt-absente": ("Alternative textuelle absente", "1.1", "bloquant"),
    "vision-alt-generique": ("Alternative textuelle non informative", "1.3", "majeur"),
    "vision-texte-image": ("Texte porté par une image", "1.3", "majeur"),
    "vision-alt-incoherent": ("Alternative probablement hors sujet", "1.3", "mineur"),
}


def selector_for_image(node: Any) -> str:
    if node.get("id"):
        return f"img#{node.get('id')}"
    if node.get("src"):
        return f'img[src="{node.get("src")}"]'
    return "img"


def _words(text: str) -> set[str]:
    return {word for word in re.split(r"\W+", normalize(text)) if len(word) > 2}


def _looks_generic(alt: str, src: str) -> bool:
    cleaned = normalize(alt).strip(" .!")
    if cleaned in GENERIC_ALT:
        return True
    stem = normalize(Path(src.split("?")[0]).stem) if src else ""
    return bool(stem) and cleaned == stem.replace("-", " ")


def classify(alt: str | None, analysis: dict[str, Any]) -> dict[str, Any] | None:
    """Verdict pour une image, ou None si l'alternative tient la route."""
    if not analysis.get("available"):
        return None
    description = str(analysis.get("description") or "").strip()
    if not description:
        return None
    alt_text = (alt or "").strip()
    source = analysis.get("src", "")

    if not alt_text:
        return {
            "rule": "vision-alt-absente",
            "severity": RULES["vision-alt-absente"][2],
            "message": f"aucune alternative textuelle ; le modèle voit : « {description} »",
            "proposed_alt": description,
        }

    if _looks_generic(alt_text, source):
        return {
            "rule": "vision-alt-generique",
            "severity": RULES["vision-alt-generique"][2],
            "message": f"l'alternative « {alt_text} » ne décrit rien ; le modèle voit : « {description} »",
            "proposed_alt": description,
        }

    if analysis.get("contains_text") and _words(alt_text) & _words(description) == set():
        return {
            "rule": "vision-texte-image",
            "severity": RULES["vision-texte-image"][2],
            "message": f"l'image porte du texte absent de l'alternative ; le modèle lit : « {description} »",
            "proposed_alt": description,
        }

    if len(_words(alt_text)) <= 3 and _words(alt_text) & _words(description) == set():
        return {
            "rule": "vision-alt-incoherent",
            "severity": RULES["vision-alt-incoherent"][2],
            "message": f"l'alternative « {alt_text} » et l'image décrite (« {description} ») ne se recoupent pas",
            "proposed_alt": description,
        }
    return None


def _resolve_target(src: str, site_root: Path, base_url: str | None) -> tuple[Any, str]:
    """Octets de l'image : fichier local du bac à sable, ou téléchargement distant."""
    if not src:
        raise FileNotFoundError("attribut src absent")
    if src.startswith(("http://", "https://")):
        return fetch_image(src), "url"
    if base_url:
        return fetch_image(urljoin(base_url, src)), "url"
    candidate = (Path(site_root) / src).resolve()
    root = Path(site_root).resolve()
    if root not in candidate.parents and candidate != root:
        raise FileNotFoundError(f"chemin hors du site : {src}")
    if not candidate.is_file():
        raise FileNotFoundError(f"image introuvable : {src}")
    return candidate, "fichier"


def audit_documents(
    documents: dict[str, Document],
    site_root: Path,
    vision: dict[str, Any] | None,
    base_url: str | None = None,
    limit: int = 4,
) -> dict[str, Any]:
    """Analyse les images des pages fournies. Retourne constats, images vues, état du modèle."""
    config = vision or {}
    report: dict[str, Any] = {
        "available": bool(config.get("base_url") and config.get("model")),
        "model": config.get("model", ""),
        "images": [],
        "findings": [],
        "skipped": [],
    }
    if not report["available"]:
        report["reason"] = "aucun modèle vision configuré"
        return report

    seen = 0
    for page, document in documents.items():
        for node in select(document.root, "img"):
            if seen >= limit:
                return report
            seen += 1
            src = node.get("src", "")
            alt = node.attrs.get("alt")
            selector = selector_for_image(node)
            if node.get("role") == "presentation" or node.get("aria-hidden") == "true":
                report["images"].append(
                    {
                        "page": page,
                        "selector": selector,
                        "src": src,
                        "alt": alt,
                        "origin": "déclarée décorative",
                        "description": "",
                        "contains_text": None,
                        "kind": "",
                        "available": True,
                        "verdict": "décorative déclarée",
                    }
                )
                continue
            try:
                target, origin = _resolve_target(src, site_root, base_url)
            except Exception as exc:  # noqa: BLE001 - image inaccessible : on le note, on ne bloque pas
                report["skipped"].append({"page": page, "selector": selector, "src": src, "reason": str(exc)})
                continue
            analysis = analyse_image(
                target,
                config.get("base_url"),
                config.get("model"),
                api_key=config.get("api_key"),
                timeout=int(config.get("timeout", 240)),
            )
            analysis["src"] = src
            verdict = classify(alt, analysis)
            row = {
                "page": page,
                "selector": selector,
                "src": src,
                "alt": alt,
                "origin": origin,
                "description": analysis.get("description", ""),
                "brut": analysis.get("brut", ""),
                "usable": analysis.get("usable"),
                "reason": analysis.get("reason") or analysis.get("source", ""),
                "ms": analysis.get("ms"),
                "contains_text": analysis.get("contains_text"),
                "kind": analysis.get("kind", ""),
                "available": analysis.get("available", False),
                "verdict": verdict["rule"] if verdict else "conforme",
            }
            report["images"].append(row)
            if verdict:
                report["findings"].append(
                    {
                        "page": page,
                        "selector": selector,
                        "src": src,
                        "alt": alt,
                        "rule": verdict["rule"],
                        "label": RULES[verdict["rule"]][0],
                        "rgpa": RULES[verdict["rule"]][1],
                        "severity": verdict["severity"],
                        "message": verdict["message"],
                        "proposed_alt": verdict["proposed_alt"],
                        "description": analysis.get("description", ""),
                "brut": analysis.get("brut", ""),
                "usable": analysis.get("usable"),
                "reason": analysis.get("reason") or analysis.get("source", ""),
                "ms": analysis.get("ms"),
                    }
                )
    return report


def apply_to_documents(documents: dict[str, Document], findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Applique les alternatives proposées par le modèle, et journalise chaque patch."""
    patches: list[dict[str, Any]] = []
    for finding in findings:
        document = documents.get(finding["page"])
        if document is None:
            continue
        proposed = str(finding.get("proposed_alt") or "").strip()
        if not proposed:
            continue
        try:
            result = apply_patch(document, finding["selector"], "set_attr", name="alt", value=proposed)
        except Exception:  # noqa: BLE001 - sélecteur obsolète : on passe au suivant
            continue
        patches.append(
            {
                "page": finding["page"],
                "selector": finding["selector"],
                "op": f'alt vision = "{proposed}"',
                "before": result["before"],
                "after": result["after"],
                "review": False,
                "source": "vision",
                "rule": finding["rule"],
            }
        )
    return patches


def reload_documents(site_root: Path, pages: list[str]) -> dict[str, Document]:
    return {name: parse((Path(site_root) / name).read_text(encoding="utf-8")) for name in pages}
