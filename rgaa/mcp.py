"""Serveur MCP : les outils de l'agent exposés à un client qui parle MCP.

Transport stdio, JSON-RPC 2.0, une requête par ligne. Aucune dépendance : le
protocole tient dans ce fichier, et un client comme Claude Desktop, Cline ou un
agent maison peut appeler l'audit sans installer quoi que ce soit.

Trois méthodes suffisent à être utile : `initialize`, `tools/list`, `tools/call`.
Tout le reste est un appel d'outil, avec les mêmes fonctions que la CLI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SERVER_NAME = "rgaa-agent"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2025-06-18"

TOOLS: list[dict[str, Any]] = [
    {
        "name": "coverage",
        "description": "Les 106 critères RGAA 4.1 et le statut de chacun : corrigé, détecté, ou humain.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "audit_site",
        "description": "Audite un dossier HTML, applique les corrections déterministes et renvoie le score avant et après.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "dossier ou fichier HTML à auditer"},
                "write": {"type": "boolean", "description": "écrire les corrections sur place", "default": False},
                "min_score": {"type": "number", "description": "seuil exigé, 100 par défaut", "default": 100},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "render_page",
        "description": "Ouvre une page dans Chromium (headless ou headful) et renvoie les constats mesurés sur le DOM rendu.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "fichier HTML local"},
                "url": {"type": "string", "description": "adresse http(s) de la page"},
                "mode": {"type": "string", "enum": ["headless", "headful"], "default": "headless"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "list_campaigns",
        "description": "Liste les campagnes d'audit disponibles, avec leur budget et leur moteur.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "run_campaign",
        "description": "Rejoue une campagne enregistrée et renvoie le résultat final.",
        "inputSchema": {
            "type": "object",
            "properties": {"slug": {"type": "string", "description": "identifiant de la campagne"}},
            "required": ["slug"],
            "additionalProperties": False,
        },
    },
]


def _text(payload: str, error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": payload}], "isError": error}


def _call_coverage(_: dict[str, Any]) -> dict[str, Any]:
    from .coverage import matrix, render_text

    data = matrix()
    return _text(render_text(data) + "\n\n" + json.dumps({"counts": data["counts"], "share": data["share"]}, ensure_ascii=False))


def _call_audit(args: dict[str, Any]) -> dict[str, Any]:
    from .ci import run_ci

    target = Path(str(args.get("path") or "."))
    if not target.exists():
        return _text(f"chemin introuvable : {target}", error=True)
    site = target if target.is_dir() else target.parent
    result = run_ci(site, min_score=float(args.get("min_score") or 100.0), write=bool(args.get("write")))
    lines = [
        f"Avant : {result['baseline']['percent']} % ({result['baseline']['violations']} violation(s))",
        f"Après : {result['score']['percent']} % ({result['score']['violations']} violation(s))",
        f"Corrections : {len(result['patches'])}, dont {len(result['review'])} à relire",
        f"Seuil : {'atteint' if result['passed'] else 'non atteint'}",
    ]
    for row in result["patches"][:10]:
        lines.append(f"  {row['page']} {row['selector']} : {row['op']}")
    return _text("\n".join(lines))


def _call_render(args: dict[str, Any]) -> dict[str, Any]:
    from . import browser, browser_audit

    try:
        rendered = browser.render(
            url=args.get("url") or None,
            path=args.get("path") or None,
            mode=args.get("mode") or "headless",
        )
    except browser.BrowserError as exc:
        return _text(f"navigateur indisponible : {exc}", error=True)
    result = browser_audit.analyse(rendered.report, str(args.get("url") or args.get("path") or "page"))
    lines = [f"{browser_audit.summary(result)} · {rendered.mode}, {rendered.ms} ms"]
    for row in result["findings"][:15]:
        lines.append(f"  {row['criterion']:<5} {row['severity']:<9} {row['selector'][:40]} {row['message'][:80]}")
    return _text("\n".join(lines))


def _call_list(_: dict[str, Any]) -> dict[str, Any]:
    from .kernel import list_campagnes

    rows = list_campagnes()
    lines = [f"{row['slug']:16} budget {row['budget']:>3} · moteur {row.get('engine', 'cassette')} · {row['title']}" for row in rows]
    return _text("\n".join(lines) or "aucune campagne")


def _call_run(args: dict[str, Any]) -> dict[str, Any]:
    from .kernel import run_campagne

    slug = str(args.get("slug") or "")
    if not slug:
        return _text("slug requis", error=True)
    try:
        result = run_campagne(slug)
    except FileNotFoundError as exc:
        return _text(str(exc), error=True)
    return _text(f"{result['title']}\n{result['final']}\n{result['errors']} erreur(s), {len(result['artifacts'])} artefact(s)")


HANDLERS = {
    "coverage": _call_coverage,
    "audit_site": _call_audit,
    "render_page": _call_render,
    "list_campaigns": _call_list,
    "run_campaign": _call_run,
}


def _ok(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle(request: dict[str, Any]) -> dict[str, Any] | None:
    """Traite une requête JSON-RPC. Retourne None pour une notification."""
    method = request.get("method") or ""
    request_id = request.get("id")

    if method == "initialize":
        return _ok(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None
    if method == "ping":
        return _ok(request_id, {})
    if method == "tools/list":
        return _ok(request_id, {"tools": TOOLS})
    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        handler = HANDLERS.get(str(name))
        if not handler:
            return _ok(request_id, _text(f"outil inconnu : {name}", error=True))
        try:
            return _ok(request_id, handler(params.get("arguments") or {}))
        except Exception as exc:  # noqa: BLE001 - un outil qui casse ne tue pas le serveur
            return _ok(request_id, _text(f"{type(exc).__name__}: {exc}", error=True))
    if not method:
        return _error(request_id, -32600, "requête sans méthode")
    return _error(request_id, -32601, f"méthode inconnue : {method}")


def serve(stream_in=None, stream_out=None) -> int:
    """Boucle stdio : une ligne JSON par message, réponse sur la sortie standard."""
    source = stream_in or sys.stdin
    sink = stream_out or sys.stdout
    for line in source:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            sink.write(json.dumps(_error(None, -32700, "JSON invalide")) + "\n")
            sink.flush()
            continue
        response = handle(request)
        if response is not None:
            sink.write(json.dumps(response, ensure_ascii=False) + "\n")
            sink.flush()
    return 0
