"""Comparaison de coût : agent local contre API cloud, avec des chiffres reproductibles.

Aucun prix n'est inventé : les tarifs sont des arguments, les jetons par étape
aussi. Le calcul, lui, est exact, et la consommation locale est dérivée du temps
CPU mesuré par le moteur.

    python -m rgaa cost --price-in 0.15 --price-out 0.60
"""

from __future__ import annotations

from typing import Any


def compare(
    *,
    steps: int = 24,
    tokens_in: int = 1000,
    tokens_out: int = 80,
    price_in: float = 0.15,
    price_out: float = 0.60,
    seconds_per_audit: float = 0.45,
    watts: float = 65.0,
    kwh_price: float = 0.25,
    audits: int = 1000,
) -> dict[str, Any]:
    """Coût par audit, côté cloud (jetons) et côté local (électricité seule)."""
    cloud_tokens_in = steps * tokens_in
    cloud_tokens_out = steps * tokens_out
    cloud_per_audit = (cloud_tokens_in / 1_000_000) * price_in + (cloud_tokens_out / 1_000_000) * price_out

    local_kwh = watts * seconds_per_audit / 3600 / 1000
    local_per_audit = local_kwh * kwh_price

    return {
        "hypotheses": {
            "etapes_par_audit": steps,
            "jetons_entree_par_etape": tokens_in,
            "jetons_sortie_par_etape": tokens_out,
            "prix_entree_par_million": price_in,
            "prix_sortie_par_million": price_out,
            "secondes_par_audit": seconds_per_audit,
            "puissance_watts": watts,
            "prix_kwh": kwh_price,
        },
        "cloud": {
            "jetons_entree": cloud_tokens_in,
            "jetons_sortie": cloud_tokens_out,
            "par_audit": round(cloud_per_audit, 6),
            "pour_100": round(cloud_per_audit * 100, 4),
            "pour_1000": round(cloud_per_audit * 1000, 3),
        },
        "local": {
            "kwh_par_audit": round(local_kwh, 9),
            "par_audit": round(local_per_audit, 9),
            "pour_100": round(local_per_audit * 100, 6),
            "pour_1000": round(local_per_audit * 1000, 6),
        },
        "ratio": round(cloud_per_audit / local_per_audit, 1) if local_per_audit else None,
        "avertissement": (
            "Le coût local ne compte que l'électricité. Il ignore l'achat de la machine, "
            "son renouvellement et le temps d'installation, et il suppose un petit modèle local "
            "ou le mode replay. Une comparaison honnête ajoute l'amortissement du matériel."
        ),
    }


def render(result: dict[str, Any]) -> str:
    hyp = result["hypotheses"]
    cloud, local = result["cloud"], result["local"]
    lines = [
        "Comparaison de coût, hypothèses affichées et modifiables",
        "",
        f"  {hyp['etapes_par_audit']} étapes par audit, {hyp['jetons_entree_par_etape']} jetons en entrée "
        f"et {hyp['jetons_sortie_par_etape']} en sortie par étape",
        f"  prix cloud : {hyp['prix_entree_par_million']} / million en entrée, "
        f"{hyp['prix_sortie_par_million']} / million en sortie",
        f"  local : {hyp['secondes_par_audit']} s à {hyp['puissance_watts']} W, "
        f"{hyp['prix_kwh']} par kWh",
        "",
        f"  jetons par audit        : {cloud['jetons_entree']} en entrée, {cloud['jetons_sortie']} en sortie",
        f"  cloud, par audit        : {cloud['par_audit']:.4f}",
        f"  cloud, 1 000 audits     : {cloud['pour_1000']:.2f}",
        f"  local, par audit        : {local['par_audit']:.7f}",
        f"  local, 1 000 audits     : {local['pour_1000']:.4f}",
        f"  rapport                 : x{result['ratio']}" if result["ratio"] else "",
        "",
        f"  {result['avertissement']}",
    ]
    return "\n".join(line for line in lines if line)
