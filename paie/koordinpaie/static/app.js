// Koordin Paie — interface (sans dépendance)
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const app = $("#app");
let moi = null;

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fcfa = (v) => (v === null || v === undefined || v === "") ? "" : Math.round(Number(v)).toLocaleString("fr-FR").replace(/ /g, " ");
const pct = (t) => t ? `${(t * 100).toLocaleString("fr-FR", { maximumFractionDigits: 2 })} %` : "";
const dfr = (d) => d ? new Date(d + "T00:00:00").toLocaleDateString("fr-FR") : "";
const MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];
const TYPES = { CDI: "CDI", CDD: "CDD", JOURNALIER: "Journalier" };
const MODES = { mensuel: "Mensuel", journalier: "Journalier", horaire: "Horaire" };
const peutModifier = () => moi && moi.role !== "lecteur";

function toast(msg, ko = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = ko ? "ko" : ""; t.hidden = false;
  clearTimeout(t._h); t._h = setTimeout(() => (t.hidden = true), ko ? 6000 : 2800);
}

async function api(url, opts = {}) {
  const o = { method: opts.method || "GET", headers: {} };
  if (opts.body !== undefined) { o.body = JSON.stringify(opts.body); o.headers["Content-Type"] = "application/json"; }
  const r = await fetch(url, o);
  if (r.status === 401 && !url.startsWith("/api/connexion")) { moi = null; route(); throw new Error("Connexion requise."); }
  const data = r.headers.get("content-type")?.includes("json") ? await r.json() : null;
  if (!r.ok) throw new Error(data?.detail ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail)) : `Erreur ${r.status}`);
  return data;
}
const essayer = (fn) => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };

// ------------------------------------------------------------------ formulaires
// champ : [nom, libellé, type, options]  type : text, number, date, select, check, textarea
function champs(defs, val = {}) {
  return defs.map(([n, l, t = "text", o = {}]) => {
    const v = val[n] ?? o.defaut ?? "";
    const ro = (o.lecture ?? (moi && !peutModifier())) ? "disabled" : "";
    const req = o.requis ? "required" : "";
    if (t === "check") return `<label class="check"><input type="checkbox" name="${n}" ${v ? "checked" : ""} ${ro}> ${esc(l)}</label>`;
    if (t === "select") return `<label>${esc(l)}<select name="${n}" ${ro} ${req}>${Object.entries(o.choix).map(([k, x]) => `<option value="${esc(k)}" ${String(v) === k ? "selected" : ""}>${esc(x)}</option>`).join("")}</select></label>`;
    if (t === "textarea") return `<label>${esc(l)}<textarea name="${n}" rows="2" ${ro}>${esc(v)}</textarea></label>`;
    const extra = t === "number" ? `step="${o.pas ?? "any"}" min="${o.min ?? 0}" inputmode="decimal"` : "";
    return `<label>${esc(l)}<input type="${t}" name="${n}" value="${esc(v)}" ${extra} ${ro} ${req} ${o.place ? `placeholder="${esc(o.place)}"` : ""}></label>`;
  }).join("");
}
function lire(form) {
  const d = {};
  $$("input, select, textarea", form).forEach((el) => {
    if (!el.name || el.closest(".lignes-primes")) return;
    if (el.type === "checkbox") d[el.name] = el.checked;
    else if (el.type === "number") d[el.name] = el.value === "" ? "" : Number(el.value);
    else d[el.name] = el.value.trim();
  });
  return d;
}

// liste de primes / retenues : [{libelle, montant, imposable}]
function editeurLignes(el, lignes = [], { imposable = true, ajout = "Ajouter une prime", lecture } = {}) {
  el.classList.add("lignes-primes");
  const ro = lecture ?? !peutModifier();
  const ligne = (p = {}) => {
    const div = document.createElement("div");
    div.className = "ligne";
    div.innerHTML = `<input placeholder="Libellé" value="${esc(p.libelle || "")}" data-k="libelle" ${ro ? "disabled" : ""}>
      <input type="number" min="0" step="any" placeholder="Montant" value="${esc(p.montant ?? "")}" data-k="montant" ${ro ? "disabled" : ""}>
      ${imposable ? `<label class="check small"><input type="checkbox" data-k="imposable" ${p.imposable === false ? "" : "checked"} ${ro ? "disabled" : ""}> imposable</label>` : "<span></span>"}
      ${ro ? "" : `<button type="button" class="ghost small" aria-label="Retirer">✕</button>`}`;
    div.querySelector("button")?.addEventListener("click", () => div.remove());
    return div;
  };
  const liste = document.createElement("div");
  lignes.forEach((p) => liste.append(ligne(p)));
  el.replaceChildren(liste);
  if (!ro) {
    const b = document.createElement("button");
    b.type = "button"; b.className = "ghost small"; b.textContent = "+ " + ajout;
    b.onclick = () => liste.append(ligne());
    el.append(b);
  }
  return () => $$(".ligne", liste).map((d) => {
    const o = { libelle: $("[data-k=libelle]", d).value.trim(), montant: Number($("[data-k=montant]", d).value || 0) };
    if (imposable) o.imposable = $("[data-k=imposable]", d).checked;
    return o;
  }).filter((p) => p.libelle || p.montant);
}

function dialogue(titre, html, onOk, texteOk = "Enregistrer") {
  const d = document.createElement("dialog");
  d.innerHTML = `<form method="dialog"><h2>${esc(titre)}</h2>${html}<p class="err" hidden></p>
    <div class="row" style="justify-content:flex-end"><button type="button" class="ghost" value="annuler">Annuler</button><button value="ok">${esc(texteOk)}</button></div></form>`;
  document.body.append(d);
  const f = $("form", d);
  $("button[value=annuler]", d).onclick = () => d.close();
  d.addEventListener("close", () => d.remove());
  f.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    try { await onOk(f, d); d.close(); } catch (e) { const p = $(".err", d); p.textContent = e.message; p.hidden = false; }
  });
  d.showModal();
  return d;
}

// ------------------------------------------------------------------ connexion
async function vueConnexion() {
  const etat = await api("/api/etat");
  const premier = etat.premier_compte;
  app.innerHTML = `<div class="card auth"><h1>${premier ? "Créer le compte administrateur" : "Connexion"}</h1>
    <p class="muted small">${premier ? "Premier lancement : ce compte gérera l'entreprise et créera les accès des autres utilisateurs." : "Gestion des contrats et de la paie."}</p>
    <form>${premier ? champs([["nom", "Nom", "text", { requis: true }]]) : ""}
      ${champs([["email", "Adresse électronique", "email", { requis: true }], ["mdp", "Mot de passe" + (premier ? " (8 caractères minimum)" : ""), "password", { requis: true }]])}
      <p class="err" hidden></p><button>${premier ? "Créer le compte" : "Se connecter"}</button></form></div>`;
  $("form", app).onsubmit = async (ev) => {
    ev.preventDefault();
    try {
      await api(premier ? "/api/inscription" : "/api/connexion", { method: "POST", body: lire(ev.target) });
      await demarrer();
    } catch (e) { const p = $(".err", app); p.textContent = e.message; p.hidden = false; }
  };
}

// ------------------------------------------------------------------ tableau de bord
async function vueAccueil() {
  const [sal, alertes, periodes, journal] = await Promise.all([api("/api/salaries"), api("/api/alertes"), api("/api/periodes"), api("/api/journal")]);
  const actifs = sal.filter((s) => s.actif);
  const parType = (t) => actifs.filter((s) => s.contrat?.type === t).length;
  let derniere = null;
  if (periodes.length) derniere = await api(`/api/periodes/${periodes[0].id}`);
  app.innerHTML = `<div class="head"><div><h1>Tableau de bord</h1><p class="muted">${esc(new Date().toLocaleDateString("fr-FR", { dateStyle: "full" }))}</p></div></div>
    <div class="kpis">
      <div class="kpi"><span>Salariés actifs</span><b>${actifs.length}</b></div>
      <div class="kpi"><span>CDI / CDD / journaliers</span><b>${parType("CDI")} / ${parType("CDD")} / ${parType("JOURNALIER")}</b></div>
      ${derniere ? `<div class="kpi"><span>Masse salariale brute — ${esc(derniere.periode.libelle)}</span><b>${fcfa(derniere.totaux.brut)}</b></div>
      <div class="kpi"><span>Coût employeur — ${esc(derniere.periode.libelle)}</span><b>${fcfa(derniere.totaux.cout_employeur)}</b></div>` : `<div class="kpi"><span>Paie</span><b>—</b></div>`}
    </div>
    <div class="split">
      <div class="card"><h2>Alertes</h2>${alertes.length ? alertes.map((a) => `<div class="alerte"><span class="niv ${a.niveau}" title="${a.niveau}"></span><div><a href="#/salaries/${a.salarie_id}">${esc(a.nom)}</a> — ${esc(a.texte)}</div></div>`).join("") : `<p class="muted">Aucune alerte : contrats et fiches à jour.</p>`}</div>
      <div class="card"><h2>Activité récente</h2>${journal.length ? journal.slice(0, 12).map((j) => `<div class="alerte"><span class="small muted" style="flex:none">${new Date(j.ts * 1000).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}</span><div>${esc(j.texte)} <span class="muted small">${esc(j.nom || "")}</span></div></div>`).join("") : `<p class="muted">Rien pour l'instant.</p>`}</div>
    </div>
    ${!sal.length ? `<div class="card vide"><p>Commencez par renseigner <a href="#/parametres">l'entreprise</a>, puis ajoutez vos <a href="#/salaries">salariés et leurs contrats</a>.</p></div>` : ""}`;
}

// ------------------------------------------------------------------ salariés
const CHAMPS_IDENTITE = [
  ["nom", "Nom", "text", { requis: true }], ["prenoms", "Prénoms"], ["matricule", "Matricule", "text", { place: "automatique" }],
  ["sexe", "Sexe", "select", { choix: { "": "—", M: "Masculin", F: "Féminin" } }], ["date_naissance", "Date de naissance", "date"],
  ["lieu_naissance", "Lieu de naissance"], ["nationalite", "Nationalité", "text", { defaut: "Ivoirienne" }], ["piece_identite", "N° pièce d'identité"],
  ["adresse", "Adresse"], ["telephone", "Téléphone", "tel"], ["email", "Courriel", "email"],
];
const CHAMPS_SOCIAL = [
  ["numero_cnps", "N° CNPS"], ["date_embauche", "Date d'embauche", "date", { place: "début du 1er contrat" }],
  ["marie", "Marié(e)", "check"], ["enfants", "Enfants à charge", "number", { pas: 1 }], ["parts", "Parts fiscales imposées", "number", { pas: 0.5, place: "calcul automatique" }],
  ["personnes_cmu", "Personnes à charge affiliées CMU", "number", { pas: 1 }], ["expatrie", "Salarié expatrié (impôt patronal 12 %)", "check"],
];
const CHAMPS_PAIEMENT = [
  ["mode_paiement", "Mode de paiement", "select", { choix: { "virement bancaire": "Virement bancaire", "mobile money": "Mobile money", "chèque": "Chèque", "espèces": "Espèces" } }],
  ["banque", "Banque / opérateur"], ["rib", "RIB / numéro de compte"], ["actif", "Salarié actif", "check", { defaut: true }],
];

async function vueSalaries() {
  const sal = await api("/api/salaries");
  app.innerHTML = `<div class="head"><div><h1>Salariés</h1><p class="muted">${sal.filter((s) => s.actif).length} actif(s) sur ${sal.length}</p></div>
    <div class="row"><input type="search" id="filtre" placeholder="Rechercher…" style="width:220px">${peutModifier() ? `<a class="btn" href="#/salaries/nouveau">+ Nouveau salarié</a>` : ""}</div></div>
    <div class="card">${sal.length ? `<div class="table-wrap"><table><thead><tr><th>Matricule</th><th>Nom et prénoms</th><th>Emploi</th><th>Contrat</th><th class="n">Salaire de base</th><th>Statut</th></tr></thead><tbody>
    ${sal.map((s) => `<tr class="clic" data-id="${s.id}" data-q="${esc((s.matricule + " " + s.nom + " " + s.prenoms + " " + (s.contrat?.poste || "")).toLowerCase())}">
      <td>${esc(s.matricule)}</td><td><b>${esc(s.nom)}</b> ${esc(s.prenoms)}</td><td>${esc(s.contrat?.poste || "")}</td>
      <td>${s.contrat ? `${TYPES[s.contrat.type] || s.contrat.type}${s.contrat.date_fin ? ` <span class="muted small">→ ${dfr(s.contrat.date_fin)}</span>` : ""}` : `<span class="badge warn">aucun contrat</span>`}</td>
      <td class="n">${s.contrat ? fcfa(s.contrat.salaire_base) + (s.contrat.mode && s.contrat.mode !== "mensuel" ? ` <span class="muted small">/${s.contrat.mode === "journalier" ? "jour" : "h"}</span>` : "") : ""}</td>
      <td>${s.actif ? `<span class="badge ok">actif</span>` : `<span class="badge">inactif</span>`}</td></tr>`).join("")}
    </tbody></table></div>` : `<div class="vide">Aucun salarié. ${peutModifier() ? `<a href="#/salaries/nouveau">Ajouter le premier salarié</a>.` : ""}</div>`}</div>`;
  $$("tr.clic", app).forEach((tr) => (tr.onclick = () => (location.hash = `#/salaries/${tr.dataset.id}`)));
  $("#filtre", app).oninput = (e) => { const q = e.target.value.toLowerCase(); $$("tr.clic", app).forEach((tr) => (tr.hidden = !tr.dataset.q.includes(q))); };
}

async function vueSalarie(id) {
  const nouveau = id === "nouveau";
  const s = nouveau ? { actif: true, nationalite: "Ivoirienne" } : await api(`/api/salaries/${id}`);
  app.innerHTML = `<div class="head"><div><a href="#/salaries" class="small">← Salariés</a><h1>${nouveau ? "Nouveau salarié" : `${esc(s.nom)} ${esc(s.prenoms)}`}</h1>
    ${nouveau ? "" : `<p class="muted">Matricule ${esc(s.matricule)} · embauché le ${dfr(s.date_embauche_effective)}</p>`}</div>
    ${!nouveau && peutModifier() ? `<button class="danger" id="suppr">Supprimer</button>` : ""}</div>
    <div class="split">
      <form class="card" id="fiche"><h2>Fiche salarié</h2>
        <fieldset><legend>Identité</legend><div class="grid">${champs(CHAMPS_IDENTITE, s)}</div></fieldset>
        <fieldset><legend>Situation sociale et fiscale</legend><div class="grid">${champs(CHAMPS_SOCIAL, s)}</div></fieldset>
        <fieldset><legend>Paiement</legend><div class="grid">${champs(CHAMPS_PAIEMENT, s)}</div></fieldset>
        ${peutModifier() ? `<button>${nouveau ? "Créer le salarié" : "Enregistrer"}</button>` : ""}
      </form>
      <div>${nouveau ? `<div class="card vide">Enregistrez la fiche pour ajouter un contrat.</div>` : `
        <div class="card"><div class="head" style="margin-bottom:8px"><h2>Contrats</h2>${peutModifier() ? `<button class="small" id="nouv-contrat">+ Nouveau contrat</button>` : ""}</div>
          <div id="contrats">${s.contrats.length ? "" : `<p class="muted">Aucun contrat.</p>`}</div></div>
        <div class="card"><h2>Bulletins de paie</h2>${s.bulletins.length ? `<table><tbody>${s.bulletins.map((b) => `<tr><td>${MOIS[b.mois - 1]} ${b.annee}</td><td>${b.statut === "cloturee" ? `<span class="badge ok">clôturé</span>` : `<span class="badge warn">en cours</span>`}</td><td class="n"><a href="/api/bulletins/${b.id}/pdf" target="_blank">PDF</a></td></tr>`).join("")}</tbody></table>` : `<p class="muted">Aucun bulletin.</p>`}</div>`}
      </div></div>`;
  $("#fiche", app).onsubmit = essayer(async (ev) => {
    ev.preventDefault();
    const d = lire(ev.target);
    if (nouveau) { const r = await api("/api/salaries", { method: "POST", body: d }); toast("Salarié créé."); location.hash = `#/salaries/${r.id}`; }
    else { await api(`/api/salaries/${id}`, { method: "PUT", body: d }); toast("Fiche enregistrée."); vueSalarie(id); }
  });
  if (nouveau) return;
  $("#suppr", app)?.addEventListener("click", essayer(async () => {
    if (!confirm(`Supprimer définitivement ${s.nom} ${s.prenoms}, ses contrats et ses bulletins non clôturés ?`)) return;
    await api(`/api/salaries/${id}`, { method: "DELETE" }); toast("Salarié supprimé."); location.hash = "#/salaries";
  }));
  $("#nouv-contrat", app)?.addEventListener("click", () => formContrat(s, null));
  const box = $("#contrats", app);
  s.contrats.forEach((c) => box.append(carteContrat(s, c)));
}

function carteContrat(s, c) {
  const div = document.createElement("div");
  div.className = "contrat" + (c.statut === "termine" ? " termine" : "");
  const unite = { mensuel: "/ mois", journalier: "/ jour", horaire: "/ heure" }[c.mode || "mensuel"];
  div.innerHTML = `<div class="row" style="justify-content:space-between"><div><b>${TYPES[c.type] || c.type}</b> — ${esc(c.poste || "poste non précisé")} ${c.categorie ? `<span class="muted">(cat. ${esc(c.categorie)})</span>` : ""}</div>
    ${c.statut === "termine" ? `<span class="badge">terminé${c.motif_fin ? " — " + esc(c.motif_fin) : ""}</span>` : `<span class="badge ok">en cours</span>`}</div>
    <p class="small muted" style="margin:.3rem 0">Du ${dfr(c.date_debut)}${c.date_fin ? ` au ${dfr(c.date_fin)}` : ""} · ${fcfa(c.salaire_base)} FCFA ${unite}${c.transport ? ` · transport ${fcfa(c.transport)}` : ""}${c.essai_mois ? ` · essai ${c.essai_mois} mois` : ""}</p>
    ${c.avenants.length ? `<div class="small"><b>Avenants :</b><ul style="margin:.2rem 0 .4rem;padding-left:1.2rem">${c.avenants.map((a) => `<li>${dfr(a.date_effet)} — ${esc(a.objet)} <span class="muted">(${Object.entries(a.modifications).filter(([k]) => k !== "primes_fixes").map(([k, v]) => `${k.replace("_", " ")} : ${typeof v === "number" ? fcfa(v) : esc(v)}`).join(", ")})</span> ${peutModifier() ? `<button class="ghost small" data-suppr-av="${a.id}" aria-label="Supprimer l'avenant">✕</button>` : ""}</li>`).join("")}</ul></div>` : ""}
    <div class="row"><a class="btn small ghost" href="/api/contrats/${c.id}/pdf" target="_blank">Contrat PDF</a>
    ${peutModifier() ? `<button class="small ghost" data-a="modif">Modifier</button>${c.statut !== "termine" ? `<button class="small ghost" data-a="avenant">Avenant</button><button class="small ghost" data-a="fin">Mettre fin</button>` : ""}<button class="small danger" data-a="suppr">Supprimer</button>` : ""}</div>`;
  const recharger = () => vueSalarie(s.id);
  $("[data-a=modif]", div)?.addEventListener("click", () => formContrat(s, c));
  $("[data-a=avenant]", div)?.addEventListener("click", () => formAvenant(s, c));
  $("[data-a=fin]", div)?.addEventListener("click", () => dialogue("Mettre fin au contrat",
    `<div class="grid">${champs([["date_fin", "Dernier jour travaillé", "date", { requis: true, defaut: c.date_fin || new Date().toISOString().slice(0, 10) }],
      ["motif", "Motif", "select", { choix: { "Arrivée du terme": "Arrivée du terme", "Démission": "Démission", "Licenciement": "Licenciement", "Rupture pendant l'essai": "Rupture pendant l'essai", "Accord des parties": "Accord des parties", "Retraite": "Retraite", "Décès": "Décès" } }]])}</div>
     <p class="note">Le contrat reste sur la paie du mois de sortie, au prorata. Pour un CDD, l'indemnité de fin de contrat (3 %) est ajoutée au dernier bulletin.</p>`,
    async (f) => { await api(`/api/contrats/${c.id}/fin`, { method: "POST", body: lire(f) }); toast("Contrat terminé."); recharger(); }, "Confirmer"));
  $("[data-a=suppr]", div)?.addEventListener("click", essayer(async () => {
    if (!confirm("Supprimer ce contrat et ses avenants ? (Pour un contrat déjà payé, préférez « Mettre fin ».)")) return;
    await api(`/api/contrats/${c.id}`, { method: "DELETE" }); toast("Contrat supprimé."); recharger();
  }));
  $$("[data-suppr-av]", div).forEach((b) => (b.onclick = essayer(async () => {
    if (!confirm("Supprimer cet avenant ?")) return;
    await api(`/api/avenants/${b.dataset.supprAv}`, { method: "DELETE" }); recharger();
  })));
  return div;
}

const CHAMPS_CONTRAT = [
  ["type", "Type de contrat", "select", { choix: TYPES }], ["poste", "Emploi / poste", "text", { requis: true }], ["categorie", "Catégorie professionnelle", "text", { place: "ex. 3e catégorie, M1…" }],
  ["date_debut", "Date de début", "date", { requis: true }], ["date_fin", "Date de fin (CDD)", "date"], ["essai_mois", "Période d'essai (mois)", "number", { pas: 0.5 }],
  ["motif_cdd", "Motif du CDD"], ["lieu", "Lieu de travail"], ["horaire", "Durée du travail", "text", { defaut: "40 heures par semaine" }],
  ["mode", "Mode de rémunération", "select", { choix: MODES }], ["salaire_base", "Salaire de base (FCFA, par mois / jour / heure)", "number", { requis: true }],
  ["sursalaire", "Sursalaire mensuel", "number"], ["transport", "Indemnité de transport mensuelle", "number"],
];

function formContrat(s, c) {
  const val = c || { type: "CDI", mode: "mensuel", date_debut: new Date().toISOString().slice(0, 10), horaire: "40 heures par semaine" };
  const d = dialogue(c ? "Modifier le contrat" : `Nouveau contrat — ${s.nom} ${s.prenoms}`,
    `<div class="grid">${champs(CHAMPS_CONTRAT, val)}</div><div><b class="small">Primes fixes mensuelles</b><div id="primes"></div></div>
     ${c && c.avenants?.length ? `<p class="note">Les avenants s'appliquent par-dessus ces clauses initiales.</p>` : ""}`,
    async (f) => {
      const body = { ...lire(f), primes_fixes: getPrimes() };
      if (c) body.statut = c.statut;
      await api(c ? `/api/contrats/${c.id}` : `/api/salaries/${s.id}/contrats`, { method: c ? "PUT" : "POST", body });
      toast("Contrat enregistré."); vueSalarie(s.id);
    });
  const getPrimes = editeurLignes($("#primes", d), val.primes_fixes || []);
  const majType = () => {
    const t = $("[name=type]", d).value;
    $("[name=date_fin]", d).required = t === "CDD";
    $("[name=motif_cdd]", d).closest("label").hidden = t !== "CDD";
    if (t === "JOURNALIER" && !c) $("[name=mode]", d).value = "journalier";
  };
  $("[name=type]", d).onchange = majType; majType();
}

function formAvenant(s, c) {
  const d = dialogue("Avenant au contrat",
    `<div class="grid">${champs([["date_effet", "Date d'effet", "date", { requis: true, defaut: new Date().toISOString().slice(0, 10) }], ["objet", "Objet", "text", { requis: true, place: "ex. Augmentation de salaire" }]])}</div>
     <p class="small muted">Ne remplissez que les éléments modifiés :</p>
     <div class="grid">${champs([["poste", "Nouveau poste"], ["categorie", "Nouvelle catégorie"], ["salaire_base", "Nouveau salaire de base", "number"],
      ["sursalaire", "Nouveau sursalaire", "number"], ["transport", "Nouvelle indemnité de transport", "number"], ["lieu", "Nouveau lieu de travail"],
      ...(c.type !== "CDI" ? [["date_fin", "Nouvelle date de fin (renouvellement)", "date"]] : [])])}</div>`,
    async (f) => {
      const v = lire(f);
      const { date_effet, objet, ...modifs } = v;
      await api(`/api/contrats/${c.id}/avenants`, { method: "POST", body: { date_effet, objet, modifications: modifs } });
      toast("Avenant enregistré."); vueSalarie(s.id);
    });
  return d;
}

// ------------------------------------------------------------------ paie
async function vuePaie() {
  const periodes = await api("/api/periodes");
  const now = new Date();
  app.innerHTML = `<div class="head"><div><h1>Paie</h1><p class="muted">Une paie par mois : saisie des éléments variables, contrôle, clôture, bulletins.</p></div>
    ${peutModifier() ? `<form class="row" id="ouvrir"><select name="mois">${MOIS.map((m, i) => `<option value="${i + 1}" ${i === now.getMonth() ? "selected" : ""}>${m}</option>`).join("")}</select>
      <input type="number" name="annee" value="${now.getFullYear()}" min="2000" max="2100" style="width:90px"><button>Ouvrir la paie</button></form>` : ""}</div>
    <div class="card">${periodes.length ? `<table><thead><tr><th>Période</th><th>Bulletins</th><th>Statut</th></tr></thead><tbody>
      ${periodes.map((p) => `<tr class="clic" data-id="${p.id}"><td><b>${esc(p.libelle)}</b></td><td>${p.nb_bulletins}</td><td>${p.statut === "cloturee" ? `<span class="badge ok">clôturée</span>` : `<span class="badge warn">ouverte</span>`}</td></tr>`).join("")}
    </tbody></table>` : `<div class="vide">Aucune paie. Choisissez un mois et ouvrez la paie : un bulletin est préparé pour chaque contrat en cours.</div>`}</div>`;
  $$("tr.clic", app).forEach((tr) => (tr.onclick = () => (location.hash = `#/paie/${tr.dataset.id}`)));
  $("#ouvrir", app)?.addEventListener("submit", essayer(async (ev) => {
    ev.preventDefault();
    const r = await api("/api/periodes", { method: "POST", body: lire(ev.target) });
    location.hash = `#/paie/${r.id}`;
  }));
}

async function vuePeriode(pid, selection) {
  const per = await api(`/api/periodes/${pid}`);
  const p = per.periode, ouverte = p.statut === "ouverte", t = per.totaux;
  app.innerHTML = `<div class="head"><div><a href="#/paie" class="small">← Paie</a><h1>Paie de ${esc(p.libelle)}</h1>
      <p>${ouverte ? `<span class="badge warn">ouverte</span> <span class="muted small">les calculs suivent les fiches et contrats</span>` : `<span class="badge ok">clôturée</span> <span class="muted small">bulletins figés</span>`}</p></div>
    <div class="row">
      <a class="btn ghost" href="/api/periodes/${pid}/bulletins.pdf" target="_blank">Tous les bulletins (PDF)</a>
      <a class="btn ghost" href="/api/periodes/${pid}/livre.xlsx">Livre de paie (Excel)</a>
      ${peutModifier() && ouverte ? `<button id="cloturer">Clôturer</button><button class="danger" id="suppr">Supprimer</button>` : ""}
      ${moi.role === "admin" && !ouverte ? `<button class="ghost" id="rouvrir">Rouvrir</button>` : ""}
    </div></div>
    <div class="kpis">
      <div class="kpi"><span>Salaires bruts</span><b>${fcfa(t.brut)}</b></div>
      <div class="kpi"><span>Net à payer</span><b>${fcfa(t.net_a_payer)}</b></div>
      <div class="kpi"><span>CNPS + CMU salariés</span><b>${fcfa(t.cnps_salarie + t.cmu_salarie)}</b></div>
      <div class="kpi"><span>ITS retenu</span><b>${fcfa(t.its)}</b></div>
      <div class="kpi"><span>Coût employeur</span><b>${fcfa(t.cout_employeur)}</b></div>
    </div>
    <div class="split"><div class="card">${per.bulletins.length ? `<div class="table-wrap"><table><thead><tr><th>Salarié</th><th class="n">Brut</th><th class="n">Retenues</th><th class="n">Net</th><th></th></tr></thead><tbody>
      ${per.bulletins.map((b) => `<tr class="clic" data-id="${b.id}"><td><b>${esc(b.nom)}</b><br><span class="small muted">${esc(b.poste)} · ${TYPES[b.type] || b.type}</span></td>
        <td class="n">${fcfa(b.resultat.brut)}</td><td class="n">${fcfa(b.resultat.total_cotisations + b.resultat.total_retenues)}</td><td class="n"><b>${fcfa(b.resultat.net_a_payer)}</b></td>
        <td>${b.resultat.alertes.length ? `<span class="badge ko" title="${esc(b.resultat.alertes.join(" "))}">!</span>` : ""}</td></tr>`).join("")}
      <tr class="tot"><td>Total (${per.bulletins.length})</td><td class="n">${fcfa(t.brut)}</td><td class="n">${fcfa(t.cnps_salarie + t.cmu_salarie + t.its + t.total_retenues)}</td><td class="n">${fcfa(t.net_a_payer)}</td><td></td></tr>
      </tbody></table></div>` : `<div class="vide">Aucun contrat en cours sur ce mois. Ajoutez des contrats depuis la fiche des <a href="#/salaries">salariés</a>.</div>`}</div>
      <div id="editeur">${per.bulletins.length ? `<div class="card vide">Sélectionnez un salarié pour saisir ses éléments variables et voir son bulletin.</div>` : ""}</div></div>`;
  const ouvrir = (id) => { $$("tr.clic", app).forEach((tr) => tr.classList.toggle("sel", tr.dataset.id == id)); editeurBulletin(id, ouverte, pid); };
  $$("tr.clic", app).forEach((tr) => (tr.onclick = () => ouvrir(tr.dataset.id)));
  if (selection && per.bulletins.some((b) => b.id == selection)) ouvrir(selection);
  $("#cloturer", app)?.addEventListener("click", essayer(async () => {
    const nbAl = per.bulletins.filter((b) => b.resultat.alertes.length).length;
    if (!confirm(`Clôturer la paie de ${p.libelle} ? Les bulletins seront figés.${nbAl ? `\n\nAttention : ${nbAl} bulletin(s) présentent des alertes.` : ""}`)) return;
    await api(`/api/periodes/${pid}/cloture`, { method: "POST" }); toast("Paie clôturée."); vuePeriode(pid);
  }));
  $("#rouvrir", app)?.addEventListener("click", essayer(async () => {
    if (!confirm("Rouvrir cette paie ? Les bulletins seront recalculés d'après les fiches actuelles.")) return;
    await api(`/api/periodes/${pid}/reouverture`, { method: "POST" }); toast("Paie rouverte."); vuePeriode(pid);
  }));
  $("#suppr", app)?.addEventListener("click", essayer(async () => {
    if (!confirm(`Supprimer la paie de ${p.libelle} et les éléments variables saisis ?`)) return;
    await api(`/api/periodes/${pid}`, { method: "DELETE" }); location.hash = "#/paie";
  }));
}

function tableBulletin(r) {
  const nb = (x) => (x === undefined || x === null) ? "" : x >= 100 ? fcfa(x) : Number(x).toLocaleString("fr-FR", { maximumFractionDigits: 2 });
  const tx = (x) => !x ? "" : x < 1 ? pct(x) : fcfa(x);
  const lg = (l, col) => `<tr><td>${esc(l.libelle)}</td><td class="n">${nb(l.base)}</td><td class="n">${tx(l.taux)}</td>
    <td class="n">${col === "g" ? fcfa(l.gain) : ""}</td><td class="n">${col === "r" ? fcfa(l.retenue) : ""}</td><td class="n muted">${fcfa(l.patronal)}</td></tr>`;
  return `<div class="table-wrap"><table><thead><tr><th>Rubrique</th><th class="n">Base</th><th class="n">Taux</th><th class="n">Gain</th><th class="n">Retenue</th><th class="n">Patronal</th></tr></thead><tbody>
    ${r.gains.map((l) => lg(l, "g")).join("")}
    <tr class="tot"><td>Salaire brut</td><td></td><td></td><td class="n">${fcfa(r.brut)}</td><td></td><td></td></tr>
    ${r.cotisations.map((l) => lg(l, "r")).join("")}${r.retenues.map((l) => lg(l, "r")).join("")}
    <tr class="tot"><td>Totaux</td><td></td><td></td><td class="n">${fcfa(r.brut)}</td><td class="n">${fcfa(r.total_cotisations + r.total_retenues)}</td><td class="n">${fcfa(r.charges_patronales)}</td></tr>
    </tbody></table></div>
    <div class="row" style="justify-content:space-between;margin-top:10px"><span class="muted small">Brut imposable ${fcfa(r.brut_imposable)} · ${r.parts} part(s) · coût employeur ${fcfa(r.cout_employeur)}</span>
    <span>Net à payer <span class="net">${fcfa(r.net_a_payer)} FCFA</span></span></div>
    ${r.alertes.length ? `<div class="note" style="margin-top:8px;color:var(--ko)">${r.alertes.map(esc).join("<br>")}</div>` : ""}`;
}

async function editeurBulletin(bid, ouverte, pid) {
  const box = $("#editeur", app);
  const b = await api(`/api/bulletins/${bid}`);
  const r = b.resultat, s = b.instantane.salarie, c = b.instantane.contrat, v = b.variables, ve = r.variables_effectives || {};
  const edit = ouverte && peutModifier();
  const mode = c.mode || "mensuel";
  const defs = [
    ...(mode === "journalier" ? [["jours", "Jours travaillés", "number", { pas: 0.5 }]] : []),
    ...(mode === "horaire" ? [["heures", "Heures travaillées", "number"]] : []),
    ...(mode === "mensuel" ? [["prorata", "Prorata du mois (1 = mois complet)", "number", { pas: 0.0001, place: String(ve.prorata ?? 1) }], ["heures_absence", "Heures d'absence non payées", "number"]] : []),
    ["hs15", "H. sup. +15 %", "number"], ["hs50", "H. sup. +50 %", "number"], ["hs75", "H. sup. +75 %", "number"], ["hs100", "H. sup. +100 %", "number"],
    ["acompte", "Acompte / avance", "number"],
    ...(c.type === "CDD" && ve.indemnite_fin_contrat ? [["indemnite_fin_contrat", "Indemnité de fin de CDD", "number", { place: String(ve.indemnite_fin_contrat) }]] : []),
  ].map((d) => (edit ? d : [d[0], d[1], d[2], { ...d[3], lecture: true }]));
  box.innerHTML = `<div class="card"><div class="head" style="margin-bottom:8px"><div><h2 style="margin:0">${esc(s.nom)} ${esc(s.prenoms)}</h2>
      <span class="small muted">${esc(c.poste || "")} · ${TYPES[c.type] || c.type} · ${fcfa(c.salaire_base)} FCFA ${mode === "mensuel" ? "/ mois" : mode === "journalier" ? "/ jour" : "/ h"} · ancienneté ${r.anciennete_annees} an(s)</span></div>
      <a class="btn small ghost" href="/api/bulletins/${bid}/pdf" target="_blank">Bulletin PDF</a></div>
    <form id="vars"><div class="grid">${champs(defs, v)}</div>
      <div style="margin-top:10px"><b class="small">Primes du mois</b><div id="primes-mois"></div></div>
      <div style="margin-top:6px"><b class="small">Autres retenues (prêt, cantine…)</b><div id="ret-mois"></div></div>
      ${edit ? `<div class="row" style="margin-top:10px"><button>Enregistrer et recalculer</button></div>` : ""}</form>
    <h3>Bulletin</h3><div id="apercu">${tableBulletin(r)}</div>
    <p class="small muted">Cumuls ${b.periode.annee} : brut ${fcfa(b.cumuls.brut)} · ITS ${fcfa(b.cumuls.its)} · net ${fcfa(b.cumuls.net_a_payer)}</p></div>`;
  const getPrimes = editeurLignes($("#primes-mois", box), v.primes || [], { ajout: "Ajouter une prime", lecture: !edit });
  const getRet = editeurLignes($("#ret-mois", box), v.autres_retenues || [], { imposable: false, ajout: "Ajouter une retenue", lecture: !edit });
  $("#vars", box).onsubmit = essayer(async (ev) => {
    ev.preventDefault();
    const vars = { ...lire(ev.target), primes: getPrimes(), autres_retenues: getRet() };
    Object.keys(vars).forEach((k) => (vars[k] === "" || vars[k] === 0) && !["primes", "autres_retenues"].includes(k) && delete vars[k]);
    await api(`/api/bulletins/${bid}`, { method: "PUT", body: { variables: vars } });
    toast("Bulletin recalculé.");
    await vuePeriode(pid, bid);
  });
}

// ------------------------------------------------------------------ simulateur
async function vueSimulateur() {
  const now = new Date();
  app.innerHTML = `<div class="head"><div><h1>Simulateur de salaire</h1><p class="muted">Du salaire de base au net à payer et au coût employeur, avec le barème en vigueur.</p></div></div>
    <div class="split"><form class="card" id="sim">
      <fieldset><legend>Rémunération</legend><div class="grid">${champs([["salaire_base", "Salaire de base mensuel", "number", { defaut: 150000 }], ["sursalaire", "Sursalaire", "number"], ["transport", "Indemnité de transport", "number", { defaut: 30000 }]].map((d) => [d[0], d[1], d[2], d[3] || {}]), {})}</div>
        <div style="margin-top:8px"><b class="small">Primes</b><div id="sim-primes"></div></div></fieldset>
      <fieldset><legend>Salarié</legend><div class="grid">${champs([["date_embauche", "Date d'embauche", "date", { defaut: now.toISOString().slice(0, 10) }], ["marie", "Marié(e)", "check"], ["enfants", "Enfants à charge", "number", { pas: 1 }], ["expatrie", "Expatrié", "check"]], {})}</div></fieldset>
      <fieldset><legend>Mois</legend><div class="grid">${champs([["hs15", "H. sup. +15 %", "number"], ["hs50", "H. sup. +50 %", "number"]], {})}</div></fieldset>
    </form><div class="card" id="sim-res"></div></div>`;
  // le simulateur reste modifiable même en lecture seule
  $$("#sim [disabled]").forEach((el) => (el.disabled = false));
  const getPrimes = editeurLignes($("#sim-primes"), [], { lecture: false });
  const calc = essayer(async () => {
    const d = lire($("#sim"));
    const r = await api("/api/simulation", { method: "POST", body: {
      annee: now.getFullYear(), mois: now.getMonth() + 1,
      salarie: { date_embauche: d.date_embauche, marie: d.marie, enfants: d.enfants, expatrie: d.expatrie },
      contrat: { salaire_base: d.salaire_base, sursalaire: d.sursalaire, transport: d.transport, primes_fixes: getPrimes() },
      variables: { hs15: d.hs15, hs50: d.hs50 } } });
    $("#sim-res").innerHTML = `<h2>Résultat</h2>${tableBulletin(r)}`;
  });
  let h; $("#sim").addEventListener("input", () => { clearTimeout(h); h = setTimeout(calc, 300); });
  $("#sim").addEventListener("click", (e) => e.target.matches("button") && setTimeout(calc, 50));
  $("#sim").onsubmit = (e) => { e.preventDefault(); calc(); };
  calc();
}

// ------------------------------------------------------------------ paramètres
const CHAMPS_ENTREPRISE = [
  ["raison_sociale", "Raison sociale", "text", { requis: true }], ["forme_juridique", "Forme juridique", "text", { place: "SARL, SA…" }], ["capital", "Capital (FCFA)", "number"],
  ["adresse", "Adresse du siège"], ["ville", "Ville", "text", { defaut: "Abidjan" }], ["telephone", "Téléphone"],
  ["rccm", "RCCM"], ["compte_contribuable", "Compte contribuable"], ["numero_cnps", "N° employeur CNPS"],
  ["representant", "Représentant légal"], ["qualite_representant", "Qualité", "text", { place: "Gérant, Directeur général…" }],
  ["taux_at", "Taux accident du travail CNPS (%)", "number", { pas: 0.01, place: "2 à 5 selon l'activité" }],
  ["convention", "Convention collective", "text", { defaut: "Convention collective interprofessionnelle du 19 juillet 1977" }],
];

async function vueParametres() {
  const [ent, bar] = await Promise.all([api("/api/entreprise"), api("/api/bareme")]);
  const admin = moi.role === "admin";
  app.innerHTML = `<div class="head"><div><h1>Paramètres</h1></div></div>
    <form class="card" id="ent"><h2>Entreprise</h2><p class="muted small">Ces informations figurent sur les contrats et les bulletins.</p><div class="grid">${champs(CHAMPS_ENTREPRISE, ent)}</div>
      ${peutModifier() ? `<p><button>Enregistrer</button></p>` : ""}</form>
    <div class="card" id="bareme"></div>
    ${admin ? `<div class="card" id="users"></div>` : ""}
    <form class="card" id="mdp"><h2>Mon mot de passe</h2><div class="grid">
      <label>Mot de passe actuel<input type="password" name="ancien" required></label><label>Nouveau mot de passe<input type="password" name="nouveau" minlength="8" required></label></div>
      <p><button>Changer le mot de passe</button></p></form>`;
  $("#ent").onsubmit = essayer(async (e) => { e.preventDefault(); await api("/api/entreprise", { method: "PUT", body: lire(e.target) }); toast("Entreprise enregistrée."); });
  $("#mdp").onsubmit = essayer(async (e) => { e.preventDefault(); await api("/api/moi/mdp", { method: "PUT", body: lire(e.target) }); e.target.reset(); toast("Mot de passe changé."); });
  rendreBareme(bar, admin);
  if (admin) rendreUtilisateurs();
}

function rendreBareme({ bareme: b, modifie }, admin) {
  const box = $("#bareme");
  const ro = admin ? "" : "disabled";
  const num = (path, v, lib, pctMode = false) => `<label>${esc(lib)}<input type="number" step="any" data-path="${path}" data-pct="${pctMode ? 1 : ""}" value="${pctMode ? +(v * 100).toFixed(4) : v}" ${ro}></label>`;
  box.innerHTML = `<div class="head" style="margin-bottom:6px"><div><h2 style="margin:0">Barème de paie — ${esc(b.pays)}</h2>
    <p class="small muted">${esc(b.avertissement)}${modifie ? " <b>Barème personnalisé.</b>" : ""}</p></div></div>
    <form id="bar">
    <fieldset><legend>Général</legend><div class="grid">
      ${num("smig_mensuel", b.smig_mensuel, "SMIG mensuel")}${num("heures_mensuelles", b.heures_mensuelles, "Heures mensuelles")}
      ${num("transport_non_imposable", b.transport_non_imposable, "Transport non imposable (plafond)")}${num("indemnite_fin_cdd", b.indemnite_fin_cdd, "Indemnité fin de CDD (%)", true)}</div></fieldset>
    <fieldset><legend>CNPS</legend><div class="grid">
      ${num("cnps.retraite_salarie", b.cnps.retraite_salarie, "Retraite — salarié (%)", true)}${num("cnps.retraite_employeur", b.cnps.retraite_employeur, "Retraite — employeur (%)", true)}
      ${num("cnps.plafond_retraite", b.cnps.plafond_retraite, "Plafond retraite mensuel")}${num("cnps.prestations_familiales", b.cnps.prestations_familiales, "Prestations familiales (%)", true)}
      ${num("cnps.maternite", b.cnps.maternite, "Assurance maternité (%)", true)}${num("cnps.accident_travail", b.cnps.accident_travail, "Accident du travail par défaut (%)", true)}
      ${num("cnps.plafond_autres_branches", b.cnps.plafond_autres_branches, "Plafond PF / maternité / AT")}</div></fieldset>
    <fieldset><legend>CMU (FCFA par mois)</legend><div class="grid">
      ${num("cmu.salarie", b.cmu.salarie, "Part salariale")}${num("cmu.employeur", b.cmu.employeur, "Part patronale")}${num("cmu.par_personne_a_charge", b.cmu.par_personne_a_charge, "Par personne à charge")}</div></fieldset>
    <fieldset><legend>ITS — barème mensuel progressif</legend>
      <table><thead><tr><th>Jusqu'à (FCFA)</th><th>Taux (%)</th></tr></thead><tbody>
      ${b.its.tranches.map(([h, t], i) => `<tr><td><input type="number" data-tr="${i}" data-k="h" value="${h ?? ""}" placeholder="au-delà" ${ro}></td><td><input type="number" step="any" data-tr="${i}" data-k="t" value="${+(t * 100).toFixed(4)}" ${ro}></td></tr>`).join("")}
      </tbody></table><div class="grid" style="margin-top:8px">${num("its.reduction_par_demi_part", b.its.reduction_par_demi_part, "Réduction par demi-part au-delà de 1")}${num("its.parts_max", b.its.parts_max, "Nombre de parts maximal")}</div></fieldset>
    <fieldset><legend>Charges patronales sur salaires</legend><div class="grid">
      ${num("employeur.impot_patronal_local", b.employeur.impot_patronal_local, "Impôt patronal — local (%)", true)}${num("employeur.impot_patronal_expatrie", b.employeur.impot_patronal_expatrie, "Impôt patronal — expatrié (%)", true)}
      ${num("employeur.taxe_apprentissage", b.employeur.taxe_apprentissage, "FDFP apprentissage (%)", true)}${num("employeur.formation_continue", b.employeur.formation_continue, "FDFP formation continue (%)", true)}</div></fieldset>
    <fieldset><legend>Ancienneté et heures supplémentaires</legend><div class="grid">
      ${num("anciennete.debut_annees", b.anciennete.debut_annees, "Prime d'ancienneté à partir de (ans)")}${num("anciennete.taux_par_an", b.anciennete.taux_par_an, "Taux par année (%)", true)}${num("anciennete.taux_max", b.anciennete.taux_max, "Taux maximal (%)", true)}
      ${Object.keys(b.heures_sup).map((k) => num(`heures_sup.${k}`, b.heures_sup[k], `Majoration ${k.toUpperCase()} (%)`, true)).join("")}</div></fieldset>
    ${admin ? `<div class="row"><button>Enregistrer le barème</button>${modifie ? `<button type="button" class="ghost" id="reinit">Rétablir le barème livré</button>` : ""}</div>` : `<p class="small muted">Seul un administrateur peut modifier le barème.</p>`}
    </form>`;
  if (!admin) return;
  $("#bar").onsubmit = essayer(async (e) => {
    e.preventDefault();
    const nb = JSON.parse(JSON.stringify(b));
    $$("[data-path]", e.target).forEach((el) => {
      const keys = el.dataset.path.split("."); let o = nb;
      keys.slice(0, -1).forEach((k) => (o = o[k]));
      o[keys.at(-1)] = el.dataset.pct ? Number(el.value) / 100 : Number(el.value);
    });
    nb.its.tranches = nb.its.tranches.map((_, i) => {
      const h = $(`[data-tr="${i}"][data-k=h]`, e.target).value;
      return [h === "" ? null : Number(h), Number($(`[data-tr="${i}"][data-k=t]`, e.target).value) / 100];
    });
    await api("/api/bareme", { method: "PUT", body: nb }); toast("Barème enregistré."); vueParametres();
  });
  $("#reinit")?.addEventListener("click", essayer(async () => {
    if (!confirm("Rétablir le barème livré avec l'application ?")) return;
    await api("/api/bareme", { method: "DELETE" }); toast("Barème rétabli."); vueParametres();
  }));
}

async function rendreUtilisateurs() {
  const us = await api("/api/utilisateurs");
  const box = $("#users");
  const ROLES = { admin: "Administrateur", gestionnaire: "Gestionnaire de paie", lecteur: "Lecture seule" };
  box.innerHTML = `<div class="head" style="margin-bottom:6px"><h2 style="margin:0">Utilisateurs</h2><button class="small" id="nouv-u">+ Nouvel utilisateur</button></div>
    <table><tbody>${us.map((u) => `<tr><td><b>${esc(u.nom)}</b><br><span class="small muted">${esc(u.email)}</span></td>
      <td><select data-role="${u.id}">${Object.entries(ROLES).map(([k, l]) => `<option value="${k}" ${u.role === k ? "selected" : ""}>${l}</option>`).join("")}</select></td>
      <td class="n">${u.id === moi.id ? `<span class="muted small">vous</span>` : `<button class="danger small" data-suppr="${u.id}">Retirer</button>`}</td></tr>`).join("")}</tbody></table>`;
  $$("[data-role]", box).forEach((s) => (s.onchange = essayer(async () => { await api(`/api/utilisateurs/${s.dataset.role}`, { method: "PUT", body: { role: s.value } }); toast("Rôle modifié."); })));
  $$("[data-suppr]", box).forEach((b) => (b.onclick = essayer(async () => { if (!confirm("Retirer cet utilisateur ?")) return; await api(`/api/utilisateurs/${b.dataset.suppr}`, { method: "DELETE" }); rendreUtilisateurs(); })));
  $("#nouv-u", box).onclick = () => dialogue("Nouvel utilisateur",
    `<div class="grid">${champs([["nom", "Nom", "text", { requis: true }], ["email", "Adresse électronique", "email", { requis: true }], ["mdp", "Mot de passe provisoire", "password", { requis: true }], ["role", "Rôle", "select", { choix: ROLES, defaut: "gestionnaire" }]])}</div>`,
    async (f) => { await api("/api/utilisateurs", { method: "POST", body: lire(f) }); toast("Utilisateur créé."); rendreUtilisateurs(); });
}

// ------------------------------------------------------------------ routeur
async function route() {
  if (!moi) { $("#menu").hidden = $("#usernav").hidden = true; return vueConnexion(); }
  $("#menu").hidden = $("#usernav").hidden = false;
  $("#username").textContent = `${moi.nom} · ${{ admin: "administrateur", gestionnaire: "gestionnaire", lecteur: "lecture seule" }[moi.role]}`;
  const h = location.hash.replace(/^#\/?/, "").split("/");
  $$("#menu a").forEach((a) => a.classList.toggle("actif", a.getAttribute("href").replace("#/", "") === (h[0] || "")));
  try {
    if (h[0] === "salaries" && h[1]) await vueSalarie(h[1]);
    else if (h[0] === "salaries") await vueSalaries();
    else if (h[0] === "paie" && h[1]) await vuePeriode(h[1]);
    else if (h[0] === "paie") await vuePaie();
    else if (h[0] === "simulateur") await vueSimulateur();
    else if (h[0] === "parametres") await vueParametres();
    else await vueAccueil();
  } catch (e) { app.innerHTML = `<div class="card err">${esc(e.message)}</div>`; }
  window.scrollTo(0, 0);
}

async function demarrer() {
  const e = await api("/api/etat");
  moi = e.utilisateur;
  route();
}

$("#logout").onclick = essayer(async () => { await api("/api/deconnexion", { method: "POST" }); moi = null; location.hash = "#/"; route(); });
window.addEventListener("hashchange", route);
demarrer();
