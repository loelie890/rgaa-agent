"""Campagnes d'audit : création, modification, suppression.

Une campagne est un objectif nommé, avec un budget, une source de pages et un
moteur. Deux moteurs :

* ``auto`` : corrections déterministes, sans modèle, sur un jeu de pages ;
* ``cassette`` : décisions enregistrées, rejouables à l'identique.

Les campagnes livrées avec le dépôt servent de démonstration ; celles créées
depuis l'interface utilisent le moteur ``auto`` pour être exécutables tout de suite.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from .kernel import CAMPAGNE_DIR, normalize

FIELDS = {"title": 80, "objective": 400, "budget": 4}


class CampaignError(Exception):
    pass


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", normalize(title)).strip("-")
    return slug[:48] or "campagne"


def folder(slug: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", slug or ""):
        raise CampaignError(f"identifiant invalide : {slug!r}")
    return Path(CAMPAGNE_DIR) / slug


def load(slug: str) -> dict[str, Any]:
    path = folder(slug) / "campagne.json"
    if not path.is_file():
        raise CampaignError(f"campagne inconnue : {slug}")
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("slug", slug)
    data.setdefault("engine", "cassette")
    return data


def create(
    title: str,
    objective: str,
    *,
    budget: int = 24,
    engine: str = "auto",
    pages: str = "site",
    slug: str | None = None,
) -> dict[str, Any]:
    title = (title or "").strip()
    objective = (objective or "").strip()
    if len(title) < 3:
        raise CampaignError("titre trop court (3 caractères minimum)")
    if len(objective) < 10:
        raise CampaignError("objectif trop court (10 caractères minimum)")
    if engine not in {"auto", "cassette"}:
        raise CampaignError("moteur inconnu : auto ou cassette")
    ident = slug or slugify(title)
    target = folder(ident)
    if target.exists():
        raise CampaignError(f"une campagne utilise déjà l'identifiant « {ident} »")

    payload = {
        "slug": ident,
        "title": title[:80],
        "objective": objective[:400],
        "as_of": None,
        "budget": max(4, min(int(budget), 60)),
        "engine": engine,
        "pages": pages if re.fullmatch(r"[a-z0-9-]{1,32}", pages or "") else "site",
    }
    if engine == "cassette":
        raise CampaignError("une campagne en cassette doit être écrite à la main dans campagnes/")
    target.mkdir(parents=True)
    (target / "campagne.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def update(slug: str, **changes: Any) -> dict[str, Any]:
    data = load(slug)
    if "engine" in changes:
        changes.pop("engine")  # changer de moteur casserait la traçabilité
    for key in ("title", "objective", "budget", "pages"):
        if key in changes and changes[key] is not None:
            value = changes[key]
            if key == "budget":
                data["budget"] = max(4, min(int(value), 60))
            elif key == "title":
                value = str(value).strip()
                if len(value) < 3:
                    raise CampaignError("titre trop court")
                data["title"] = value[:80]
            elif key == "objective":
                value = str(value).strip()
                if len(value) < 10:
                    raise CampaignError("objectif trop court")
                data["objective"] = value[:400]
            elif key == "pages" and re.fullmatch(r"[a-z0-9-]{1,32}", str(value)):
                data["pages"] = str(value)
    path = folder(slug) / "campagne.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def delete(slug: str) -> dict[str, Any]:
    target = folder(slug)
    if not target.is_dir():
        raise CampaignError(f"campagne inconnue : {slug}")
    data = load(slug)
    if data.get("engine") != "auto":
        raise CampaignError("les campagnes de démonstration ne sont pas supprimables depuis l'interface")
    shutil.rmtree(target)
    return {"deleted": slug}


def site_path(slug: str) -> Path:
    data = load(slug)
    from .kernel import ROOT

    return Path(ROOT) / "fixtures" / str(data.get("pages") or "site")
