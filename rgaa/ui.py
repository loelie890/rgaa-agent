"""Interface d'une page, sans dépendance ni CDN.

Trois vues : Agent (campagnes, analyse d'URL), Équipe (sous-agents en parallèle),
Paramètres (backend local, Ollama, vision, mode CI). Thème clair et chaleureux,
mais conforme aux règles que le moteur vérifie : titres hiérarchisés, contrastes
suffisants, champs étiquetés, aucune image sans alternative.
"""

INDEX_HTML = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RGAA Agent, audit et corrections d'accessibilité en local</title>
<style>
  :root{--cream:#fffaf7;--paper:#fff;--ink:#2b2430;--muted:#6d5f6b;--line:#f0dfe7;--rose:#b03060;
        --rose-soft:#fdf0f5;--lilac:#6b5bd2;--lilac-soft:#f1eeff;--sage:#1f6f4a;--sage-soft:#eaf6ef;
        --amber:#8a5b00;--amber-soft:#fdf3e2;--r:18px;--shadow:0 10px 30px rgba(120,60,90,.08)}
  *{box-sizing:border-box}
  body{margin:0;background:var(--cream);color:var(--ink);font:15.5px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif}
  h1,h2,h3{font-family:"Iowan Old Style",Georgia,"Times New Roman",serif;font-weight:600}
  header{position:sticky;top:0;z-index:5;background:rgba(255,250,247,.94);backdrop-filter:blur(8px);
         border-bottom:1px solid var(--line);padding:16px 30px 12px}
  .bar{display:flex;flex-wrap:wrap;gap:16px;align-items:center;max-width:1240px;margin:0 auto}
  .brand{font-family:"Iowan Old Style",Georgia,serif;font-size:23px}
  .brand b{color:var(--rose);font-weight:600}
  .tagline{color:var(--muted);font-size:13px;max-width:420px}
  nav{display:flex;gap:6px;margin-left:auto;background:var(--paper);border:1px solid var(--line);border-radius:999px;padding:4px}
  nav button{border:0;background:transparent;color:var(--muted);padding:8px 16px;border-radius:999px;font:inherit;font-size:14px;cursor:pointer}
  nav button[aria-selected="true"]{background:var(--rose);color:#fff;font-weight:600}
  main{max-width:1240px;margin:0 auto;padding:26px 30px 70px;display:grid;grid-template-columns:minmax(330px,.95fr) minmax(380px,1.25fr);gap:24px;align-items:start}
  @media (max-width:980px){main{grid-template-columns:1fr}}
  section h2{font-size:13px;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-family:inherit;font-weight:700;margin:0 0 12px}
  .card{background:var(--paper);border:1px solid var(--line);border-radius:var(--r);padding:20px 22px;box-shadow:var(--shadow);margin-bottom:18px}
  .card h3{margin:0 0 6px;font-size:19px}
  .card p{margin:0 0 14px;color:var(--muted);font-size:14px}
  .meta{display:flex;gap:8px;flex-wrap:wrap;font-size:12.5px;color:var(--muted);margin-bottom:14px}
  .chip{border-radius:999px;padding:3px 11px;background:var(--rose-soft);color:var(--rose)}
  .chip.lilac{background:var(--lilac-soft);color:var(--lilac)}
  .chip.sage{background:var(--sage-soft);color:var(--sage)}
  .chip.amber{background:var(--amber-soft);color:var(--amber)}
  button{font:inherit}
  .btn{display:inline-block;border:1px solid var(--line);background:var(--paper);color:var(--ink);border-radius:12px;
       padding:9px 16px;font-size:14px;cursor:pointer;text-decoration:none}
  .btn:hover{border-color:var(--rose);color:var(--rose)}
  .btn.primary{background:var(--rose);border-color:var(--rose);color:#fff;font-weight:600}
  .btn.primary:hover{background:#96284f;color:#fff}
  .btn.lilac{background:var(--lilac);border-color:var(--lilac);color:#fff;font-weight:600}
  .btn.rose{background:var(--rose);border-color:var(--rose);color:#fff;font-weight:600}
  .btn:disabled{opacity:.55;cursor:progress}
  .btn-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
  label{display:block;font-size:12.5px;color:var(--muted);margin-bottom:4px}
  input,select{width:100%;background:#fffdfd;border:1px solid var(--line);border-radius:11px;padding:9px 11px;font:inherit;font-size:14px;color:var(--ink)}
  input:focus,select:focus,.btn:focus,nav button:focus{outline:3px solid #f3c6d8;outline-offset:1px}
  .field{margin-bottom:14px}
  .field-row{display:flex;gap:10px}
  .switch{display:flex;align-items:center;gap:10px;margin-bottom:14px}
  .switch input{width:auto}
  .summary{display:flex;gap:18px;flex-wrap:wrap;margin:4px 0 14px;font-size:14px;color:var(--muted)}
  .summary b{color:var(--ink);font-size:17px;display:block}
  .scorewrap{background:var(--lilac-soft);border-radius:14px;padding:12px 16px;margin-bottom:14px}
  .scorebar{height:10px;background:#e6e1f7;border-radius:999px;overflow:hidden;display:flex;gap:2px}
  .scorebar span{display:block;height:100%}
  .steps{display:flex;flex-direction:column;gap:9px;max-height:46vh;overflow:auto;padding-right:4px}
  .step{border:1px solid var(--line);border-left:4px solid var(--sage);border-radius:12px;padding:10px 12px;background:#fffdfd}
  .step.err{border-left-color:var(--rose)}
  .step .head{display:flex;gap:8px;align-items:baseline;font-size:13px}
  .step code{color:var(--rose);font-size:12.5px;word-break:break-all}
  .step .thought{color:var(--muted);font-size:12.5px;margin-top:2px}
  .step pre{margin:6px 0 0;white-space:pre-wrap;word-break:break-word;font-size:12px;color:#4b4048;background:var(--cream);border-radius:8px;padding:8px 10px;max-height:140px;overflow:auto}
  table{width:100%;border-collapse:collapse;font-size:13.5px}
  th{text-align:left;font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);border-bottom:1px solid var(--line);padding:7px 8px}
  td{padding:8px;border-bottom:1px solid #f7ecf1;vertical-align:top}
  .artifacts{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:12px}
  .artifacts a{color:var(--lilac);text-decoration:none;border:1px solid var(--line);border-radius:10px;padding:5px 11px;font-size:12.5px;background:#fff}
  pre.viewer{background:var(--cream);border:1px solid var(--line);border-radius:12px;padding:14px;white-space:pre-wrap;word-break:break-word;font-size:12.5px;color:#4b4048;max-height:40vh;overflow:auto;margin:0}
  .muted{color:var(--muted);font-size:13px}
  ul.clean{list-style:none;padding:0;margin:0}
  ul.clean li{font-size:13px;color:var(--muted);margin-bottom:8px}
  ul.clean b{color:var(--ink)}
  .note{border-left:3px solid var(--lilac);background:var(--lilac-soft);padding:11px 14px;border-radius:0 12px 12px 0;font-size:13px;color:#433d8c}
  footer{max-width:1240px;margin:0 auto;padding:0 30px 40px;color:var(--muted);font-size:12.5px}
  [hidden]{display:none!important}
</style>
</head>
<body>
<header>
  <div class="bar">
    <span class="brand">RGAA <b>Agent</b></span>
    <span class="tagline">audit et corrections d'accessibilité, en local, avec preuve chiffrée</span>
    <nav role="tablist" aria-label="Vues">
      <button role="tab" id="tab-agent" aria-selected="true" aria-controls="view-agent" data-tab="agent">Agent</button>
      <button role="tab" id="tab-team" aria-selected="false" aria-controls="view-team" data-tab="team">Équipe</button>
      <button role="tab" id="tab-settings" aria-selected="false" aria-controls="view-settings" data-tab="settings">Paramètres</button>
      <a class="btn" href="/demo" target="_blank" rel="noopener" style="margin-left:8px">Voir la démo</a>
    </nav>
  </div>
</header>

<main>
  <div id="view-agent">
    <section aria-labelledby="scan-title">
      <h2 id="scan-title">Analyser un site</h2>
      <div class="card">
        <h3>Une URL, ou les pages de démonstration</h3>
        <p>Collez l'adresse d'une page publique : elle est récupérée une seule fois, analysée, corrigée et exportable. Aucun envoi vers un tiers.</p>
        <div class="field">
          <label for="siteUrl">Adresse de la page</label>
          <input id="siteUrl" type="url" placeholder="https://exemple.fr/" spellcheck="false">
        </div>
        <div class="switch">
          <input type="checkbox" id="scanBrowser">
          <label for="scanBrowser" style="margin:0;font-size:14px;color:var(--ink)">Mesurer aussi dans Chromium (DOM rendu, JavaScript)</label>
        </div>
        <div class="btn-row">
          <button class="btn primary" id="scanBtn">Analyser cette page</button>
          <span id="scanOut" class="muted"></span>
        </div>
      </div>
    </section>

    <section aria-labelledby="campagnes-title">
      <h2 id="campagnes-title">Campagnes</h2>
      <div class="card">
        <h3>Nouvelle campagne</h3>
        <p>Une campagne est un objectif nommé. Celles créées ici s'exécutent sans modèle, avec les corrections déterministes : images, titres, formulaires, contrastes, tableaux.</p>
        <div class="field"><label for="campTitle">Titre</label><input id="campTitle" placeholder="Contrôle des pages produits"></div>
        <div class="field"><label for="campObjective">Objectif</label><input id="campObjective" placeholder="Vérifier les images et les formulaires des pages produits"></div>
        <div class="field"><label for="campBudget">Budget d'étapes</label><input id="campBudget" value="24" spellcheck="false"></div>
        <div class="btn-row">
          <button class="btn primary" id="campCreate">Créer la campagne</button>
          <button class="btn" id="campReset">Annuler la modification</button>
          <span id="campOut" class="muted"></span>
        </div>
      </div>
      <div id="campagnes"><p class="muted">chargement…</p></div>
    </section>

    <section aria-labelledby="skills-title">
      <h2 id="skills-title">Procédures apprises</h2>
      <div class="card">
        <ul class="clean" id="skills"><li>aucune pour l'instant</li></ul>
        <p class="muted" style="margin-top:10px">Écrites après une erreur, conservées hors du bac à sable, relues au run suivant.</p>
      </div>
    </section>

    <section aria-labelledby="rules-title">
      <h2 id="rules-title">Règles vérifiées</h2>
      <div class="card"><ul class="clean" id="rules"><li>chargement…</li></ul></div>
    </section>
  </div>

  <div id="view-team" hidden>
    <section aria-labelledby="team-title">
      <h2 id="team-title">Équipe de sous-agents</h2>
      <div class="card">
        <h3>Un sous-agent par page, en parallèle</h3>
        <p>Chaque page est confiée à un sous-agent indépendant, avec son rôle, son budget et son score. L'orchestrateur recolle, recalcule et produit le rapport. Même moteur que le mode CI, distribué par page.</p>
        <div class="btn-row"><button class="btn primary" id="teamBtn">Lancer l'équipe</button><span id="teamOut" class="muted"></span></div>
      </div>
      <div class="card">
        <h3>Ajouter un sous-agent</h3>
        <p>Donnez-lui un nom, une spécialité et les pages qu'il couvre. L'équipe de départ reste disponible si vous n'ajoutez personne.</p>
        <div class="field"><label for="agentName">Nom</label><input id="agentName" placeholder="agent-formulaires" spellcheck="false"></div>
        <div class="field">
          <label for="agentRole">Spécialité</label>
          <select id="agentRole">
            <option value="structure">structure et titres</option>
            <option value="media">images et médias</option>
            <option value="formulaires">formulaires</option>
            <option value="contraste">couleurs et contraste</option>
            <option value="tableaux">tableaux</option>
            <option value="vision">vision</option>
            <option value="conformité">conformité générale</option>
          </select>
        </div>
        <div class="field"><label for="agentPages">Pages couvertes</label><input id="agentPages" value="toutes" spellcheck="false"></div>
        <div class="btn-row">
          <button class="btn" id="agentAdd">Ajouter à l'équipe</button>
          <span id="agentOut" class="muted"></span>
        </div>
        <ul class="clean" id="agentList" style="margin-top:12px"></ul>
      </div>

      <div class="card">
        <h3>Résultat de l'équipe</h3>
        <div id="teamResult"><p class="muted">Aucune exécution pour l'instant.</p></div>
      </div>
    </section>
  </div>

  <div id="view-settings" hidden>
    <section aria-labelledby="settings-title">
      <h2 id="settings-title">Paramètres</h2>
      <div class="card">
        <h3>Backend local</h3>
        <p>Un serveur OpenAI-compatible suffit : Ollama, LM Studio, vLLM, llama.cpp. Les valeurs restent dans ce navigateur.</p>
        <div class="switch">
          <input type="checkbox" id="ollamaOn">
          <label for="ollamaOn" style="margin:0;font-size:14px;color:var(--ink)">Utiliser Ollama</label>
        </div>
        <div class="field">
          <label for="backendUrl">Adresse du serveur</label>
          <input id="backendUrl" spellcheck="false" placeholder="http://127.0.0.1:11434">
        </div>
        <div class="field">
          <label for="modelName">Modèle de décision</label>
          <select id="modelName"><option value="">sonder le serveur</option></select>
        </div>
        <div class="btn-row">
          <button class="btn" id="probeBtn">Sonder et lister les modèles</button>
          <span id="probeOut" class="muted"></span>
        </div>
      </div>

      <div class="card">
        <h3>Modèle vision (optionnel)</h3>
        <p>Utilisé pour décrire une image. Sans modèle chargé, l'agent décrit depuis le contexte HTML et le signale.</p>
        <div class="field">
          <label for="visionUrl">Adresse du serveur vision</label>
          <input id="visionUrl" spellcheck="false" placeholder="http://127.0.0.1:11434">
        </div>
        <div class="field">
          <label for="visionModel">Modèle vision</label>
          <select id="visionModel"><option value="">sonder le serveur vision</option></select>
        </div>
        <div class="btn-row">
          <button class="btn" id="probeVisionBtn">Sonder l'adresse vision</button>
          <span id="probeVisionOut" class="muted"></span>
        </div>
      </div>

      <div class="card">
        <h3>Ollama dans le conteneur</h3>
        <p>L'image peut embarquer Ollama. Activez-le ici, démarrez-le, puis choisissez un modèle : il est téléchargé une fois et reste dans le volume.</p>
        <div class="switch">
          <input type="checkbox" id="embeddedOn">
          <label for="embeddedOn" style="margin:0;font-size:14px;color:var(--ink)">Utiliser l'Ollama intégré</label>
        </div>
        <div class="btn-row">
          <button class="btn" id="ollamaStart">Démarrer Ollama</button>
          <span id="ollamaOut" class="muted"></span>
        </div>
        <div class="field" style="margin-top:12px"><label for="ollamaModel">Modèle à télécharger</label><input id="ollamaModel" placeholder="qwen2.5:3b" spellcheck="false"></div>
        <div class="btn-row"><button class="btn" id="ollamaPull">Télécharger ce modèle</button></div>
      </div>

      <div class="card">
        <h3>Ce que cette image sait faire</h3>
        <p>Deux capacités dépendent de la construction de l'image, pas d'un réglage : le navigateur et le modèle embarqué.</p>
        <ul class="clean" id="capabilities"><li class="muted">chargement…</li></ul>
      </div>

      <div class="card">
        <h3>Serveur MCP</h3>
        <p>Les mêmes outils, servis en JSON-RPC sur l'entrée et la sortie standard : un client MCP les voit comme des outils natifs.</p>
        <div class="field"><label for="mcpCmd">Commande à déclarer</label><input id="mcpCmd" value="python -m rgaa mcp" readonly></div>
        <p class="muted">Cinq outils : coverage, audit_site, render_page, list_campaigns, run_campaign. Aucun port ouvert, aucun processus en fond.</p>
      </div>

      <div class="card">
        <h3>Mode CI</h3>
        <p>Mêmes corrections que la ligne de commande, sans modèle. Utile pour vérifier un seuil avant de brancher un pipeline.</p>
        <div class="field"><label for="ciScore">Seuil de conformité exigé</label><input id="ciScore" value="100" spellcheck="false"></div>
        <div class="btn-row"><button class="btn" id="ciBtn">Lancer le mode CI</button><span id="ciOut" class="muted"></span></div>
      </div>

      <div class="note">Dans le conteneur, l'adresse par défaut est <code>http://host.docker.internal:11434</code> : Ollama tourne sur la machine hôte, pas dans l'image.</div>
    </section>
  </div>

  <div id="view-result">
    <section aria-labelledby="result-title">
      <h2 id="result-title">Résultat</h2>
      <div class="card" id="resultCard">
        <p class="muted">Choisissez un campagne, une URL ou l'équipe. Le score affiché est recalculé sur les fichiers produits, jamais déclaré.</p>
      </div>
    </section>
  </div>
</main>

<footer>RGAA Agent · MIT · site de démonstration synthétique, aucune donnée personnelle. Audit local, aucune ressource externe.</footer>

<script>
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const store = { get: (k, d) => { try { return localStorage.getItem("rgaa:" + k) ?? d; } catch (e) { return d; } },
                set: (k, v) => { try { localStorage.setItem("rgaa:" + k, v); } catch (e) {} } };

async function api(path, options) {
  const response = await fetch(path, options);
  const text = await response.text();
  try { return JSON.parse(text); } catch (e) { return { error: text || response.statusText }; }
}

function showTab(name) {
  ["agent", "team", "settings"].forEach((tab) => {
    const view = $("#view-" + tab);
    const button = $("#tab-" + tab);
    const active = tab === name;
    if (view) view.hidden = !active;
    if (button) button.setAttribute("aria-selected", active ? "true" : "false");
  });
}
document.querySelectorAll("nav button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

function renderCampagnes(data) {
  const box = $("#campagnes");
  if (!data.campagnes || !data.campagnes.length) { box.innerHTML = '<p class="muted">aucune campagne</p>'; return; }
  box.innerHTML = data.campagnes.map((s) => `
    <div class="card">
      <h3>${esc(s.title)}</h3>
      <p>${esc(s.objective)}</p>
      <div class="meta">
        <span class="chip">budget ${s.budget} étapes</span>
        <span class="chip lilac">${s.fixtures.length} page(s)</span>
        <span class="chip">${s.engine === "auto" ? "automatique" : "rejouée"}</span>
        ${s.learning ? '<span class="chip amber">apprentissage</span>' : ""}
      </div>
      <div class="btn-row">
        <button class="btn primary" data-run="${esc(s.slug)}">Lancer</button>
        <button class="btn" data-live="${esc(s.slug)}">Avec le modèle local</button>
        <button class="btn" data-edit="${esc(s.slug)}">Modifier</button>
        <button class="btn" data-del="${esc(s.slug)}" ${s.engine === "auto" ? "" : "disabled"}>Supprimer</button>
      </div>
    </div>`).join("");
  box.querySelectorAll("[data-run]").forEach((b) => b.addEventListener("click", () => runCampagne(b.dataset.run, "replay", b)));
  box.querySelectorAll("[data-live]").forEach((b) => b.addEventListener("click", () => runCampagne(b.dataset.live, "live", b)));
  box.querySelectorAll("[data-edit]").forEach((b) => b.addEventListener("click", () => editCampagne(b.dataset.edit, data.campagnes)));
  box.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", () => deleteCampagne(b.dataset.del)));
}

function editCampagne(slug, list) {
  const item = (list || []).find((entry) => entry.slug === slug);
  if (!item) return;
  window.__editing = slug;
  $("#campTitle").value = item.title;
  $("#campObjective").value = item.objective;
  $("#campBudget").value = item.budget;
  $("#campOut").textContent = `modification de « ${item.title} »`;
}

async function submitCampagne() {
  const title = $("#campTitle").value.trim();
  const objective = $("#campObjective").value.trim();
  const budget = parseInt($("#campBudget").value, 10) || 24;
  if (!title || !objective) { $("#campOut").textContent = "titre et objectif requis"; return; }
  const editing = window.__editing;
  const result = editing
    ? await api(`/api/campagnes/${encodeURIComponent(editing)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title, objective, budget }) })
    : await api("/api/campagnes", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title, objective, budget }) });
  if (result.error) { $("#campOut").textContent = result.error; return; }
  window.__editing = null;
  $("#campTitle").value = "";
  $("#campObjective").value = "";
  $("#campOut").textContent = editing ? "campagne modifiée" : "campagne créée";
  renderCampagnes({ campagnes: result.campagnes });
}

async function deleteCampagne(slug) {
  if (!confirm(`Supprimer la campagne « ${slug} » ?`)) return;
  const result = await api(`/api/campagnes/${encodeURIComponent(slug)}`, { method: "DELETE" });
  if (result.error) { $("#campOut").textContent = result.error; return; }
  $("#campOut").textContent = "campagne supprimée";
  renderCampagnes({ campagnes: result.campagnes });
}

function renderAgents() {
  const box = $("#agentList");
  box.innerHTML = (window.__agents || []).map((a, index) => `<li><b>${esc(a.name)}</b> · ${esc(a.role)} · ${esc(a.pages)} <button class="btn" data-rm-agent="${index}" style="padding:2px 8px;font-size:12px">retirer</button></li>`).join("") || '<li class="muted">équipe automatique : un agent par page</li>';
  box.querySelectorAll("[data-rm-agent]").forEach((b) => b.addEventListener("click", () => {
    window.__agents.splice(Number(b.dataset.rmAgent), 1);
    renderAgents();
  }));
}

async function ollamaStatus() {
  const status = await api("/api/ollama/status");
  if (status.error) { $("#ollamaOut").textContent = status.error; return; }
  const bits = [];
  bits.push(status.installed ? "binaire présent" : "binaire absent");
  bits.push(status.running ? "serveur actif" : "serveur arrêté");
  if (status.embedded) bits.push("mode conteneur");
  $("#ollamaOut").textContent = bits.join(" · ");
}

async function ollamaStart() {
  $("#ollamaOut").textContent = "démarrage…";
  const result = await api("/api/ollama/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  if (result.error) { $("#ollamaOut").textContent = result.error; return; }
  $("#backendUrl").value = result.url;
  saveSettings();
  $("#ollamaOut").textContent = result.running ? "Ollama actif" : "Ollama non démarré";
}

async function ollamaPull() {
  const model = $("#ollamaModel").value.trim();
  if (!model) { $("#ollamaOut").textContent = "modèle requis"; return; }
  $("#ollamaOut").textContent = "téléchargement…";
  const result = await api("/api/ollama/pull", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model }) });
  $("#ollamaOut").textContent = result.error ? result.error : `modèle ${model} prêt`;
  await probeModels();
}

$("#campCreate").addEventListener("click", submitCampagne);
$("#campReset").addEventListener("click", () => { window.__editing = null; $("#campOut").textContent = ""; });
$("#agentAdd").addEventListener("click", () => {
  const name = ($("#agentName").value || "").trim() || `agent-${(window.__agents || []).length + 1}`;
  window.__agents = window.__agents || [];
  window.__agents.push({ name, role: $("#agentRole").value, pages: ($("#agentPages").value || "toutes").trim() });
  $("#agentName").value = "";
  $("#agentOut").textContent = `${window.__agents.length} sous-agent(s) personnalisé(s)`;
  renderAgents();
});
$("#ollamaStart").addEventListener("click", ollamaStart);
$("#tab-settings").addEventListener("click", loadCapabilities);
$("#ollamaPull").addEventListener("click", ollamaPull);
$("#embeddedOn").addEventListener("change", () => { saveSettings(); ollamaStatus(); });

async function loadCapabilities() {
  const box = $("#capabilities");
  if (!box) return;
  const data = await api("/api/capabilities");
  if (data.error) { box.innerHTML = `<li class="muted">${esc(data.error)}</li>`; return; }
  const chrome = data.chrome || {};
  const ollama = data.ollama || {};
  box.innerHTML = `
    <li><b>Navigateur</b> · ${chrome.available ? `Chromium présent (${esc(chrome.binary || "")}), Xvfb ${chrome.xvfb ? "oui" : "non"}` : "absent de cette image"}</li>
    <li><b>Ollama</b> · ${ollama.installed ? (ollama.running ? "binaire présent, serveur actif" : "binaire présent, serveur arrêté") : "absent de cette image"}</li>
    <li><b>Campagnes</b> · ${data.campagnes} · <b>règles</b> · ${data.rules} · <b>Python</b> · ${esc(data.python || "")}</li>`;
  if (!chrome.available) box.innerHTML += `<li class="muted">Pour l'activer : reconstruire avec --build-arg INSTALL_BROWSER=1, voir docs/DEPLOY.md</li>`;
}

function renderSkills(skills) {
  const box = $("#skills");
  if (!skills || !skills.length) { box.innerHTML = "<li>aucune pour l'instant, lancez le campagne d'apprentissage</li>"; return; }
  box.innerHTML = skills.map((s) => `<li><b>${esc(s.name)}</b> · ${esc(s.campagne)} · ${s.chars} caractères<br><span>${esc(s.preview)}</span></li>`).join("");
}

function renderRules(rules) {
  const box = $("#rules");
  if (!rules || !rules.length) { box.innerHTML = "<li>aucune règle</li>"; return; }
  box.innerHTML = rules.map((r) => `<li><b>${esc(r.label)}</b> · critère ${esc(r.rgpa)} · ${esc(r.severity)}</li>`).join("");
}

function lastScore(steps) {
  for (let i = steps.length - 1; i >= 0; i--) {
    const r = steps[i].observation && steps[i].observation.result;
    if (r && r.score && typeof r.score.percent === "number") return r;
  }
  return null;
}

function summaryBlock(title, before, after, violations, patches, extra, gradeBefore, gradeAfter) {
  const tone = after >= 100 ? "var(--sage)" : "var(--lilac)";
  const badge = (grade, letter) => grade && letter
    ? `<span class="chip ${letter === "A" || letter === "B" ? "sage" : letter === "C" ? "amber" : ""}" title="${esc(grade.label)}">note ${esc(letter)} · ${esc(grade.label)}</span>`
    : "";
  return `<h3>${esc(title)}</h3>
    <div class="meta">${badge(gradeBefore, gradeBefore && gradeBefore.letter)}${gradeAfter ? '<span class="muted">après corrections</span>' : ""}${badge(gradeAfter, gradeAfter && gradeAfter.letter)}</div>
    <div class="summary">
      <span>avant<b>${before} %</b></span>
      <span>après<b>${after} %</b></span>
      <span>violations restantes<b>${violations}</b></span>
      <span>corrections<b>${patches}</b></span>
    </div>
    <div class="scorewrap"><div class="scorebar"><span style="width:${before}%;background:#cbbfe8"></span><span style="width:${after}%;background:${tone}"></span></div></div>
    ${extra || ""}`;
}

function visionLine(v) {
  if (!v || !v.available) return "";
  const skipped = v.skipped ? `, ${v.skipped} image(s) inaccessible(s)` : "";
  return `<p class="muted">Vision (${esc(v.model || "modèle local")}) : ${v.images} image(s) analysée(s), ${v.findings} constat(s), ${v.fixes} alternative(s) écrite(s)${skipped}.</p>`;
}

function exportRow(runId) {
  if (!runId) return "";
  return `<div class="btn-row" style="margin-bottom:14px">
    <a class="btn primary" href="/api/export?run=${encodeURIComponent(runId)}&format=zip" download>Tout exporter (ZIP)</a>
    <a class="btn" href="/api/export?run=${encodeURIComponent(runId)}&format=html">Rapport HTML</a>
    <a class="btn" href="/api/export?run=${encodeURIComponent(runId)}&format=json">JSON</a>
  </div>`;
}

async function runCampagne(slug, mode, button) {
  const label = button.textContent;
  button.disabled = true;
  $("#resultCard").innerHTML = '<p class="muted">exécution en cours…</p>';
  const payload = { campagne: slug, mode };
  if (mode === "live") { payload.base_url = $("#backendUrl").value; payload.model = $("#modelName").value; }
  if ($("#visionUrl").value.trim()) { payload.vision_url = $("#visionUrl").value.trim(); payload.vision_model = $("#visionModel").value.trim(); }
  const result = await api("/api/run", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  button.disabled = false;
  button.textContent = label;
  if (result.error) { $("#resultCard").innerHTML = `<p class="muted">${esc(result.error)}</p>`; return; }
  renderResult(result);
  const fresh = await api("/api/campagnes");
  renderSkills(fresh.skills);
}

function renderResult(r) {
  const steps = r.steps.map((s) => `
    <div class="step ${s.ok ? "" : "err"}">
      <div class="head"><span>${s.step}</span><code>${esc(s.tool)}</code><span class="muted">${esc(s.pass)}</span></div>
      <div class="thought">${esc(s.thought)}</div>
      <pre>${esc(s.ok ? JSON.stringify(s.observation.result, null, 1).slice(0, 900) : "erreur : " + s.observation.error)}</pre>
    </div>`).join("");
  const artefacts = r.artifacts.map((a) => `<a href="#" data-art="${esc(a.name)}">${esc(a.name)}</a>`).join("");
  const sc = lastScore(r.steps);
  const patches = r.steps.filter((s) => s.tool === "patch_html" && s.ok).length;
  const head = sc
    ? summaryBlock(r.title, sc.baseline ? sc.baseline.percent : sc.score.percent, sc.score.percent, sc.score.violations, patches, null, sc.baseline ? sc.baseline.grade : null, sc.score.grade)
    : `<h3>${esc(r.title)} <span class="chip sage">${esc(r.status)}</span></h3>`;
  const learning = r.passes.length > 1
    ? `<div class="meta">${r.passes.map((p) => `<span class="chip">${esc(p.label)} · ${p.steps} étapes · ${p.errors} erreur(s)</span>`).join("")}</div>`
    : "";
  $("#resultCard").innerHTML = `
    ${head}
    ${learning}
    ${exportRow(r.run_id)}
    <div class="artifacts">${artefacts || '<span class="muted">aucun artefact</span>'}</div>
    <pre class="viewer" id="viewer">${esc(r.final || "(pas de conclusion)")}</pre>
    <h2 style="margin:18px 0 10px">Journal</h2>
    <div class="steps">${steps}</div>`;
  $("#resultCard").querySelectorAll("[data-art]").forEach((a) => a.addEventListener("click", async (event) => {
    event.preventDefault();
    const response = await fetch(`/api/artifact?run=${encodeURIComponent(r.run_id)}&name=${encodeURIComponent(a.dataset.art)}`);
    $("#viewer").textContent = await response.text();
    $("#viewer").scrollTop = 0;
  }));
}

async function runTeam() {
  const button = $("#teamBtn");
  button.disabled = true;
  $("#teamOut").textContent = "les sous-agents travaillent…";
  const result = await api("/api/team", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ workers: 4, vision_url: $("#visionUrl").value.trim(), vision_model: $("#visionModel").value.trim(), agents: window.__agents || [] }) });
  button.disabled = false;
  if (result.error) { $("#teamOut").textContent = result.error; return; }
  $("#teamOut").textContent = `${result.agents.length} sous-agents · ${result.ms} ms`;
  const rows = result.agents.map((a) => `<tr>
      <td>${esc(a.agent)}</td><td>${esc(a.role)}</td><td>${esc(a.page)}</td>
      <td>${a.before} %</td><td>${a.after} %</td><td>${a.patches}</td><td>${a.ms} ms</td></tr>`).join("");
  $("#teamResult").innerHTML = `
    ${summaryBlock("Score de l'équipe", result.baseline.percent, result.score.percent, result.score.violations, result.patches, null, result.baseline.grade, result.score.grade)}
    ${visionLine(result.vision)}
    ${exportRow(result.run_id)}
    <table>
      <thead><tr><th>Sous-agent</th><th>Rôle</th><th>Page</th><th>Avant</th><th>Après</th><th>Corrections</th><th>Durée</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

async function scanSite() {
  const url = $("#siteUrl").value.trim();
  if (!url) { $("#scanOut").textContent = "adresse vide"; return; }
  const button = $("#scanBtn");
  button.disabled = true;
  $("#scanOut").textContent = "récupération…";
  const result = await api("/api/scan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url, vision_url: $("#visionUrl").value.trim(), vision_model: $("#visionModel").value.trim(), browser: $("#scanBrowser").checked }) });
  button.disabled = false;
  if (result.error) { $("#scanOut").textContent = result.error; return; }
  const nav = result.browser && result.browser.available
    ? ` · rendu ${result.browser.mode} ${result.browser.ms} ms, ${(result.browser.findings || []).length} constat(s)`
    : (result.browser && result.browser.error ? " · rendu indisponible" : "");
  $("#scanOut").textContent = `${result.page} · ${result.bytes} octets${nav}`;
  $("#resultCard").innerHTML = `
    ${summaryBlock(result.url, result.baseline.percent, result.score.percent, result.score.violations, result.patches, null, result.baseline.grade, result.score.grade)}
    ${visionLine(result.vision)}
    ${exportRow(result.run_id)}
    <p class="muted">Page récupérée une seule fois, analysée localement, corrigée dans le bac à sable. Les corrections provisoires sur les textes sont signalées à relire.</p>`;
  showTab("agent");
}

async function runCi() {
  const button = $("#ciBtn");
  button.disabled = true;
  $("#ciOut").textContent = "calcul…";
  const result = await api("/api/ci", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ min_score: parseFloat($("#ciScore").value) || 100, vision_url: $("#visionUrl").value.trim(), vision_model: $("#visionModel").value.trim() }) });
  button.disabled = false;
  if (result.error) { $("#ciOut").textContent = result.error; return; }
  $("#ciOut").textContent = `${result.baseline.percent} % → ${result.score.percent} % · sortie ${result.exit_code}`;
  $("#resultCard").innerHTML = `
    ${summaryBlock("Mode CI", result.baseline.percent, result.score.percent, result.score.violations, result.patches,
      `<p class="muted">${result.review} correction(s) textuelles à relire · ${result.diff_lines} lignes de diff · code de sortie ${result.exit_code}</p>`,
      result.baseline.grade, result.score.grade)}
    <p class="muted">Le mode CI n'écrit rien dans le dépôt : il produit le diff et le code de sortie.</p>`;
}

function applySettings() {
  $("#ollamaOn").checked = store.get("ollama", "1") === "1";
  $("#backendUrl").value = store.get("backend", "http://127.0.0.1:11434");
  $("#visionUrl").value = store.get("vision", "");
  $("#visionModel").value = store.get("visionModel", "");
  $("#ciScore").value = store.get("ciScore", "100");
  const model = store.get("model", "");
  if (model) {
    const option = document.createElement("option");
    option.value = model;
    option.textContent = model;
    $("#modelName").appendChild(option);
  }
}
function saveSettings() {
  store.set("ollama", $("#ollamaOn").checked ? "1" : "0");
  store.set("backend", $("#backendUrl").value.trim());
  store.set("model", $("#modelName").value);
  store.set("vision", $("#visionUrl").value.trim());
  store.set("visionModel", $("#visionModel").value.trim());
  store.set("ciScore", $("#ciScore").value);
}
["ollamaOn", "backendUrl", "modelName", "visionUrl", "visionModel", "ciScore"].forEach((id) => {
  const el = $("#" + id);
  if (el) el.addEventListener("change", saveSettings);
});

async function probeModels() {
  $("#probeOut").textContent = "…";
  const result = await api("/api/probe", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ base_url: $("#backendUrl").value }) });
  if (result.error) { $("#probeOut").textContent = result.error; return; }
  const select = $("#modelName");
  const previous = select.value;
  select.innerHTML = result.models.length
    ? result.models.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join("")
    : '<option value="">aucun modèle exposé</option>';
  if (previous && result.models.includes(previous)) select.value = previous;
  $("#probeOut").textContent = `${result.models.length} modèle(s)`;
  saveSettings();
}

$("#teamBtn").addEventListener("click", runTeam);
$("#scanBtn").addEventListener("click", scanSite);
$("#ciBtn").addEventListener("click", runCi);
async function probeVision() {
  const url = $("#visionUrl").value.trim() || $("#backendUrl").value.trim();
  if (!url) { $("#probeVisionOut").textContent = "adresse vide"; return; }
  $("#probeVisionOut").textContent = "…";
  const result = await api("/api/probe", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ base_url: url }) });
  if (result.error) { $("#probeVisionOut").textContent = result.error; return; }
  const select = $("#visionModel");
  const previous = select.value;
  select.innerHTML = result.models.length
    ? result.models.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join("")
    : '<option value="">aucun modèle exposé</option>';
  if (previous && result.models.includes(previous)) select.value = previous;
  $("#probeVisionOut").textContent = `${result.models.length} modèle(s)`;
  saveSettings();
}

$("#probeBtn").addEventListener("click", probeModels);
$("#probeVisionBtn").addEventListener("click", probeVision);

(async () => {
  applySettings();
  const data = await api("/api/campagnes");
  renderCampagnes(data);
  renderSkills(data.skills);
  renderRules((await api("/api/rules")).rules);
  renderAgents();
  ollamaStatus();
  loadCapabilities();
  const settings = await api("/api/settings");
  if (!store.get("backend") && settings.ollama_url) $("#backendUrl").value = settings.ollama_url;
  if (!store.get("vision") && settings.vision_url) $("#visionUrl").value = settings.vision_url;
})();
</script>
</body>
</html>
"""
