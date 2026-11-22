"""Serveur MCP : poignée de main, catalogue d'outils, appels réels.

Le transport est testé en mémoire (une requête, une réponse) ; le protocole est
vérifié sur les trois méthodes qui comptent pour un client : initialize,
tools/list et tools/call.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from rgaa import mcp
from rgaa.kernel import ROOT


class TestProtocole(unittest.TestCase):
    def test_initialize(self) -> None:
        response = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert response is not None
        self.assertEqual(response["result"]["protocolVersion"], mcp.PROTOCOL_VERSION)
        self.assertEqual(response["result"]["serverInfo"]["name"], "rgaa-agent")
        self.assertIn("tools", response["result"]["capabilities"])

    def test_notification_sans_reponse(self) -> None:
        self.assertIsNone(mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_tools_list(self) -> None:
        response = mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert response is not None
        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertEqual(names, {"coverage", "audit_site", "render_page", "list_campaigns", "run_campaign"})
        for tool in response["result"]["tools"]:
            self.assertEqual(tool["inputSchema"]["type"], "object")
            self.assertTrue(tool["description"])

    def test_methode_inconnue(self) -> None:
        response = mcp.handle({"jsonrpc": "2.0", "id": 3, "method": "nope"})
        assert response is not None
        self.assertEqual(response["error"]["code"], -32601)

    def test_pas_de_method(self) -> None:
        response = mcp.handle({"jsonrpc": "2.0", "id": 4})
        assert response is not None
        self.assertEqual(response["error"]["code"], -32600)

    def test_outil_inconnu(self) -> None:
        response = mcp.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                               "params": {"name": "rm_rf", "arguments": {}}})
        assert response is not None
        self.assertTrue(response["result"]["isError"])


class TestOutils(unittest.TestCase):
    def test_coverage(self) -> None:
        response = mcp.handle({"jsonrpc": "2.0", "id": 10, "method": "tools/call",
                               "params": {"name": "coverage", "arguments": {}}})
        assert response is not None
        text = response["result"]["content"][0]["text"]
        self.assertIn("106 critères", text)
        self.assertFalse(response["result"]["isError"])

    def test_list_campagnes(self) -> None:
        response = mcp.handle({"jsonrpc": "2.0", "id": 11, "method": "tools/call",
                               "params": {"name": "list_campaigns", "arguments": {}}})
        assert response is not None
        text = response["result"]["content"][0]["text"]
        self.assertIn("conformite", text)

    def test_audit_site_sur_copie(self) -> None:
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            site = Path(tmp) / "site"
            shutil.copytree(Path(ROOT) / "fixtures" / "site", site)
            response = mcp.handle({"jsonrpc": "2.0", "id": 12, "method": "tools/call",
                                   "params": {"name": "audit_site",
                                              "arguments": {"path": str(site), "write": True}}})
            assert response is not None
            text = response["result"]["content"][0]["text"]
            self.assertIn("Corrections", text)
            self.assertIn("100.0 %", text)
            self.assertIn("alt=", (site / "index.html").read_text(encoding="utf-8"))

    def test_chemin_absent(self) -> None:
        response = mcp.handle({"jsonrpc": "2.0", "id": 13, "method": "tools/call",
                               "params": {"name": "audit_site", "arguments": {"path": "/nope/ici"}}})
        assert response is not None
        self.assertTrue(response["result"]["isError"])

    def test_render_sans_navigateur(self) -> None:
        response = mcp.handle({"jsonrpc": "2.0", "id": 14, "method": "tools/call",
                               "params": {"name": "render_page",
                                          "arguments": {"path": "fixtures/site/index.html"}}})
        assert response is not None
        text = response["result"]["content"][0]["text"]
        self.assertTrue(response["result"]["isError"] or "constat" in text)


class TestTransport(unittest.TestCase):
    def test_boucle_stdio(self) -> None:
        payload = "\n".join(
            [
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
                "",
            ]
        )
        source = io.StringIO(payload)
        sink = io.StringIO()
        self.assertEqual(mcp.serve(source, sink), 0)
        lines = [json.loads(line) for line in sink.getvalue().strip().splitlines()]
        self.assertEqual(len(lines), 2)  # la notification ne répond pas
        self.assertEqual(lines[0]["id"], 1)
        self.assertEqual(len(lines[1]["result"]["tools"]), 5)

    def test_json_invalide(self) -> None:
        sink = io.StringIO()
        mcp.serve(io.StringIO("{pas du json}\n"), sink)
        self.assertEqual(json.loads(sink.getvalue())["error"]["code"], -32700)


if __name__ == "__main__":
    unittest.main()
