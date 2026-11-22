#!/usr/bin/env python3
"""Faux serveur vision pour vérifier la passe d'audit sans GPU ni modèle.

Répond au format attendu par rgaa/vision.py : une description, la présence de
texte, un type. Sert uniquement aux vérifications locales et aux tests.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        return

    def do_GET(self):  # noqa: N802
        body = json.dumps({"data": [{"id": "fake-vl"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        answer = "DESCRIPTION: Une trottinette rouge pliée devant une vitrine\nTEXTE: non\nTYPE: photo"
        body = json.dumps({"choices": [{"message": {"content": answer}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8095
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
