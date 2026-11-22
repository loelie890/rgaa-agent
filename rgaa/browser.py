"""Rendu réel dans Chromium, sans dépendance.

Le HTML d'un fichier n'est pas la page : JavaScript ajoute des éléments, les
feuilles externes décident des couleurs, et le contraste se mesure sur le style
calculé, pas sur l'attribut `style`. Ce module ouvre donc la page dans Chrome
(headless par défaut, headful sur demande), laisse le moteur faire son travail,
puis récupère le DOM rendu et un rapport calculé par un script injecté.

Aucune bibliothèque : on parle à Chrome par ses propres options de ligne de
commande (`--dump-dom`), qui exécutent la page et renvoient le DOM vivant.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MARKER = "rgaa-browser-report"

CANDIDATES = (
    "google-chrome-stable",
    "google-chrome",
    "chromium",
    "chromium-browser",
    "chrome",
    "microsoft-edge",
    "msedge",
    "brave-browser",
)

PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome-stable",
    "/snap/bin/chromium",
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
)

# Le script tourne dans la page, après chargement. Il ne corrige rien : il mesure.
PROBE_JS = r"""
(() => {
  const run = () => {
  const out = {title: document.title, lang: document.documentElement.lang,
               dir: document.documentElement.dir, url: location.href,
               contrasts: [], images: [], iframes: [], links: [], controls: [],
               headings: [], landmarks: {main: document.querySelectorAll('main,[role=main]').length,
                 nav: document.querySelectorAll('nav,[role=navigation]').length,
                 header: document.querySelectorAll('header,[role=banner]').length},
               hiddenFocusable: [], jsText: (document.body ? document.body.innerText.length : 0)};
  const sel = (el) => {
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 4) {
      let part = node.tagName.toLowerCase();
      if (node.classList.length) part += '.' + CSS.escape(node.classList[0]);
      parts.unshift(part);
      node = node.parentElement;
    }
    return parts.join(' > ');
  };
  const rgb = (value) => {
    const m = (value || '').match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map((x) => parseFloat(x));
    if (p.length > 3 && p[3] === 0) return null;
    return p.slice(0, 3);
  };
  const lum = (c) => {
    const v = c.map((x) => { const s = x / 255; return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4); });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
  };
  const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); const hi = Math.max(l1, l2), lo = Math.min(l1, l2); return (hi + 0.05) / (lo + 0.05); };
  const effectiveBg = (el) => {
    let node = el;
    while (node && node.nodeType === 1) {
      const bg = rgb(getComputedStyle(node).backgroundColor);
      if (bg) return bg;
      node = node.parentElement;
    }
    return [255, 255, 255];
  };
  const texted = (el) => (el.textContent || '').trim().slice(0, 120);
  document.querySelectorAll('body *').forEach((el) => {
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return;
    const hasText = Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim().length > 1);
    if (hasText) {
      const fg = rgb(style.color) || [0, 0, 0];
      const bg = effectiveBg(el);
      const size = parseFloat(style.fontSize) || 16;
      const weight = parseInt(style.fontWeight, 10) || 400;
      out.contrasts.push({selector: sel(el), text: texted(el), fg: fg.join(','), bg: bg.join(','),
        ratio: Math.round(ratio(fg, bg) * 100) / 100, size: size, bold: weight >= 700});
    }
    if (el.hasAttribute('aria-hidden') && el.getAttribute('aria-hidden') === 'true' && el.tabIndex >= 0) {
      out.hiddenFocusable.push({selector: sel(el), tag: el.tagName.toLowerCase()});
    }
  });
  document.querySelectorAll('img').forEach((img) => out.images.push({
    selector: sel(img), alt: img.getAttribute('alt'), role: img.getAttribute('role'),
    src: (img.currentSrc || img.src || '').split('/').pop(), width: img.naturalWidth, height: img.naturalHeight}));
  document.querySelectorAll('iframe,frame').forEach((f) => out.iframes.push({selector: sel(f), title: f.getAttribute('title')}));
  document.querySelectorAll('a[href]').forEach((a) => out.links.push({
    selector: sel(a), text: (a.textContent || '').trim().slice(0, 80),
    aria: a.getAttribute('aria-label'), title: a.getAttribute('title'), href: a.getAttribute('href')}));
  document.querySelectorAll('input,select,textarea').forEach((c) => {
    const id = c.getAttribute('id');
    const label = id ? document.querySelector('label[for="' + CSS.escape(id) + '"]') : c.closest('label');
    out.controls.push({selector: sel(c), type: (c.getAttribute('type') || c.tagName).toLowerCase(),
      label: label ? (label.textContent || '').trim().slice(0, 80) : null,
      aria: c.getAttribute('aria-label') || c.getAttribute('aria-labelledby'),
      title: c.getAttribute('title')});
  });
  document.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach((h) => out.headings.push({
    level: parseInt(h.tagName[1], 10), text: (h.textContent || '').trim().slice(0, 80)}));
  const holder = document.createElement('script');
  holder.type = 'application/json';
  holder.id = 'rgaa-browser-report';
  holder.textContent = JSON.stringify(out);
  document.documentElement.appendChild(holder);
  };
  // Le document est encore en cours d'analyse quand la sonde est lue : on attend
  // la fin du parse, sinon <main> et le reste du corps n'existent pas encore.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', run, {once: true});
  } else {
    run();
  }
})();
"""


@dataclass
class Rendered:
    html: str
    report: dict[str, Any] = field(default_factory=dict)
    url: str = ""
    ms: int = 0
    mode: str = "headless"


class BrowserError(RuntimeError):
    pass


def find_chrome() -> str | None:
    forced = os.environ.get("RGAA_CHROME")
    if forced and Path(forced).exists():
        return forced
    for name in CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    for path in PATHS:
        if Path(path).exists():
            return path
    return None


def available() -> dict[str, Any]:
    binary = find_chrome()
    return {"available": bool(binary), "binary": binary, "mode": os.environ.get("RGAA_BROWSER_MODE", "headless")}


def _inject(markup: str, base: str) -> str:
    """Ajoute la base des URL relatives, puis la sonde juste avant </body>."""
    base_tag = f'<base href="{base}">'
    probe = f'<script id="rgaa-probe">{PROBE_JS}</script>'
    head_end = re.search(r"</head\s*>", markup, re.IGNORECASE)
    if head_end:
        markup = markup[: head_end.start()] + base_tag + markup[head_end.start() :]
    else:
        markup = base_tag + markup
    body_end = re.search(r"</body\s*>", markup, re.IGNORECASE)
    if body_end:
        return markup[: body_end.start()] + probe + markup[body_end.start() :]
    return markup + probe


def render(
    *,
    url: str | None = None,
    path: str | Path | None = None,
    mode: str | None = None,
    timeout: float = 90.0,
    budget_ms: int = 4000,
) -> Rendered:
    """Ouvre une page, la laisse s'exécuter, renvoie le DOM rendu et les mesures."""
    binary = find_chrome()
    if not binary:
        raise BrowserError("aucun navigateur Chromium détecté (installer Chrome/Chromium ou régler RGAA_CHROME)")

    if url and not path:
        from .remote import fetch

        page = fetch(url, allow_private=True, keep_scripts=True)
        markup, base = page["html"], page["url"]
    elif path:
        source = Path(path)
        if not source.is_file():
            raise BrowserError(f"page introuvable : {source}")
        markup, base = source.read_text(encoding="utf-8"), source.resolve().as_uri()
    else:
        raise BrowserError("url ou chemin requis")

    flavoured = (mode or os.environ.get("RGAA_BROWSER_MODE") or "headless").lower()
    if flavoured == "headful":
        # Xvfb démarre un serveur X à chaque appel : il faut de la marge.
        timeout = max(timeout, float(os.environ.get("RGAA_HEADFUL_TIMEOUT", "150")))
    workdir = Path(tempfile.mkdtemp(prefix="rgaa-render-"))
    target = workdir / "page.html"
    target.write_text(_inject(markup, base), encoding="utf-8")

    args = [binary, "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--no-first-run"]
    prefix: list[str] = []
    if flavoured == "headful":
        args += ["--window-size=1280,900", "--start-maximized"]
        if not os.environ.get("DISPLAY"):
            xvfb = shutil.which("xvfb-run")
            if not xvfb:
                raise BrowserError(
                    "mode headful sans écran : installer Xvfb (xvfb-run) ou définir DISPLAY"
                )
            prefix = [xvfb, "-a", "-s", "-screen 0 1280x900x24"]
    else:
        args += ["--headless=new"]
    args += [
        "--hide-scrollbars",
        f"--virtual-time-budget={budget_ms}",
        "--run-all-compositor-stages-before-draw",
        "--dump-dom",
        target.as_uri(),
    ]
    started = time.perf_counter()
    try:
        completed = subprocess.run(  # noqa: S603 - binaire local, arguments fixes
            prefix + args, capture_output=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise BrowserError(f"navigateur muet après {timeout:.0f} s") from exc
    elapsed = round((time.perf_counter() - started) * 1000)
    html = completed.stdout.decode("utf-8", "replace")
    if not html.strip():
        detail = completed.stderr.decode("utf-8", "replace")[-400:]
        raise BrowserError(f"dom vide (code {completed.returncode}) {detail}".strip())

    report = extract_report(html)
    return Rendered(html=html, report=report, url=base, ms=elapsed, mode=flavoured)


def extract_report(html: str) -> dict[str, Any]:
    match = re.search(
        rf'<script[^>]*id="{MARKER}"[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE
    )
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def strip_report(html: str) -> str:
    """Retire la sonde avant d'écrire la page nettoyée."""
    return re.sub(rf'<script[^>]*id="{MARKER}"[^>]*>.*?</script>', "", html, flags=re.DOTALL | re.IGNORECASE)
