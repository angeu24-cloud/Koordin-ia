// Koordin-IA — interface web (sans étape de compilation)
const $app = document.getElementById("app");
const state = { user: null, project: null, tab: "plan", model: null, storey: 0, view: "2d", poll: null };

// ------------------------------------------------------------------ outils
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d = 1) => (v === null || v === undefined || v === "") ? "—" : Number(v).toLocaleString("fr-FR", { maximumFractionDigits: d, minimumFractionDigits: 0 });
const when = (ts) => ts ? new Date(ts * 1000).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "";
function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 3500);
}
async function api(path, opts = {}) {
  const init = { credentials: "same-origin", ...opts };
  if (opts.json !== undefined) {
    init.method = init.method || "POST";
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(opts.json);
  }
  const r = await fetch(path, init);
  if (r.status === 401 && !path.startsWith("/api/compte")) { state.user = null; go("#/connexion"); throw new Error("Connexion requise."); }
  const ct = r.headers.get("content-type") || "";
  const body = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((body && body.detail) || `Erreur ${r.status}`);
  return body;
}
const go = (hash) => { if (location.hash !== hash) location.hash = hash; else route(); };
const canEdit = () => state.project && state.project.role !== "lecteur";
const isOwner = () => state.project && state.project.role === "proprietaire";

// ------------------------------------------------------------------ navigation
window.addEventListener("hashchange", route);
document.getElementById("logout").onclick = async () => {
  await api("/api/compte/deconnexion", { method: "POST" }).catch(() => {});
  state.user = null; go("#/connexion");
};
async function route() {
  clearInterval(state.poll);
  if (!state.user) {
    try { state.user = await api("/api/compte"); } catch { state.user = null; }
  }
  const nav = document.getElementById("usernav");
  nav.hidden = !state.user;
  if (state.user) document.getElementById("username").textContent = state.user.nom;
  const h = location.hash || "#/";
  if (!state.user) return viewAuth(h.includes("inscription") ? "inscription" : "connexion");
  const m = h.match(/^#\/projet\/(\d+)(?:\/(\w+))?/);
  if (m) return viewProject(Number(m[1]), m[2] || state.tab || "plan");
  return viewProjects();
}

// ------------------------------------------------------------------ connexion
function viewAuth(mode) {
  const signup = mode === "inscription";
  $app.innerHTML = `
  <section class="card auth">
    <h1>${signup ? "Créer un compte" : "Connexion"}</h1>
    <p class="muted small">Modélisation et dimensionnement de structures à partir des plans d'architecte.</p>
    <form id="f">
      ${signup ? `<label for="nom">Nom</label><input id="nom" autocomplete="name" required>` : ""}
      <label for="email">Adresse e-mail</label><input id="email" type="email" autocomplete="email" required>
      <label for="pw">Mot de passe${signup ? " (8 caractères minimum)" : ""}</label>
      <input id="pw" type="password" autocomplete="${signup ? "new-password" : "current-password"}" required>
      <div class="actions"><button type="submit">${signup ? "Créer mon compte" : "Se connecter"}</button>
      <a class="button ghost" href="#/${signup ? "connexion" : "inscription"}">${signup ? "J'ai déjà un compte" : "Créer un compte"}</a></div>
      <p id="err" class="small" style="color:var(--ko)"></p>
    </form>
  </section>`;
  document.getElementById("f").onsubmit = async (e) => {
    e.preventDefault();
    const body = { email: email.value, mot_de_passe: pw.value };
    if (signup) body.nom = document.getElementById("nom").value;
    try {
      state.user = await api(`/api/compte/${signup ? "inscription" : "connexion"}`, { json: body });
      go("#/");
    } catch (er) { document.getElementById("err").textContent = er.message; }
  };
}

// ------------------------------------------------------------------ projets
async function viewProjects() {
  $app.innerHTML = `<div class="spinner"></div>`;
  const list = await api("/api/projets");
  $app.innerHTML = `
  <section class="card">
    <h1>Mes projets</h1>
    <form id="newp" class="actions" style="margin-top:6px">
      <input id="pname" placeholder="Nom du nouveau projet (ex. Immeuble R+3 Cocody)" style="flex:1;min-width:220px" required>
      <button type="submit">Créer le projet</button>
    </form>
  </section>
  <section class="grid">
    ${list.length ? list.map((p) => `
      <article class="card project-card" tabindex="0" data-id="${p.id}">
        <h3 style="margin-top:0">${esc(p.nom)}</h3>
        <div class="small muted">${esc(p.statut)} · modifié le ${when(p.modifie)}</div>
        <div class="small" style="margin-top:6px"><span class="badge">${esc(p.role)}</span>
        ${p.role !== "proprietaire" ? `<span class="muted"> partagé par ${esc(p.proprietaire)}</span>` : ""}</div>
      </article>`).join("") : `<p class="muted">Aucun projet pour l'instant : créez-en un, puis importez le plan de l'architecte.</p>`}
  </section>`;
  document.getElementById("newp").onsubmit = async (e) => {
    e.preventDefault();
    const p = await api("/api/projets", { json: { nom: pname.value } });
    go(`#/projet/${p.id}/plan`);
  };
  document.querySelectorAll(".project-card").forEach((el) => {
    const open = () => go(`#/projet/${el.dataset.id}/plan`);
    el.onclick = open;
    el.onkeydown = (e) => { if (e.key === "Enter") open(); };
  });
}

// ------------------------------------------------------------------ projet
const TABS = [["plan", "Plan & niveaux"], ["hypotheses", "Hypothèses"], ["geotech", "Géotechnique"],
  ["calcul", "Calcul"], ["modele", "Modèle 2D / 3D"], ["fichiers", "Plans & note"], ["equipe", "Équipe"]];

async function loadProject(pid) { state.project = await api(`/api/projets/${pid}`); return state.project; }

async function viewProject(pid, tab) {
  state.tab = tab;
  if (!state.project || state.project.id !== pid) { $app.innerHTML = `<div class="spinner"></div>`; state.model = null; }
  try { await loadProject(pid); } catch (e) { $app.innerHTML = `<p>${esc(e.message)}</p>`; return; }
  const p = state.project;
  $app.innerHTML = `
  <section>
    <a href="#/" class="small">← Mes projets</a>
    <h1>${esc(p.nom)}</h1>
    <div class="small muted">${esc(p.statut)} · votre rôle : <span class="badge">${esc(p.role)}</span>
      ${p.role === "lecteur" ? " (consultation seule)" : ""}</div>
    <nav class="tabs" role="tablist">${TABS.map(([k, l]) =>
      `<button role="tab" aria-selected="${k === tab}" data-tab="${k}">${l}</button>`).join("")}</nav>
    <div id="pane"></div>
  </section>`;
  document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => go(`#/projet/${pid}/${b.dataset.tab}`)));
  const pane = document.getElementById("pane");
  ({ plan: paneplan, hypotheses: panehyp, geotech: panegeo, calcul: panecalc, modele: panemodel,
     fichiers: panefiles, equipe: paneteam }[tab] || paneplan)(pane, p);
  const job = p.tache;
  if (job && (job.status === "en_attente" || job.status === "en_cours")) watchJob(job.id);
}

function jobBanner(job) {
  if (!job) return "";
  const lbl = { analyse: "Analyse du plan", calcul: "Calcul" }[job.kind] || job.kind;
  if (job.status === "en_attente" || job.status === "en_cours")
    return `<p><span class="spinner"></span> ${lbl} en cours…</p>`;
  if (job.status === "erreur") return `<p class="badge ko">${lbl} : échec</p><details><summary>Détails</summary><div class="log">${esc(job.error)}\n${esc(job.log)}</div></details>`;
  return `<p class="small muted">${lbl} terminé le ${when(job.finished)}.</p>`;
}
function watchJob(jid) {
  clearInterval(state.poll);
  state.poll = setInterval(async () => {
    const j = await api(`/api/taches/${jid}`).catch(() => null);
    if (!j || j.status === "termine" || j.status === "erreur") {
      clearInterval(state.poll);
      if (j) toast(j.status === "termine" ? "Terminé." : "Échec : voir le détail.");
      state.model = null;
      viewProject(state.project.id, state.tab);
    }
  }, 1500);
}

// --- Plan & niveaux
function paneplan(el, p) {
  const a = p.analyse, cfg = p.configuration, lec = cfg.lecture || {};
  el.innerHTML = `
  <section class="card">
    <h2 style="margin-top:0">Plan de l'architecte</h2>
    <p class="small muted">DWG, DXF ou PDF vectoriel. Un DWG peut contenir toutes les planches (RDC, étages, coupes, façades).</p>
    ${cfg.projet.plan ? `<p>Plan actuel : <b>${esc(cfg.projet.plan.split("/").pop())}</b></p>` : ""}
    ${canEdit() ? `<div class="drop" id="drop"><p>Déposez le fichier ici ou</p>
      <label class="button" style="display:inline-flex;color:#fff">Choisir un fichier
      <input type="file" id="file" accept=".dwg,.dxf,.pdf" hidden></label></div>` : ""}
    ${jobBanner(p.tache && p.tache.kind === "analyse" ? p.tache : null)}
  </section>
  ${a ? `<section class="card">
    <h2 style="margin-top:0">Planches du dessin</h2>
    <div class="table-wrap"><table><tr><th>N°</th><th>Titre</th><th>Type</th><th>Taille (m)</th></tr>
    ${a.planches.map((s) => `<tr><td>${s.numero}</td><td>${esc(s.titre)}</td><td>${s.plan ? "plan" : "autre"}</td><td>${s.taille.join(" × ")}</td></tr>`).join("") || `<tr><td colspan="4" class="muted">Dessin d'une seule planche.</td></tr>`}
    </table></div>
    <h2>Niveaux</h2>
    ${a.multi ? `<p class="small muted">Niveaux et hauteurs lus sur les coupes et façades ; corrigez si besoin.</p>
    <div class="table-wrap"><table><tr><th>Niveau</th><th>Altitude</th><th>Hauteur (m)</th><th>Planche</th><th>Choix</th></tr>
    ${a.niveaux.map((n) => `<tr><td>${esc(n.nom)}</td><td>+${fmt(n.altitude, 2)}</td>
      <td><input data-h="${esc(n.code)}" type="number" step="0.01" min="2" max="8" value="${n.hauteur}" ${canEdit() ? "" : "disabled"} style="max-width:110px"></td>
      <td><select data-s="${esc(n.code)}" ${canEdit() ? "" : "disabled"}>${a.planches.filter((s) => s.plan).map((s) =>
        `<option value="${s.numero}" ${s.numero === n.planche ? "selected" : ""}>${s.numero}. ${esc(s.titre)}</option>`).join("")}</select></td>
      <td class="small muted">${esc(n.raison)}</td></tr>`).join("")}
    </table></div>` : `<p class="small muted">Pas de coupes cotées : le plan est utilisé pour tous les niveaux.</p>
    <div class="row"><div><label>Nombre de planchers</label><input id="nlev" type="number" min="1" max="60" value="${lec.niveaux || 1}" ${canEdit() ? "" : "disabled"}></div>
    <div><label>Hauteur d'étage (m)</label><input id="hlev" type="number" step="0.01" value="${lec.hauteur || 3}" ${canEdit() ? "" : "disabled"}></div>
    ${a.planches.some((s) => s.plan) ? `<div><label>Planche de l'étage courant</label><select id="pl" ${canEdit() ? "" : "disabled"}>${a.planches.filter((s) => s.plan).map((s) =>
      `<option value="${s.numero}" ${String(s.numero) === String(lec.planche) ? "selected" : ""}>${s.numero}. ${esc(s.titre)}</option>`).join("")}</select></div>` : ""}</div>`}
    <div class="row">
      <div><label>Calque des poteaux (vide = automatique)</label><input id="calque" value="${esc(lec.calque_poteaux || "")}" ${canEdit() ? "" : "disabled"}></div>
      <div><label>Échelle d'un PDF (ex. 100)</label><input id="ech" type="number" value="${lec.echelle || ""}" ${canEdit() ? "" : "disabled"}></div>
    </div>
    ${a.notes.length ? `<details><summary class="small">Remarques de lecture (${a.notes.length})</summary><ul class="small warnings">${a.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></details>` : ""}
    ${canEdit() ? `<div class="actions"><button id="save">Enregistrer</button><button class="ghost" id="calc">Enregistrer et calculer</button></div>` : ""}
  </section>` : ""}`;
  if (canEdit()) {
    const send = async (file) => {
      const fd = new FormData(); fd.append("fichier", file);
      toast("Envoi du plan…");
      const r = await api(`/api/projets/${p.id}/plan`, { method: "POST", body: fd }).catch((e) => toast(e.message));
      if (r) { toast("Plan reçu : analyse en cours."); watchJob(r.tache); viewProject(p.id, "plan"); }
    };
    const f = document.getElementById("file");
    if (f) f.onchange = () => f.files[0] && send(f.files[0]);
    const drop = document.getElementById("drop");
    if (drop) {
      drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
      drop.ondragleave = () => drop.classList.remove("over");
      drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); if (e.dataTransfer.files[0]) send(e.dataTransfer.files[0]); };
    }
  }
  const save = async (thenCalc) => {
    const lecture = { calque_poteaux: calque.value.trim() || null, echelle: ech.value ? Number(ech.value) : null };
    if (a && a.multi) {
      lecture.hauteurs = [...el.querySelectorAll("[data-h]")].map((i) => `${i.dataset.h}=${i.value}`).join(",");
      lecture.affectation = [...el.querySelectorAll("[data-s]")].map((s) => `${s.dataset.s}=${s.value}`).join(",");
    } else {
      lecture.niveaux = Number(nlev.value); lecture.hauteur = Number(hlev.value);
      const pl = document.getElementById("pl"); if (pl) lecture.planche = pl.value;
    }
    await api(`/api/projets/${p.id}/configuration`, { method: "PUT", json: { lecture } });
    toast("Enregistré.");
    if (thenCalc) runCalc(p.id); else viewProject(p.id, "plan");
  };
  const sb = document.getElementById("save"); if (sb) sb.onclick = () => save(false);
  const cb = document.getElementById("calc"); if (cb) cb.onclick = () => save(true);
}

// --- Hypothèses
const FIELDS = [
  ["reglement", "norme", "Règlement", "select", [["bael", "BAEL 91 mod. 99"], ["ec2", "Eurocode 2"]]],
  ["reglement", "fc", "Béton fc28 / fck (MPa)", "number"],
  ["reglement", "fe", "Acier fe / fyk (MPa)", "number"],
  ["reglement", "enrobage", "Enrobage (m)", "number"],
  ["charges", "plancher", "Type de plancher", "select", [["corps_creux", "Corps creux (1 sens)"], ["dalle_pleine", "Dalle pleine (2 sens)"]]],
  ["charges", "g_plancher", "Poids propre plancher (kN/m²)", "number"],
  ["charges", "g_revetement", "Revêtements + cloisons (kN/m²)", "number"],
  ["charges", "q", "Exploitation étage courant (kN/m²)", "number"],
  ["charges", "g_terrasse", "Étanchéité terrasse (kN/m²)", "number"],
  ["charges", "q_terrasse", "Exploitation terrasse (kN/m²)", "number"],
  ["charges", "facade", "Maçonnerie de façade (kN/m)", "number"],
  ["charges", "degression", "Dégression des charges d'exploitation", "checkbox"],
  ["sol", "sol", "Contrainte du sol imposée (MPa, vide = rapport géotechnique)", "number"],
];
function panehyp(el, p) {
  const cfg = p.configuration;
  el.innerHTML = `<section class="card"><h2 style="margin-top:0">Hypothèses de calcul</h2>
    <p class="small muted">Les charges particulières des locaux (balcons, stockage, locaux techniques…) sont lues sur le plan ; ces valeurs s'appliquent au reste du plancher.</p>
    <form id="hf"><div class="row">${FIELDS.map(([sec, key, label, type, opts]) => {
      const v = (cfg[sec] || {})[key]; const dis = canEdit() ? "" : "disabled";
      if (type === "select") return `<div><label>${label}</label><select data-k="${sec}.${key}" ${dis}>${opts.map(([o, l]) => `<option value="${o}" ${o === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>`;
      if (type === "checkbox") return `<div><label><input type="checkbox" data-k="${sec}.${key}" ${v !== false ? "checked" : ""} ${dis}> ${label}</label></div>`;
      return `<div><label>${label}</label><input type="number" step="any" data-k="${sec}.${key}" value="${v ?? ""}" ${dis}></div>`;
    }).join("")}</div>
    ${canEdit() ? `<div class="actions"><button type="submit">Enregistrer</button><button type="button" class="ghost" id="hc">Enregistrer et calculer</button></div>` : ""}
    </form></section>`;
  const collect = () => {
    const body = {};
    el.querySelectorAll("[data-k]").forEach((i) => {
      const [sec, key] = i.dataset.k.split(".");
      body[sec] = body[sec] || {};
      body[sec][key] = i.type === "checkbox" ? i.checked : i.tagName === "SELECT" ? i.value : (i.value === "" ? null : Number(i.value));
    });
    if (body.reglement && body.reglement.norme === "ec2" && body.reglement.fe === 400) body.reglement.fe = 500;
    return body;
  };
  const f = document.getElementById("hf");
  f.onsubmit = async (e) => { e.preventDefault(); await api(`/api/projets/${p.id}/configuration`, { method: "PUT", json: collect() }); toast("Hypothèses enregistrées."); };
  const hc = document.getElementById("hc");
  if (hc) hc.onclick = async () => { await api(`/api/projets/${p.id}/configuration`, { method: "PUT", json: collect() }); runCalc(p.id); };
}

// --- Géotechnique
const GEO = [["contrainte_admissible_els", "Contrainte admissible ELS (MPa)", "number"], ["contrainte_elu", "Contrainte ELU (MPa)", "number"],
  ["profondeur_ancrage", "Profondeur d'ancrage (m)", "number"], ["type_fondation", "Type de fondation", "select"],
  ["nappe", "Nappe (m sous TN ou « absente »)", "text"], ["tassement", "Tassement (cm)", "number"],
  ["classe_sismique", "Classe de sol sismique", "text"], ["charge_pieu", "Charge admissible par pieu (kN)", "number"],
  ["diametre_pieu", "Diamètre des pieux (m)", "number"]];
function panegeo(el, p) {
  const g = p.geotech;
  el.innerHTML = `<section class="card"><h2 style="margin-top:0">Rapport géotechnique</h2>
    <p class="small muted">PDF texte, TXT ou DOCX. Les valeurs sont extraites avec la phrase du rapport d'où elles viennent ; vérifiez-les puis validez.</p>
    ${canEdit() ? `<label class="button" style="display:inline-flex;color:#fff">Importer le rapport<input type="file" id="gf" accept=".pdf,.txt,.docx" hidden></label>` : ""}
    ${g ? `<form id="gform" style="margin-top:12px">
      ${g.valide ? `<p class="badge ok">Validé</p>` : `<p class="badge ko">À valider par l'ingénieur</p>`}
      <p class="small muted">Rapport : ${esc(g.fichier)}</p>
      <div class="table-wrap"><table><tr><th>Donnée</th><th>Valeur</th><th>Extrait du rapport</th></tr>
      ${GEO.map(([k, lab, type]) => {
        const v = g[k]; const val = v ? v.value : ""; const dis = canEdit() ? "" : "disabled";
        const input = type === "select"
          ? `<select data-g="${k}" ${dis}>${["", "superficielles", "filantes", "radier", "pieux"].map((o) => `<option ${o === val ? "selected" : ""}>${o}</option>`).join("")}</select>`
          : `<input data-g="${k}" ${type === "number" ? 'type="number" step="any"' : ""} value="${esc(val)}" ${dis}>`;
        return `<tr><td>${lab}</td><td style="min-width:140px">${input}</td><td class="source">${v ? esc((v.page ? `p.${v.page} : ` : "") + v.source) : "—"}</td></tr>`;
      }).join("")}</table></div>
      ${(g.remarques || []).map((r) => `<p class="small" style="color:var(--warn)">${esc(r)}</p>`).join("")}
      ${canEdit() ? `<label><input type="checkbox" id="gval" ${g.valide ? "checked" : ""}> J'ai vérifié ces valeurs : elles sont validées</label>
      <div class="actions"><button type="submit">Enregistrer</button></div>` : ""}
    </form>` : `<p class="muted">Aucun rapport importé : la contrainte du sol des hypothèses (ou 0,20 MPa) est utilisée.</p>`}
  </section>`;
  const gf = document.getElementById("gf");
  if (gf) gf.onchange = async () => {
    const fd = new FormData(); fd.append("fichier", gf.files[0]);
    toast("Lecture du rapport…");
    await api(`/api/projets/${p.id}/geotech`, { method: "POST", body: fd }).then(() => viewProject(p.id, "geotech")).catch((e) => toast(e.message));
  };
  const form = document.getElementById("gform");
  if (form && canEdit()) form.onsubmit = async (e) => {
    e.preventDefault();
    const body = { ...g, valide: gval.checked };
    el.querySelectorAll("[data-g]").forEach((i) => {
      const k = i.dataset.g; const raw = i.value.trim();
      if (!raw) { body[k] = null; return; }
      const val = i.type === "number" ? Number(raw) : raw;
      const prev = g[k] || {};
      body[k] = { value: val, unit: prev.unit || "", source: prev.value === val ? prev.source : "saisie de l'ingénieur", page: prev.value === val ? prev.page : null };
    });
    await api(`/api/projets/${p.id}/geotech`, { method: "PUT", json: body });
    toast("Données géotechniques enregistrées."); viewProject(p.id, "geotech");
  };
}

// --- Calcul
async function runCalc(pid) {
  const r = await api(`/api/projets/${pid}/calcul`, { method: "POST" }).catch((e) => { toast(e.message); return null; });
  if (r) { toast("Calcul lancé."); go(`#/projet/${pid}/calcul`); watchJob(r.tache); }
}
function panecalc(el, p) {
  const r = p.resultats;
  const job = p.tache && p.tache.kind === "calcul" ? p.tache : null;
  el.innerHTML = `<section class="card"><h2 style="margin-top:0">Calcul</h2>
    <p class="small muted">Lecture des plans, descente de charges, dimensionnement (poteaux, poutres, transferts, balcons, escaliers, fondations), plans et note de calcul.</p>
    ${canEdit() ? `<button id="run" ${job && ["en_attente", "en_cours"].includes(job.status) ? "disabled" : ""}>Lancer le calcul</button>` : ""}
    ${jobBanner(job)}
  </section>
  ${r ? `<section class="card"><h2 style="margin-top:0">Résultats — ${esc(r.norme)}</h2>
    <div class="kpis">
      <div class="kpi"><span class="muted small">Niveaux</span><b>${(r.niveaux || []).length}</b></div>
      <div class="kpi"><span class="muted small">Tronçons de poteaux</span><b>${r.n_poteaux}</b></div>
      <div class="kpi"><span class="muted small">Poutres</span><b>${r.n_poutres}</b></div>
      <div class="kpi"><span class="muted small">Fondations</span><b>${esc(r.fondations || "")}</b></div>
      <div class="kpi"><span class="muted small">Non vérifiés</span><b style="color:${r.non_verifies ? "var(--ko)" : "var(--ok)"}">${r.non_verifies}</b></div>
    </div>
    ${r.metre ? `<h3>Métré estimatif</h3><div class="table-wrap"><table><tr><th>Élément</th><th>Béton (m³)</th><th>Acier (kg)</th></tr>
      ${Object.entries(r.metre).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${fmt(v.beton_m3, 2)}</td><td>${fmt(v.acier_kg, 0)}</td></tr>`).join("")}</table></div>` : ""}
    <h3>Points à vérifier (${(r.avertissements || []).length})</h3>
    <details ${r.non_verifies ? "open" : ""}><summary class="small">Afficher</summary><ul class="small warnings">${(r.avertissements || []).map((w) => `<li>${esc(w)}</li>`).join("")}</ul></details>
    <div class="actions"><a class="button ghost" href="#/projet/${p.id}/modele">Voir le modèle</a><a class="button ghost" href="#/projet/${p.id}/fichiers">Plans et note</a></div>
  </section>` : ""}
  ${job && job.log ? `<section class="card"><h3 style="margin-top:0">Journal du calcul</h3><div class="log">${esc(job.log)}</div></section>` : ""}`;
  const b = document.getElementById("run"); if (b) b.onclick = () => runCalc(p.id);
}

// --- Fichiers
const FILE_INFO = [[/^note_de_calcul\.pdf$/, "Note de calcul (PDF)"], [/^note_de_calcul\.html$/, "Note de calcul (HTML)"],
  [/^coffrage_/, "Plan de coffrage (DXF)"], [/^plan_coffrage/, "Plan de coffrage (DXF)"], [/^plan_fondations/, "Plan de fondations (DXF)"],
  [/^plans_ferraillage/, "Plans de ferraillage (DXF)"], [/^controle/, "Plan de contrôle du modèle (DXF)"],
  [/^projet\.json|^modele\.json/, "Modèle structurel (JSON)"], [/^resultats\.json/, "Résultats (JSON)"], [/^geotech/, "Données géotechniques (JSON)"]];
function panefiles(el, p) {
  const files = (p.fichiers || []).filter((f) => f !== "modele_3d.json");
  el.innerHTML = `<section class="card"><h2 style="margin-top:0">Plans d'exécution et note de calcul</h2>
    ${files.length ? `<div class="table-wrap"><table><tr><th>Fichier</th><th>Contenu</th><th></th></tr>
    ${files.map((f) => `<tr><td>${esc(f)}</td><td class="muted small">${esc((FILE_INFO.find(([re]) => re.test(f)) || [, ""])[1])}</td>
      <td><a class="button ghost" href="/api/projets/${p.id}/fichiers/${encodeURIComponent(f)}" download>Télécharger</a></td></tr>`).join("")}
    </table></div>` : `<p class="muted">Lancez le calcul pour produire les plans et la note.</p>`}
  </section>`;
}

// --- Équipe
function paneteam(el, p) {
  el.innerHTML = `<section class="card"><h2 style="margin-top:0">Équipe du projet</h2>
    <div class="table-wrap"><table><tr><th>Nom</th><th>E-mail</th><th>Rôle</th><th></th></tr>
    ${p.membres.map((m) => `<tr><td>${esc(m.name)}</td><td>${esc(m.email)}</td><td><span class="badge">${esc(m.role)}</span></td>
      <td>${isOwner() && m.role !== "proprietaire" ? `<button class="danger" data-rm="${m.id}">Retirer</button>` : ""}</td></tr>`).join("")}
    </table></div>
    ${isOwner() ? `<form id="inv" class="row" style="margin-top:12px">
      <div><label>E-mail du collègue (compte existant)</label><input id="ie" type="email" required></div>
      <div><label>Rôle</label><select id="ir"><option value="editeur">Éditeur (modifie et calcule)</option><option value="lecteur">Lecteur (consulte)</option></select></div>
      <div style="align-self:end"><button type="submit">Ajouter</button></div></form>` : ""}
  </section>
  <section class="card"><h2 style="margin-top:0">Activité</h2>
    <ul class="small warnings">${p.journal.map((a) => `<li><span class="muted">${when(a.ts)}</span> — ${esc(a.name || "")} : ${esc(a.text)}</li>`).join("")}</ul>
  </section>`;
  const f = document.getElementById("inv");
  if (f) f.onsubmit = async (e) => {
    e.preventDefault();
    await api(`/api/projets/${p.id}/membres`, { json: { email: ie.value, role: ir.value } }).then(() => { toast("Membre ajouté."); viewProject(p.id, "equipe"); }).catch((er) => toast(er.message));
  };
  el.querySelectorAll("[data-rm]").forEach((b) => (b.onclick = async () => {
    await api(`/api/projets/${p.id}/membres/${b.dataset.rm}`, { method: "DELETE" }).catch((er) => toast(er.message));
    viewProject(p.id, "equipe");
  }));
}

// --- Modèle 2D / 3D
async function panemodel(el, p) {
  if (!state.model) {
    el.innerHTML = `<div class="spinner"></div>`;
    try { state.model = await api(`/api/projets/${p.id}/modele`); } catch (e) {
      el.innerHTML = `<section class="card"><p class="muted">${esc(e.message)}</p></section>`; return;
    }
  }
  const m = state.model;
  state.storey = Math.min(state.storey, m.niveaux.length - 1);
  el.innerHTML = `<section class="card">
    <div class="viewer-bar">
      <select id="lv">${m.niveaux.map((n, i) => `<option value="${i}" ${i === state.storey ? "selected" : ""}>${esc(n.plancher)} (poteaux ${esc(n.nom)})</option>`).join("")}
      <option value="fond" ${state.storey === -1 ? "selected" : ""}>Fondations</option></select>
      <button class="${state.view === "2d" ? "" : "ghost"}" id="v2">Plan 2D</button>
      <button class="${state.view === "3d" ? "" : "ghost"}" id="v3">Vue 3D</button>
      <span class="small muted">${m.non_verifies ? `<span class="badge ko">${m.non_verifies} non vérifié(s)</span>` : `<span class="badge ok">tout vérifié</span>`}</span>
    </div>
    <div class="viewer" id="vw"></div>
    <div class="legend"><span><i style="background:var(--column)"></i>Poteaux</span><span><i style="background:var(--beam)"></i>Poutres</span>
      <span><i style="background:var(--transfer)"></i>Transferts / non vérifiés</span><span><i style="background:var(--slab)"></i>Contour du plancher</span>
      <span><i style="background:var(--zone)"></i>Locaux à charge particulière</span></div>
    <p class="small muted">Plan : faites glisser pour déplacer, molette ou pincement pour zoomer, touchez un élément pour ses résultats.</p>
  </section>`;
  document.getElementById("lv").onchange = (e) => { state.storey = e.target.value === "fond" ? -1 : Number(e.target.value); panemodel(el, p); };
  document.getElementById("v2").onclick = () => { state.view = "2d"; panemodel(el, p); };
  document.getElementById("v3").onclick = () => { state.view = "3d"; panemodel(el, p); };
  const vw = document.getElementById("vw");
  if (state.view === "3d") {
    const mod = await import("/static/viewer3d.js");
    mod.render3d(vw, m, state.storey);
  } else {
    render2d(vw, m, state.storey);
  }
}

function render2d(host, m, k) {
  const css = getComputedStyle(document.documentElement);
  const col = (v) => css.getPropertyValue(v).trim();
  const lvl = k >= 0 ? m.niveaux[k] : m.niveaux[0];
  const pts = [];
  lvl.colonnes.forEach((c) => pts.push([c.x, c.y]));
  lvl.contour.forEach((s) => { pts.push([s[0], s[1]]); pts.push([s[2], s[3]]); });
  if (k < 0) m.semelles.forEach((f) => { pts.push([f.x - f.A / 2, f.y - f.B / 2]); pts.push([f.x + f.A / 2, f.y + f.B / 2]); });
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const x0 = Math.min(...xs) - 2.5, x1 = Math.max(...xs) + 2.5, y0 = Math.min(...ys) - 2.5, y1 = Math.max(...ys) + 2.5;
  const Y = (y) => (y0 + y1) - y; // axe Y vers le haut
  let svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${x0} ${y0} ${x1 - x0} ${y1 - y0}" id="plan2d">`;
  svg += `<g stroke="${col("--line")}" stroke-width="0.03" stroke-dasharray="0.3 0.15">`;
  lvl.axes_x.forEach(([x, n]) => { svg += `<line x1="${x}" y1="${y0 + 1}" x2="${x}" y2="${y1 - 1}"/><text x="${x}" y="${y0 + 0.8}" font-size="0.45" text-anchor="middle" fill="${col("--muted")}" stroke="none">${esc(n)}</text>`; });
  lvl.axes_y.forEach(([y, n]) => { svg += `<line x1="${x0 + 1}" y1="${Y(y)}" x2="${x1 - 1}" y2="${Y(y)}"/><text x="${x0 + 0.6}" y="${Y(y) + 0.15}" font-size="0.45" text-anchor="middle" fill="${col("--muted")}" stroke="none">${esc(n)}</text>`; });
  svg += `</g><g stroke="${col("--slab")}" stroke-width="0.06">${lvl.contour.map((s) => `<line x1="${s[0]}" y1="${Y(s[1])}" x2="${s[2]}" y2="${Y(s[3])}"/>`).join("")}</g>`;
  if (k >= 0) {
    svg += `<g stroke="${col("--zone")}" stroke-width="0.05">`;
    lvl.zones.filter((z) => z.type !== "local" || (z.q !== null && z.usage !== "Bureaux")).forEach((z, zi) => {
      svg += z.contour.map((s) => `<line x1="${s[0]}" y1="${Y(s[1])}" x2="${s[2]}" y2="${Y(s[3])}" data-z="${zi}"/>`).join("");
    });
    svg += `</g>`;
    svg += lvl.poutres.map((b, i) => {
      const c = b.transfert ? col("--transfer") : (b.ok ? col("--beam") : col("--ko"));
      return `<line x1="${b.x1}" y1="${Y(b.y1)}" x2="${b.x2}" y2="${Y(b.y2)}" stroke="${c}" stroke-width="${Math.max(b.b, 0.18)}" stroke-opacity="0.55" data-b="${i}" class="hit"/>`;
    }).join("");
  } else {
    svg += m.semelles.map((f, i) => `<rect x="${f.x - f.A / 2}" y="${Y(f.y) - f.B / 2}" width="${f.A}" height="${f.B}" fill="none" stroke="${f.ok ? col("--accent") : col("--ko")}" stroke-width="0.06" data-f="${i}" class="hit"/>`).join("");
  }
  svg += lvl.colonnes.map((c, i) => `<rect x="${c.x - c.b / 2}" y="${Y(c.y) - c.h / 2}" width="${c.b}" height="${c.h}" fill="${c.ok ? col("--column") : col("--ko")}" data-c="${i}" class="hit"/>`).join("");
  svg += lvl.colonnes.map((c) => `<text x="${c.x + c.b / 2 + 0.1}" y="${Y(c.y) - c.h / 2 - 0.08}" font-size="0.3" fill="${col("--muted")}">${esc(c.id)}</text>`).join("");
  svg += `</svg>`;
  host.innerHTML = svg + `<div class="info" id="info" hidden></div>`;
  const el = host.querySelector("svg"), info = host.querySelector("#info");
  // sélection (toucher / clic sans glissement)
  const select = (t) => {
    let html = "";
    if (t.dataset.c !== undefined) { const c = lvl.colonnes[t.dataset.c]; html = `<b>Poteau ${esc(c.id)}</b><br>${fmt(c.b * 100, 0)}×${fmt(c.h * 100, 0)} cm<br>Nu = ${fmt(c.nu, 0)} kN<br>${esc(c.armatures)} — ${esc(c.cadres)}<br>${c.ok ? '<span class="badge ok">vérifié</span>' : '<span class="badge ko">non vérifié</span>'}`; }
    else if (t.dataset.b !== undefined) { const b = lvl.poutres[t.dataset.b]; html = `<b>Poutre ${esc(b.id)}</b>${b.transfert ? " (transfert)" : ""}<br>${fmt(b.b * 100, 0)}×${fmt(b.h * 100, 0)} cm<br>Inf. ${esc(b.inf)} — Sup. ${esc(b.sup)}<br>${esc(b.cadres)}<br>${b.ok ? '<span class="badge ok">vérifiée</span>' : '<span class="badge ko">non vérifiée</span>'}`; }
    else if (t.dataset.f !== undefined) { const f = m.semelles[t.dataset.f]; html = `<b>Semelle ${esc(f.id)}</b>${f.sous_mur ? " (sous mur)" : ""}<br>${fmt(f.A * 100, 0)}×${fmt(f.B * 100, 0)}×${fmt(f.h * 100, 0)} cm`; }
    info.hidden = !html; info.innerHTML = html;
  };
  // déplacement / zoom (souris, molette, tactile)
  let vb = [x0, y0, x1 - x0, y1 - y0];
  const apply = () => el.setAttribute("viewBox", vb.join(" "));
  const toWorld = (cx, cy) => { const r = el.getBoundingClientRect(); const s = Math.max(vb[2] / r.width, vb[3] / r.height); return [vb[0] + (cx - r.left) * s, vb[1] + (cy - r.top) * s, s]; };
  el.addEventListener("wheel", (e) => {
    e.preventDefault(); const [wx, wy] = toWorld(e.clientX, e.clientY); const f = e.deltaY > 0 ? 1.15 : 1 / 1.15;
    vb = [wx - (wx - vb[0]) * f, wy - (wy - vb[1]) * f, vb[2] * f, vb[3] * f]; apply();
  }, { passive: false });
  const ptrs = new Map(); let last = null; let down = null;
  el.addEventListener("pointerdown", (e) => {
    ptrs.set(e.pointerId, [e.clientX, e.clientY]); last = null;
    down = { x: e.clientX, y: e.clientY, target: e.target, moved: false };
  });
  el.addEventListener("pointermove", (e) => {
    if (!ptrs.has(e.pointerId)) return;
    if (down && Math.hypot(e.clientX - down.x, e.clientY - down.y) > 6) {
      if (!down.moved) { down.moved = true; el.setPointerCapture(e.pointerId); }
    }
    if (down && !down.moved) return;
    const prev = ptrs.get(e.pointerId); ptrs.set(e.pointerId, [e.clientX, e.clientY]);
    if (ptrs.size === 1) { const [, , s] = toWorld(0, 0); vb[0] -= (e.clientX - prev[0]) * s; vb[1] -= (e.clientY - prev[1]) * s; apply(); }
    else if (ptrs.size === 2) {
      const [a, b] = [...ptrs.values()]; const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      if (last) { const [wx, wy] = toWorld((a[0] + b[0]) / 2, (a[1] + b[1]) / 2); const f = last / d; vb = [wx - (wx - vb[0]) * f, wy - (wy - vb[1]) * f, vb[2] * f, vb[3] * f]; apply(); }
      last = d;
    }
  });
  const up = (e) => {
    if (down && !down.moved && ptrs.size === 1) select(down.target);
    ptrs.delete(e.pointerId); last = null; if (!ptrs.size) down = null;
  };
  el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
}

route();
