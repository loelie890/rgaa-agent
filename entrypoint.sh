#!/bin/sh
# Démarrage : Ollama embarqué, uniquement s'il est présent et demandé.
set -e

if [ "${RGAA_EMBEDDED_OLLAMA:-0}" = "1" ] && command -v ollama >/dev/null 2>&1; then
    if ! curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        echo "[entrypoint] démarrage d'Ollama embarqué"
        OLLAMA_HOST=127.0.0.1:11434 OLLAMA_MODELS="${OLLAMA_MODELS:-/var/lib/rgaa/ollama}" ollama serve >/var/lib/rgaa/ollama.log 2>&1 &
        i=0
        while [ $i -lt 30 ]; do
            curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
            i=$((i + 1))
            sleep 1
        done
    fi
fi

# La démo sur son port historique, pour les déploiements qui publient déjà 8090.
# RGAA_DEMO_PORT=0 la désactive (la démo reste disponible sur /demo du serveur principal).
if [ "${RGAA_DEMO_PORT:-8090}" != "0" ]; then
    python -m rgaa demo --host 0.0.0.0 --port "${RGAA_DEMO_PORT:-8090}" >>/var/lib/rgaa/demo.log 2>&1 &
    echo "[entrypoint] démo sur 0.0.0.0:${RGAA_DEMO_PORT:-8090}"
fi

exec "$@"
