// BatiCalc — éditeur de structure (poteaux et poutres) avant calcul
// Coordonnées en mètres, axe y vers le haut (affiché inversé dans le SVG).

const NEW = "~";        // repères provisoires des éléments créés (renumérotés par le serveur)
const SNAP = 0.25;      // distance d'accrochage aux axes de murs et aux files (m)

export function mountEditor(host, data, opts) {
  const ed = {
    data, k: 0, tool: "select", sel: null, pendingBeam: null, dirty: false, undo: [], seq: 1,
  };
  const css = getComputedStyle(document.documentElement);
  const col = (v) => css.getPropertyValue(v).trim();
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const lvl = () => ed.data.niveaux[ed.k];
  const below = () => (ed.k > 0 ? ed.data.niveaux[ed.k - 1] : null);
  const r3 = (v) => Math.round(v * 1000) / 1000;
  const newId = (p) => `${NEW}${p}${ed.seq++}`;
  const snapshot = () => JSON.stringify(ed.data.niveaux);
  const push = () => { ed.undo.push(snapshot()); if (ed.undo.length > 60) ed.undo.shift(); ed.dirty = true; };

  host.innerHTML = `
    <div class="viewer-bar" id="edbar">
      <select id="edlv" aria-label="Niveau">${ed.data.niveaux.map((n, i) => `<option value="${i}">${esc(n.nom)}</option>`).join("")}</select>
      <span class="seg" role="group" aria-label="Outil">
        <button data-tool="select" title="Sélectionner, déplacer (glisser un poteau)">Sélection</button>
        <button data-tool="col" title="Cliquer pour placer un poteau (accroché aux murs et aux files)">+ Poteau</button>
        <button data-tool="beam" title="Cliquer deux poteaux">+ Poutre</button>
        <button data-tool="del" title="Cliquer un élément pour le supprimer">Supprimer</button>
      </span>
      <button class="ghost" id="edundo" title="Annuler (Ctrl+Z)">Annuler</button>
      <button class="ghost" id="edcopy" ${ed.data.niveaux.length > 1 ? "" : "hidden"} title="Reprendre les poteaux du niveau inférieur">Copier niveau inférieur</button>
    </div>
    <div class="viewer" id="edvw"></div>
    <div class="legend"><span><i style="background:var(--column)"></i>Poteaux</span><span><i style="background:var(--beam)"></i>Poutres</span>
      <span><i style="background:var(--muted);opacity:.5"></i>Murs du plan</span><span><i style="border:1px dashed var(--transfer)"></i>Poteaux du niveau inférieur</span>
      <span><i style="background:var(--transfer)"></i>Poteau naissant (rien dessous)</span><span><i style="background:var(--slab)"></i>Contour</span></div>
    <p class="small muted" id="edhelp"></p>`;
  const vw = host.querySelector("#edvw");
  const help = host.querySelector("#edhelp");
  const HELP = {
    select: "Glissez un poteau pour le déplacer ; touchez un élément pour modifier sa section. Glissez le fond pour vous déplacer, molette ou pincement pour zoomer.",
    col: "Touchez le plan pour placer un poteau : il s'accroche aux axes des murs, aux files existantes et aux poteaux du niveau inférieur. Placé sur une poutre, il la coupe en deux.",
    beam: "Touchez deux poteaux successivement pour créer une poutre entre eux.",
    del: "Touchez un poteau (ses poutres sont retirées, les poutres alignées sont raccordées) ou une poutre pour la supprimer.",
  };

  // ------------------------------------------------------------- géométrie
  let vb = null;
  function fit() {
    const L = lvl(), pts = [];
    L.poteaux.forEach((c) => pts.push([c.x, c.y]));
    L.murs.forEach((w) => { pts.push([w[0], w[1]]); pts.push([w[2], w[3]]); });
    L.contour.forEach((s) => { pts.push([s[0], s[1]]); pts.push([s[2], s[3]]); });
    if (!pts.length) pts.push([0, 0], [10, 10]);
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => -p[1]);
    const x0 = Math.min(...xs) - 1.5, x1 = Math.max(...xs) + 1.5, y0 = Math.min(...ys) - 1.5, y1 = Math.max(...ys) + 1.5;
    vb = [x0, y0, x1 - x0, y1 - y0];
  }
  const svgEl = () => vw.querySelector("svg");
  function toWorld(cx, cy) {
    const r = svgEl().getBoundingClientRect();
    const s = Math.max(vb[2] / r.width, vb[3] / r.height);
    const ox = vb[0] + vb[2] / 2 - (r.width * s) / 2, oy = vb[1] + vb[3] / 2 - (r.height * s) / 2;
    return [ox + (cx - r.left) * s, -(oy + (cy - r.top) * s), s];
  }
  function snap(x, y, ignore) {
    const L = lvl(), xs = [], ys = [];
    L.murs.forEach((w) => {
      const horiz = Math.abs(w[2] - w[0]) >= Math.abs(w[3] - w[1]);
      if (horiz && x >= Math.min(w[0], w[2]) - SNAP && x <= Math.max(w[0], w[2]) + SNAP) ys.push((w[1] + w[3]) / 2);
      if (!horiz && y >= Math.min(w[1], w[3]) - SNAP && y <= Math.max(w[1], w[3]) + SNAP) xs.push((w[0] + w[2]) / 2);
    });
    const others = L.poteaux.filter((c) => c !== ignore).concat(below() ? below().poteaux : []);
    // priorité : poteau du niveau inférieur juste dessous (continuité verticale)
    const under = below() && below().poteaux.find((c) => Math.hypot(c.x - x, c.y - y) <= SNAP * 1.6);
    if (under) return [under.x, under.y, true];
    others.forEach((c) => { xs.push(c.x); ys.push(c.y); });
    const near = (v, arr) => arr.reduce((best, a) => (Math.abs(a - v) < Math.abs(best - v) ? a : best), Infinity);
    const sx = near(x, xs), sy = near(y, ys);
    return [Math.abs(sx - x) <= SNAP ? sx : x, Math.abs(sy - y) <= SNAP ? sy : y, false];
  }
  const colById = (id) => lvl().poteaux.find((c) => c.id === id);
  const isNaissant = (c) => below() && !below().poteaux.some((o) => Math.hypot(o.x - c.x, o.y - c.y) < 0.15);

  // ------------------------------------------------------------- opérations
  function addColumn(x, y) {
    const L = lvl();
    const [sx, sy] = snap(x, y);
    if (L.poteaux.some((c) => Math.hypot(c.x - sx, c.y - sy) < 0.3)) { opts.toast("Un poteau existe déjà ici."); return; }
    push();
    const ref = L.poteaux[0] || {};
    const c = { id: newId("P"), x: r3(sx), y: r3(sy), b: ref.b || 0.2, h: ref.h || 0.2 };
    L.poteaux.push(c);
    // coupe la poutre traversée
    for (const bm of [...L.poutres]) {
      const a = colById(bm.a), b = colById(bm.b);
      if (!a || !b) continue;
      const len = Math.hypot(b.x - a.x, b.y - a.y);
      const t = ((c.x - a.x) * (b.x - a.x) + (c.y - a.y) * (b.y - a.y)) / (len * len);
      const d = Math.abs((b.x - a.x) * (a.y - c.y) - (a.x - c.x) * (b.y - a.y)) / len;
      if (t > 0.02 && t < 0.98 && d < 0.15) {
        L.poutres.splice(L.poutres.indexOf(bm), 1,
          { id: bm.id, a: bm.a, b: c.id, l: bm.l, h: bm.h }, { id: newId("B"), a: c.id, b: bm.b, l: bm.l, h: bm.h });
        break;
      }
    }
    ed.sel = { type: "c", id: c.id };
  }
  function deleteColumn(id) {
    const L = lvl();
    push();
    const attached = L.poutres.filter((bm) => bm.a === id || bm.b === id);
    L.poutres = L.poutres.filter((bm) => !attached.includes(bm));
    L.poteaux = L.poteaux.filter((c) => c.id !== id);
    // raccorde deux poutres alignées de part et d'autre
    if (attached.length >= 2) {
      const ends = attached.map((bm) => (bm.a === id ? bm.b : bm.a)).map(colById).filter(Boolean);
      for (let i = 0; i < ends.length; i++) for (let j = i + 1; j < ends.length; j++) {
        const p = ends[i], q = ends[j];
        if (Math.abs(p.x - q.x) < 0.15 || Math.abs(p.y - q.y) < 0.15) {
          const src = attached[i];
          L.poutres.push({ id: newId("B"), a: p.id, b: q.id, l: src.l, h: src.h });
          i = j = ends.length;
        }
      }
    }
    ed.sel = null;
  }
  function addBeam(a, b) {
    const L = lvl();
    if (a === b) return;
    if (L.poutres.some((bm) => (bm.a === a && bm.b === b) || (bm.a === b && bm.b === a))) { opts.toast("Cette poutre existe déjà."); return; }
    push();
    const ref = L.poutres[0] || {};
    L.poutres.push({ id: newId("B"), a, b, l: ref.l || 0.2, h: ref.h || 0.4 });
  }
  function copyBelow() {
    const B = below(); if (!B) return;
    push();
    const L = lvl();
    let n = 0;
    B.poteaux.forEach((o) => {
      const near = L.poteaux.find((c) => Math.hypot(c.x - o.x, c.y - o.y) < 0.6);
      if (near) { near.x = o.x; near.y = o.y; return; }
      L.poteaux.push({ id: newId("P"), x: o.x, y: o.y, b: o.b, h: o.h }); n++;
    });
    opts.toast(`${n} poteau(x) ajouté(s), les autres recalés sur le niveau inférieur.`);
  }

  // ------------------------------------------------------------- dessin
  function draw() {
    const L = lvl(), B = below();
    const Y = (y) => -y;
    let s = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vb.join(" ")}">`;
    s += `<g stroke="${col("--slab")}" stroke-width="0.05">${L.contour.map((g) => `<line x1="${g[0]}" y1="${Y(g[1])}" x2="${g[2]}" y2="${Y(g[3])}"/>`).join("")}</g>`;
    s += `<g stroke="${col("--muted")}" stroke-opacity="0.35" stroke-linecap="square">${L.murs.map((w) => `<line x1="${w[0]}" y1="${Y(w[1])}" x2="${w[2]}" y2="${Y(w[3])}" stroke-width="${w[4] || 0.2}"/>`).join("")}</g>`;
    if (B) s += `<g fill="none" stroke="${col("--transfer")}" stroke-width="0.035" stroke-dasharray="0.08 0.06">${B.poteaux.map((c) => `<rect x="${c.x - c.b / 2 - 0.05}" y="${Y(c.y) - c.h / 2 - 0.05}" width="${c.b + 0.1}" height="${c.h + 0.1}"/>`).join("")}</g>`;
    s += L.poutres.map((bm) => {
      const a = colById(bm.a), b = colById(bm.b);
      if (!a || !b) return "";
      const on = ed.sel && ed.sel.type === "b" && ed.sel.id === bm.id;
      return `<line x1="${a.x}" y1="${Y(a.y)}" x2="${b.x}" y2="${Y(b.y)}" stroke="${on ? col("--accent") : col("--beam")}" stroke-width="${Math.max(bm.l, 0.16)}" stroke-opacity="${on ? 0.9 : 0.6}" data-b="${esc(bm.id)}" class="hit"/>`;
    }).join("");
    s += L.poteaux.map((c) => {
      const on = (ed.sel && ed.sel.type === "c" && ed.sel.id === c.id) || ed.pendingBeam === c.id;
      const fill = on ? col("--accent") : isNaissant(c) ? col("--transfer") : col("--column");
      const pad = 0.12;   // zone de toucher agrandie
      return `<g data-c="${esc(c.id)}" class="hit"><rect x="${c.x - c.b / 2 - pad}" y="${Y(c.y) - c.h / 2 - pad}" width="${c.b + 2 * pad}" height="${c.h + 2 * pad}" fill="transparent"/>
        <rect x="${c.x - c.b / 2}" y="${Y(c.y) - c.h / 2}" width="${c.b}" height="${c.h}" fill="${fill}"/></g>`;
    }).join("");
    s += `<g font-size="0.28" fill="${col("--muted")}">${L.poteaux.map((c) => `<text x="${c.x + c.b / 2 + 0.08}" y="${Y(c.y) - c.h / 2 - 0.06}">${esc(c.id.startsWith(NEW) ? "nouveau" : c.id)}</text>`).join("")}</g>`;
    s += `</svg><div class="info" id="edinfo" hidden></div>`;
    vw.innerHTML = s;
    host.querySelectorAll("[data-tool]").forEach((b) => b.classList.toggle("ghost", b.dataset.tool !== ed.tool));
    host.querySelector("#edundo").disabled = !ed.undo.length;
    help.textContent = HELP[ed.tool];
    showInfo();
    bindView();
    opts.onChange && opts.onChange(ed);
  }

  function showInfo() {
    const info = vw.querySelector("#edinfo");
    if (!ed.sel) { info.hidden = true; return; }
    const L = lvl();
    let html = "";
    if (ed.sel.type === "c") {
      const c = colById(ed.sel.id); if (!c) { info.hidden = true; return; }
      html = `<b>Poteau ${esc(c.id.startsWith(NEW) ? "(nouveau)" : c.id)}</b>${isNaissant(c) ? ' <span class="badge ko">naissant</span>' : ""}
        <div class="row2"><label>b (cm)<input type="number" min="12" max="150" step="5" id="eb" value="${Math.round(c.b * 100)}"></label>
        <label>h (cm)<input type="number" min="12" max="150" step="5" id="eh" value="${Math.round(c.h * 100)}"></label></div>
        <div class="row2"><label>x (m)<input type="number" step="0.05" id="ex" value="${c.x}"></label>
        <label>y (m)<input type="number" step="0.05" id="ey" value="${c.y}"></label></div>
        <label class="inline"><input type="checkbox" id="eall"> appliquer la section à tous les poteaux du niveau</label>`;
    } else {
      const bm = L.poutres.find((x) => x.id === ed.sel.id); if (!bm) { info.hidden = true; return; }
      const a = colById(bm.a), b = colById(bm.b);
      html = `<b>Poutre</b> ${esc(bm.a)} – ${esc(bm.b)}<br><span class="small muted">portée ${(Math.hypot(b.x - a.x, b.y - a.y)).toFixed(2)} m</span>
        <div class="row2"><label>largeur (cm)<input type="number" min="12" max="100" step="5" id="eb" value="${Math.round(bm.l * 100)}"></label>
        <label>hauteur (cm)<input type="number" min="15" max="150" step="5" id="eh" value="${Math.round(bm.h * 100)}"></label></div>
        <label class="inline"><input type="checkbox" id="eall"> appliquer à toutes les poutres du niveau</label>`;
    }
    info.innerHTML = html + `<div class="actions"><button class="danger" id="edel">Supprimer</button><button class="ghost" id="eclose">Fermer</button></div>`;
    info.hidden = false;
    const num = (id) => Number(info.querySelector(id).value);
    const commit = () => {
      push();
      const all = info.querySelector("#eall").checked;
      if (ed.sel.type === "c") {
        const c = colById(ed.sel.id);
        const b = num("#eb") / 100, h = num("#eh") / 100;
        (all ? L.poteaux : [c]).forEach((o) => { o.b = b; o.h = h; });
        c.x = r3(num("#ex")); c.y = r3(num("#ey"));
      } else {
        const bm = L.poutres.find((x) => x.id === ed.sel.id);
        const l = num("#eb") / 100, h = num("#eh") / 100;
        (all ? L.poutres : [bm]).forEach((o) => { o.l = l; o.h = h; });
      }
      draw();
    };
    info.querySelectorAll("input").forEach((i) => (i.onchange = commit));
    info.querySelector("#edel").onclick = () => {
      if (ed.sel.type === "c") deleteColumn(ed.sel.id);
      else { push(); L.poutres = L.poutres.filter((x) => x.id !== ed.sel.id); ed.sel = null; }
      draw();
    };
    info.querySelector("#eclose").onclick = () => { ed.sel = null; draw(); };
    info.addEventListener("pointerdown", (e) => e.stopPropagation());
  }

  // ------------------------------------------------------------- interaction
  function bindView() {
    const el = svgEl();
    const apply = () => el.setAttribute("viewBox", vb.join(" "));
    el.addEventListener("wheel", (e) => {
      e.preventDefault();
      const r = el.getBoundingClientRect(), [wx, wyN] = toWorld(e.clientX, e.clientY), wy = -wyN;
      const f = e.deltaY > 0 ? 1.15 : 1 / 1.15;
      vb = [wx - (wx - vb[0]) * f, wy - (wy - vb[1]) * f, vb[2] * f, vb[3] * f]; apply();
      void r;
    }, { passive: false });
    const ptrs = new Map(); let last = null; let down = null;
    el.addEventListener("pointerdown", (e) => {
      ptrs.set(e.pointerId, [e.clientX, e.clientY]); last = null;
      const g = e.target.closest("[data-c],[data-b]");
      down = { x: e.clientX, y: e.clientY, target: g, moved: false, drag: null };
      if (ed.tool === "select" && g && g.dataset.c && ptrs.size === 1) down.drag = colById(g.dataset.c);
    });
    el.addEventListener("pointermove", (e) => {
      if (!ptrs.has(e.pointerId)) return;
      if (down && !down.moved && Math.hypot(e.clientX - down.x, e.clientY - down.y) > 6) {
        down.moved = true; el.setPointerCapture(e.pointerId);
        if (down.drag) push();
      }
      if (down && !down.moved) return;
      const prev = ptrs.get(e.pointerId); ptrs.set(e.pointerId, [e.clientX, e.clientY]);
      if (down && down.drag && ptrs.size === 1) {
        const [wx, wy] = toWorld(e.clientX, e.clientY);
        const [sx, sy] = snap(wx, wy, down.drag);
        down.drag.x = r3(sx); down.drag.y = r3(sy);
        moveDom(el, down.drag);
        return;
      }
      if (ptrs.size === 1) { const s = toWorld(0, 0)[2]; vb[0] -= (e.clientX - prev[0]) * s; vb[1] -= (e.clientY - prev[1]) * s; apply(); }
      else if (ptrs.size === 2) {
        const [a, b] = [...ptrs.values()]; const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
        if (last) { const [wx, wyN] = toWorld((a[0] + b[0]) / 2, (a[1] + b[1]) / 2); const wy = -wyN; const f = last / d; vb = [wx - (wx - vb[0]) * f, wy - (wy - vb[1]) * f, vb[2] * f, vb[3] * f]; apply(); }
        last = d;
      }
    });
    const up = (e) => {
      const d = down;
      ptrs.delete(e.pointerId); last = null; if (!ptrs.size) down = null;
      if (!d) return;
      if (d.drag && d.moved) { draw(); return; }
      if (d.moved || !opts.editable) { if (!d.moved && d.target) { ed.sel = d.target.dataset.c ? { type: "c", id: d.target.dataset.c } : { type: "b", id: d.target.dataset.b }; draw(); } return; }
      click(d);
    };
    el.addEventListener("pointerup", up); el.addEventListener("pointercancel", up);
  }
  function moveDom(el, c) {     // mise à jour directe du SVG pendant le glissement
    const g = el.querySelector(`[data-c="${CSS.escape(c.id)}"]`);
    if (g) {
      const [hit, body] = g.querySelectorAll("rect");
      hit.setAttribute("x", c.x - c.b / 2 - 0.12); hit.setAttribute("y", -c.y - c.h / 2 - 0.12);
      body.setAttribute("x", c.x - c.b / 2); body.setAttribute("y", -c.y - c.h / 2);
    }
    lvl().poutres.forEach((bm) => {
      if (bm.a !== c.id && bm.b !== c.id) return;
      const ln = el.querySelector(`[data-b="${CSS.escape(bm.id)}"]`);
      if (!ln) return;
      const n = bm.a === c.id ? 1 : 2;
      ln.setAttribute(`x${n}`, c.x); ln.setAttribute(`y${n}`, -c.y);
    });
  }
  function click(d) {
    const t = d.target;
    const cid = t && t.dataset.c, bid = t && t.dataset.b;
    if (ed.tool === "select") { ed.sel = cid ? { type: "c", id: cid } : bid ? { type: "b", id: bid } : null; }
    else if (ed.tool === "col") { if (cid) ed.sel = { type: "c", id: cid }; else { const [wx, wy] = toWorld(d.x, d.y); addColumn(wx, wy); } }
    else if (ed.tool === "beam") {
      if (!cid) { ed.pendingBeam = null; }
      else if (!ed.pendingBeam) ed.pendingBeam = cid;
      else { addBeam(ed.pendingBeam, cid); ed.pendingBeam = cid; }
    } else if (ed.tool === "del") {
      if (cid) deleteColumn(cid);
      else if (bid) { push(); lvl().poutres = lvl().poutres.filter((x) => x.id !== bid); }
    }
    draw();
  }

  // ------------------------------------------------------------- barre d'outils
  const lv = host.querySelector("#edlv");
  lv.onchange = () => { ed.k = Number(lv.value); ed.sel = null; ed.pendingBeam = null; host.querySelector("#edcopy").disabled = ed.k === 0; draw(); };
  host.querySelectorAll("[data-tool]").forEach((b) => (b.onclick = () => { ed.tool = b.dataset.tool; ed.pendingBeam = null; draw(); }));
  host.querySelector("#edundo").onclick = () => { if (ed.undo.length) { ed.data.niveaux = JSON.parse(ed.undo.pop()); ed.sel = null; draw(); } };
  host.querySelector("#edcopy").onclick = () => { copyBelow(); draw(); };
  host.querySelector("#edcopy").disabled = true;
  if (!opts.editable) host.querySelectorAll("[data-tool],#edundo,#edcopy").forEach((b) => (b.hidden = true));
  const onKey = (e) => {
    if (!host.isConnected) { document.removeEventListener("keydown", onKey); return; }
    if (e.target.matches("input,select,textarea")) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); host.querySelector("#edundo").click(); }
    else if ((e.key === "Delete" || e.key === "Backspace") && ed.sel && opts.editable) {
      if (ed.sel.type === "c") deleteColumn(ed.sel.id); else { push(); lvl().poutres = lvl().poutres.filter((x) => x.id !== ed.sel.id); ed.sel = null; }
      draw();
    } else if (e.key === "Escape") { ed.sel = null; ed.pendingBeam = null; draw(); }
  };
  document.addEventListener("keydown", onKey);
  fit();
  draw();
  return ed;
}
