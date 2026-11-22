"""Dimensionnement : ce qui tient dans une carte, calculé et pas souhaité.

Le produit utilise un modèle vision pour trancher trois constats qu'aucune règle
ne peut trancher : image décorative ou informative, alternative générique, texte
porté par l'image. Ce module dit, pour une mémoire donnée, quels modèles tiennent
et combien d'images un audit peut réellement traiter.

Le calcul est volontairement simple et affiché : poids des paramètres selon la
quantification, cache d'attention proportionnel au contexte, et une réserve de
runtime. Un relecteur peut refaire la division.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

RUNTIME_GO = 1.2  # bibliothèque de calcul, allocateurs, tampons d'image
KV_PAR_7B_8K = 0.5  # Go de cache d'attention pour 7 milliards de paramètres à 8192 jetons

# (nom, milliards de paramètres, octets par paramètre, palier d'usage)
MODELS: tuple[tuple[str, float, float, str], ...] = (
    ("qwen2.5vl:3b", 3.0, 0.58, "Q4, lecture d'image simple"),
    ("llava:7b", 7.0, 0.58, "Q4, description courte"),
    ("qwen2.5vl:7b", 7.0, 0.58, "Q4, texte dans l'image"),
    ("minicpm-v:8b", 8.0, 0.58, "Q4, images denses en texte"),
    ("qwen2.5vl:32b", 32.0, 0.58, "Q4, arbitrage fin sur image ambiguë"),
    ("llama3.2-vision:90b", 90.0, 0.58, "Q4, hors de portée d'une carte unique"),
)


def images_in_fixtures(root: str | Path | None = None) -> int:
    base = Path(root) if root else Path(__file__).resolve().parent.parent / "fixtures"
    if not base.is_dir():
        return 0
    return sum(1 for path in base.rglob("*") if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"})


def needs(name: str, params_b: float, bytes_per_param: float, context: int = 8192) -> dict[str, float]:
    weights = round(params_b * bytes_per_param, 2)
    kv = round(KV_PAR_7B_8K * (params_b / 7.0) * (context / 8192.0), 2)
    total = round(weights + kv + RUNTIME_GO, 2)
    return {"poids": weights, "cache": kv, "runtime": RUNTIME_GO, "total": total}


def fit(
    vram_gb: float = 32.0,
    vram_actuelle: float = 4.0,
    context: int = 8192,
    images: int | None = None,
    seconds_per_image: float = 4.0,
) -> dict[str, Any]:
    images = images_in_fixtures() if images is None else int(images)
    rows = []
    for name, params_b, quant, note in MODELS:
        need = needs(name, params_b, quant, context)
        rows.append(
            {
                "model": name,
                "params_b": params_b,
                "quant": "Q4",
                "note": note,
                **need,
                "tient_maintenant": need["total"] <= vram_actuelle,
                "tient_cible": need["total"] <= vram_gb,
            }
        )
    tiennent_maintenant = [row for row in rows if row["tient_maintenant"]]
    tiennent_cible = [row for row in rows if row["tient_cible"]]
    return {
        "hypotheses": {
            "vram_actuelle_go": vram_actuelle,
            "vram_cible_go": vram_gb,
            "contexte_jetons": context,
            "images_par_audit": images,
            "secondes_par_image": seconds_per_image,
            "runtime_go": RUNTIME_GO,
            "cache_7b_8k_go": KV_PAR_7B_8K,
            "quantification": "Q4_K_M, 0,58 Go par milliard de paramètres",
        },
        "models": rows,
        "tiennent_maintenant": [row["model"] for row in tiennent_maintenant],
        "tiennent_cible": [row["model"] for row in tiennent_cible],
        "images_traitees_maintenant": 0 if not tiennent_maintenant else images,
        "images_traitees_cible": 0 if not tiennent_cible else images,
        "minutes_maintenant": round(0 if not tiennent_maintenant else images * seconds_per_image / 60, 1),
        "minutes_cible": round(0 if not tiennent_cible else images * seconds_per_image / 60, 1),
    }


def render_text(data: dict[str, Any] | None = None) -> str:
    data = data or fit()
    hyp = data["hypotheses"]
    lines = [
        "Hypothèses",
        f"  mémoire aujourd'hui        : {hyp['vram_actuelle_go']} Go",
        f"  mémoire visée              : {hyp['vram_cible_go']} Go",
        f"  contexte                   : {hyp['contexte_jetons']} jetons",
        f"  images par audit           : {hyp['images_par_audit']} (fixtures du dépôt)",
        f"  seconde par image          : {hyp['secondes_par_image']}",
        f"  quantification             : {hyp['quantification']}",
        f"  réserve runtime            : {hyp['runtime_go']} Go",
        f"  cache d'attention          : {hyp['cache_7b_8k_go']} Go pour 7 B à 8192 jetons",
        "",
        f"{'modèle':22} {'poids':>7} {'cache':>7} {'total':>7}  {'maintenant':>10} {'cible':>7}",
    ]
    for row in data["models"]:
        lines.append(
            f"{row['model'][:22]:22} {row['poids']:>7} {row['cache']:>7} {row['total']:>7}"
            f"  {'tient' if row['tient_maintenant'] else 'non':>10}"
            f"  {'tient' if row['tient_cible'] else 'non':>7}"
        )
    lines.append("")
    if data["tiennent_maintenant"]:
        lines.append(
            f"Aujourd'hui, {len(data['tiennent_maintenant'])} modèle(s) tiennent : "
            f"{data['images_traitees_maintenant']} image(s), environ {data['minutes_maintenant']} min par audit."
        )
    else:
        lines.append(
            "Aujourd'hui, aucun modèle vision ne tient : la passe vision reste un contrat "
            "d'interface, pas un service rendu."
        )
    lines.append(
        f"Sur {hyp['vram_cible_go']} Go, {len(data['tiennent_cible'])} modèle(s) tiennent : "
        f"{data['images_traitees_cible']} image(s) en une passe, environ {data['minutes_cible']} min par audit."
    )
    return "\n".join(lines)
