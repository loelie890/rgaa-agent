"""Feuilles de style minimales : cascade, couleurs effectives, contraste WCAG.

Suffisant pour le critère RGAA 3.2 sur un site statique : blocs ``<style>``,
sélecteurs simples, héritage de la couleur et du fond, priorité au style en
ligne. Ce n'est pas un moteur CSS complet (pas de ``@media``, pas de variables,
pas de calcul de spécificité exotique), et c'est dit dans le README.
"""

from __future__ import annotations

import re
from typing import Any

from .dom import Document, Node, select

_HEX = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RGB = re.compile(r"^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)")
_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_BLOCK = re.compile(r"([^{}]+)\{([^{}]*)\}", re.S)
_TAG = re.compile(r"(^|[\s>+~])[a-zA-Z][\w-]*")

STYLE_KEYS = ("color", "background-color", "background", "font-size", "font-weight")


def parse_color(value: str) -> tuple[int, int, int] | None:
    value = (value or "").strip().lower()
    if _HEX.match(value):
        digits = value[1:]
        if len(digits) == 3:
            digits = "".join(c * 2 for c in digits)
        return tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    match = _RGB.match(value)
    if match:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


def to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*[max(0, min(255, round(c))) for c in rgb])


def luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: float) -> float:
        ratio = value / 255
        return ratio / 12.92 if ratio <= 0.03928 else ((ratio + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(component) for component in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground: tuple[int, int, int], background: tuple[int, int, int]) -> float:
    first, second = luminance(foreground), luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def threshold_for(font_size_px: float, bold: bool) -> float:
    large = font_size_px >= 24 or (bold and font_size_px >= 18.66)
    return 3.0 if large else 4.5


def propose_compliant(color: str, background: str, target: float = 4.5) -> dict[str, Any]:
    """Teinte la plus proche qui atteint le seuil, en conservant la teinte d'origine.

    On éclaircit ou on fonce par paliers de 2 % : la teinte et la saturation
    restent reconnaissables, seul le niveau change. Retourne aussi le ratio
    obtenu, pour que l'appelant vérifie au lieu de croire.
    """
    foreground = parse_color(color)
    backdrop = parse_color(background)
    if not foreground or not backdrop:
        raise ValueError(f"couleur illisible : {color!r} / {background!r}")
    start = contrast_ratio(foreground, backdrop)
    if start >= target:
        return {"color": to_hex(foreground), "ratio": round(start, 2), "changed": False, "target": target}

    darken = luminance(backdrop) > 0.35
    best: tuple[float, tuple[int, int, int]] | None = None
    for step in range(1, 101):
        factor = 1 - step / 100 if darken else 1 + step / 100
        candidate = tuple(min(255, max(0, round(component * factor))) for component in foreground)
        ratio = contrast_ratio(candidate, backdrop)  # type: ignore[arg-type]
        if ratio >= target:
            best = (ratio, candidate)  # type: ignore[assignment]
            break
    if best is None:
        extreme = (0, 0, 0) if darken else (255, 255, 255)
        best = (contrast_ratio(extreme, backdrop), extreme)
    return {
        "color": to_hex(best[1]),
        "ratio": round(best[0], 2),
        "changed": True,
        "target": target,
        "original": to_hex(foreground),
        "original_ratio": round(start, 2),
    }


def _parse_declarations(text: str) -> dict[str, str]:
    declarations: dict[str, str] = {}
    for chunk in text.split(";"):
        if ":" in chunk:
            key, _, value = chunk.partition(":")
            key = key.strip().lower()
            if key in STYLE_KEYS:
                declarations[key] = value.strip()
    return declarations


def specificity(selector: str) -> int:
    ids = selector.count("#")
    classes = selector.count(".") + selector.count("[") + len(re.findall(r":[a-zA-Z-]+", selector))
    tags = len(_TAG.findall(selector))
    return ids * 100 + classes * 10 + tags


def parse_stylesheets(doc: Document) -> list[tuple[str, dict[str, str], int]]:
    """Règles des blocs ``<style>``, dans l'ordre du document."""
    rules: list[tuple[str, dict[str, str], int]] = []
    for style in select(doc.root, "style"):
        text = _COMMENT.sub("", style.text())
        for block in _BLOCK.finditer(text):
            selector_text = block.group(1).strip()
            if not selector_text or selector_text.startswith("@"):
                continue
            declarations = _parse_declarations(block.group(2))
            if not declarations:
                continue
            for single in selector_text.split(","):
                single = single.strip()
                if single and not single.startswith("@"):
                    rules.append((single, declarations, specificity(single)))
    return rules


def _matched_declarations(
    doc: Document, node: Node, rules: list[tuple[str, dict[str, str], int]]
) -> dict[str, str]:
    best_specificity = -1
    declarations: dict[str, str] = {}
    for selector, decls, weight in rules:
        try:
            matched = select(doc.root, selector)
        except Exception:  # noqa: BLE001 - sélecteur non supporté : ignoré, pas fatal
            continue
        if any(candidate is node for candidate in matched):
            if weight > best_specificity:
                best_specificity = weight
                declarations = dict(decls)
            elif weight == best_specificity:
                declarations.update(decls)
    inline = _parse_declarations(node.get("style"))
    declarations.update(inline)
    return declarations


def resolve_text_style(
    doc: Document, node: Node, rules: list[tuple[str, dict[str, str], int]] | None = None
) -> dict[str, Any]:
    """Couleur du texte, fond réel (hérité des ancêtres), taille et graisse."""
    if rules is None:
        rules = parse_stylesheets(doc)
    color: str | None = None
    background: str | None = None
    size = 16.0
    bold = False

    current: Node | None = node
    while current is not None:
        declarations = _matched_declarations(doc, current, rules)
        if color is None and "color" in declarations:
            color = declarations["color"]
        if background is None:
            background = declarations.get("background-color") or (
                declarations["background"] if "background" in declarations and parse_color(declarations["background"]) else None
            )
        if current is node:
            raw_size = declarations.get("font-size", "")
            if raw_size.endswith("px") and raw_size[:-2].replace(".", "", 1).isdigit():
                size = float(raw_size[:-2])
            bold = declarations.get("font-weight", "") in {"bold", "700", "800", "900"}
        current = current.parent

    return {
        "color": color or "#000000",
        "background": background or "#ffffff",
        "font_size": size,
        "bold": bold,
        "source": "inline" if "color" in _parse_declarations(node.get("style")) else "feuille" if color else "défaut",
    }


def has_direct_text(node: Node) -> bool:
    return any(child.tag == "#text" and child.data.strip() for child in node.children)
