# Image de démonstration : aucune dépendance Python, aucun réseau requis.
FROM python:3.12-slim

# Ollama embarqué, désactivé par défaut : la même image sert aux deux usages.
#   docker build --build-arg INSTALL_OLLAMA=1 .
# Puis RGAA_EMBEDDED_OLLAMA=1 pour le démarrer, ou l'activer depuis les paramètres.
ARG INSTALL_OLLAMA=0
ARG BUILD_SHA=dev

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RGAA_RUNS=/var/lib/rgaa/runs \
    RGAA_DATA=/var/lib/rgaa \
    RGAA_IN_CONTAINER=1 \
    RGAA_OLLAMA_URL=http://127.0.0.1:11434 \
    RGAA_EMBEDDED_OLLAMA=0 \
    OLLAMA_MODELS=/var/lib/rgaa/ollama \
    RGAA_BUILD=${BUILD_SHA}

WORKDIR /app

# Utilisateur non-root aligné sur l'utilisateur applicatif TrueNAS SCALE (568:568),
# pour que les fichiers écrits restent lisibles depuis l'hôte sans chmod.
RUN groupadd --gid 568 app \
 && useradd --uid 568 --gid 568 --home-dir /app --shell /usr/sbin/nologin app \
 && mkdir -p /var/lib/rgaa/ollama \
 && chown -R 568:568 /app /var/lib/rgaa

# Ollama optionnel : binaire officiel, sans service systemd et sans GPU obligatoire.
RUN if [ "$INSTALL_OLLAMA" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends curl ca-certificates zstd \
      && ARCH="$(dpkg --print-architecture)" \
      && curl -fsSL "https://github.com/ollama/ollama/releases/latest/download/ollama-linux-${ARCH}.tar.zst" -o /tmp/ollama.tar.zst \
      && tar --zstd -C /usr/local -xf /tmp/ollama.tar.zst \
      && rm -f /tmp/ollama.tar.zst && rm -rf /var/lib/apt/lists/* \
      && /usr/local/bin/ollama --version ; \
    fi

# Navigateur optionnel : Chromium et Xvfb, pour le passage rendu.
# Headless fonctionne sans écran, headful passe par xvfb-run dans le conteneur.
ARG INSTALL_BROWSER=0
RUN if [ "$INSTALL_BROWSER" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends \
        chromium xvfb xauth fonts-liberation fonts-dejavu-core ca-certificates \
      && rm -rf /var/lib/apt/lists/* ; \
    fi

ENV RGAA_CHROME=/usr/bin/chromium

COPY --chown=568:568 . /app

RUN chmod +x /app/entrypoint.sh

USER 568:568

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"

# Aucune configuration, aucun secret, aucun socket Docker.
# Un seul volume inscriptible : /var/lib/rgaa (runs, pages corrigées, journal, modèles).
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "-m", "rgaa", "serve", "--host", "0.0.0.0", "--port", "8080"]
