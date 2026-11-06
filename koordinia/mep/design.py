"""Pré-dimensionnement des réseaux : plomberie (DTU 60.11), électricité (NF C 15-100),
climatisation (bilan simplifié en climat tropical). Paramètres : koordinia/data/mep.json."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..slab import SlabMask, _dilate

PARAMS_PATH = Path(__file__).resolve().parent.parent / "data" / "mep.json"
PVC_PRESSION = [(20, 14.8), (25, 21.0), (32, 26.8), (40, 33.6), (50, 42.0), (63, 53.0), (75, 63.2), (90, 75.8)]
PVC_EVAC = [32, 40, 50, 63, 90, 100, 110, 125, 160, 200]
CABLE_SECTIONS = [(6, 46), (10, 63), (16, 85), (25, 112), (35, 138), (70, 213), (95, 258), (150, 344)]


def load_params(extra: dict | None = None) -> dict:
    p = json.loads(PARAMS_PATH.read_text(encoding="utf-8"))
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(p.get(k), dict):
            p[k].update(v)
        else:
            p[k] = v
    return p


# ----------------------------------------------------------------------------- locaux
@dataclass
class Room:
    name: str
    usage: str
    area: float
    cx: float
    cy: float
    mask: SlabMask | None = None
    facade_cells: list[tuple[float, float]] = field(default_factory=list)
    glazing: float = 0.0  # m² de vitrage en façade


def rooms_of(plan) -> list[Room]:
    """Locaux du niveau (étiquetés) + « autres surfaces » (reste de l'emprise)."""
    rooms_src = plan.rooms if plan.rooms is not None else plan.zones
    fp = plan.footprint or plan.slab
    grid = SlabMask.from_dict(fp) if fp else None
    out: list[Room] = []
    used = np.zeros_like(grid.mask) if grid is not None else None
    for z in rooms_src or []:
        if z["type"] == "ouverture":
            continue
        m = SlabMask.from_dict(z["cells"])
        jj, ii = np.nonzero(m.mask)
        if not len(jj):
            continue
        cx, cy = float(m.x0 + (ii.mean() + 0.5) * m.res), float(m.y0 + (jj.mean() + 0.5) * m.res)
        out.append(Room(z["name"], z["usage"] if z["type"] != "escalier" else "Escalier", z["area"], cx, cy, m))
        if used is not None and m.mask.shape == used.shape:
            used |= m.mask
    if grid is not None:
        rest = grid.mask & ~used
        area = float(rest.sum()) * grid.res ** 2
        if area > 5:
            jj, ii = np.nonzero(rest)
            out.append(Room("Autres surfaces", "_defaut", area, float(grid.x0 + (ii.mean() + .5) * grid.res),
                            float(grid.y0 + (jj.mean() + .5) * grid.res), SlabMask(grid.res, grid.x0, grid.y0, rest)))
        outside = ~grid.mask
        edge = _dilate(outside, 1)
        for r in out:
            if r.mask is None or r.mask.mask.shape != grid.mask.shape:
                continue
            cells = np.argwhere(r.mask.mask & edge)
            r.facade_cells = [(float(grid.x0 + (i + .5) * grid.res), float(grid.y0 + (j + .5) * grid.res))
                              for j, i in cells[:: max(1, len(cells) // 400)]]
            for o in plan.openings or []:
                if o["type"] in ("fenetre", "baie") or o["facade"]:
                    i, j = int((o["x"] - grid.x0) / grid.res), int((o["y"] - grid.y0) / grid.res)
                    rr = int(0.8 / grid.res)
                    win = r.mask.mask[max(0, j - rr):j + rr + 1, max(0, i - rr):i + rr + 1]
                    if win.size and win.any():
                        r.glazing += o["largeur"] * (2.2 if o["type"] != "fenetre" else 1.2)
    return out


def _points_in(room: Room, n: int) -> list[tuple[float, float]]:
    """n points répartis régulièrement dans le local (trame), pour les plans."""
    if n <= 0:
        return []
    if room.mask is None:
        return [(room.cx, room.cy)] * n
    jj, ii = np.nonzero(room.mask.mask)
    if not len(jj):
        return [(room.cx, room.cy)] * n
    x0, x1 = ii.min(), ii.max()
    y0, y1 = jj.min(), jj.max()
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    nx = max(1, round(math.sqrt(n * w / h)))
    ny = max(1, math.ceil(n / nx))
    pts = []
    for a in range(ny):
        for b in range(nx):
            i = int(x0 + (b + .5) * w / nx)
            j = int(y0 + (a + .5) * h / ny)
            if room.mask.mask[min(j, room.mask.mask.shape[0] - 1), min(i, room.mask.mask.shape[1] - 1)]:
                pts.append((room.mask.x0 + (i + .5) * room.mask.res, room.mask.y0 + (j + .5) * room.mask.res))
    while len(pts) < n:
        pts.append((room.cx, room.cy))
    return pts[:n]


# ----------------------------------------------------------------------------- résultats
@dataclass
class StoreyMEP:
    name: str
    height: float
    rooms: list[dict] = field(default_factory=list)          # synthèse par local (élec + clim)
    fixtures: list[dict] = field(default_factory=list)
    groups: list[dict] = field(default_factory=list)         # blocs sanitaires (gaine, débits, diamètres)
    lights: list[tuple] = field(default_factory=list)        # (x, y, type)
    sockets: list[tuple] = field(default_factory=list)       # (x, y, étanche)
    switches: list[tuple] = field(default_factory=list)
    units: list[dict] = field(default_factory=list)          # splits (x, y, CV, local)
    td: tuple = (0.0, 0.0)
    circuits: dict = field(default_factory=dict)             # {"eclairage": n, "prises": n, "clim": n}
    power_kw: float = 0.0
    current_a: float = 0.0
    feeder: dict = field(default_factory=dict)               # câble colonne vers le TD
    cool_kw: float = 0.0


@dataclass
class MEPResult:
    storeys: list[StoreyMEP] = field(default_factory=list)
    columns: list[dict] = field(default_factory=list)        # colonnes montantes (x, y, segments)
    tgbt: dict = field(default_factory=dict)
    quantities: dict = field(default_factory=dict)           # code → (quantité, détails)
    notes: list[str] = field(default_factory=list)


def _dn_pressure(q_ls: float, vmax: float) -> tuple[int, float]:
    for dn, di in PVC_PRESSION:
        v = q_ls / 1000 / (math.pi * (di / 1000) ** 2 / 4)
        if v <= vmax:
            return dn, v
    dn, di = PVC_PRESSION[-1]
    return dn, q_ls / 1000 / (math.pi * (di / 1000) ** 2 / 4)


def _simultaneity(n: int) -> float:
    return 1.0 if n <= 1 else max(0.2, 0.8 / math.sqrt(n - 1))


def _q(res, code: str, qty: float, label: str) -> None:
    if qty <= 0:
        return
    cur = res.quantities.setdefault(code, [0.0, []])
    cur[0] += qty
    cur[1].append((label, round(qty, 2)))


def design_mep(project, params: dict | None = None) -> MEPResult:
    P = params or load_params()
    U = P["usages"]
    E = P["electricite"]
    PL = P["plomberie"]
    CL = P["climatisation"]
    lum = P["luminaires"]
    res = MEPResult()
    storeys = project.storeys
    times_list = [project.n] if project.single_plan else [1] * len(storeys)
    if project.single_plan:
        storeys = storeys[:1]
    z = 0.0
    alt = []
    for st in project.storeys:
        alt.append(z)
        z += st.height
    columns: list[dict] = []
    tgbt_pos = None
    for k, st in enumerate(storeys):
        times = times_list[k]
        plan = st.plan
        sm = StoreyMEP(st.name if not project.single_plan else f"niveau courant × {times}", st.height)
        rooms = rooms_of(plan)
        stair = next((r for r in rooms if r.usage == "Escalier"), None)
        if stair:
            sm.td = (stair.cx, stair.cy)
        elif rooms:
            sm.td = (float(np.mean([r.cx for r in rooms])), float(np.mean([r.cy for r in rooms])))
        if tgbt_pos is None:
            tgbt_pos = sm.td
        p_light = p_pc = p_clim = 0.0
        n_light_pts = n_pc = n_splits = 0
        len_light = len_pc = len_clim = 0.0
        for r in rooms:
            u = U.get(r.usage, U["_defaut"])
            lt = lum[u["luminaire"]]
            n_l = math.ceil(u["eclairement"] * r.area / (lt["flux_lm"] * E["facteur_utilisation_maintenance"])) \
                if u["eclairement"] and r.area > 0.5 else 0
            n_p = max(u["prise_min"], math.ceil(r.area / u["prise_m2"])) if u["prise_m2"] else u["prise_min"]
            n_s = max(1, math.ceil(r.area / 40)) if n_l else 0
            # climatisation
            q_cool = 0.0
            units = []
            if u.get("clim_w_m2"):
                q_cool = (r.area * u["clim_w_m2"] + r.glazing * CL["apport_vitrage_w_m2"] * CL["facteur_protection"]) / 1000
                splits = CL["splits"]
                if q_cool <= splits[-1][1]:
                    cv, kw = next(sp for sp in splits if sp[1] >= q_cool)
                    units = [(cv, kw)]
                else:
                    units = [tuple(splits[-1])] * math.ceil(q_cool / splits[-1][1])
            pts = _points_in(r, n_l)
            sm.lights += [(x, y, u["luminaire"]) for x, y in pts]
            sock_pts = r.facade_cells[:: max(1, len(r.facade_cells) // max(1, n_p))][:n_p] if r.facade_cells else []
            sock_pts += _points_in(r, n_p - len(sock_pts))
            sm.sockets += [(x, y, bool(u.get("etanche"))) for x, y in sock_pts]
            sm.switches += [(r.cx, r.cy)] * n_s
            upos = r.facade_cells[:: max(1, len(r.facade_cells) // max(1, len(units)))][:len(units)] if r.facade_cells \
                else []
            upos += [(r.cx, r.cy)] * (len(units) - len(upos))
            for (cv, kw), (x, y) in zip(units, upos):
                sm.units.append({"x": x, "y": y, "cv": cv, "kw": kw, "local": r.name, "facade": bool(r.facade_cells)})
            dist = abs(r.cx - sm.td[0]) + abs(r.cy - sm.td[1])
            len_light += (dist + 3 * n_l) * 1.2 if n_l else 0
            len_pc += (dist + 4 * n_p) * 1.2 if n_p else 0
            len_clim += sum((dist + 3) * 1.2 for _ in units)
            p_light += n_l * lt["puissance_w"]
            p_pc += n_p * E["puissance_prise_w"] * E["ks_prises"]
            p_clim += sum(kw for cv, kw in units) * 1000 / E["eer_clim"]
            n_light_pts += n_l
            n_pc += n_p
            n_splits += len(units)
            sm.cool_kw += q_cool
            sm.rooms.append({"local": r.name, "usage": r.usage if r.usage != "_defaut" else "autre", "surface": round(r.area, 1),
                             "luminaires": n_l, "type_luminaire": lt["designation"], "prises": n_p, "interrupteurs": n_s,
                             "apports_kw": round(q_cool, 2), "splits": [f"{cv:g} CV" for cv, kw in units],
                             "etanche": bool(u.get("etanche"))})
            # quantités électricité / clim (par local)
            lbl = f"{sm.name} — {r.name}"
            if n_l:
                _q(res, "EL-PL1", times * 1, lbl)
                _q(res, "EL-PLS", times * (n_l - 1), lbl)
                _q(res, {"grille": "EL-LGR", "reglette": "EL-LRE", "hublot": "EL-LHU", "plafonnier": "EL-LPF"}[u["luminaire"]],
                   times * n_l, lbl)
            _q(res, "EL-INE" if u.get("etanche") else "EL-INT", times * n_s, lbl)
            _q(res, "EL-PCA", times * n_p, lbl)
            _q(res, "EL-PCE" if u.get("etanche") else "EL-PC", times * n_p, lbl)
            for cv, kw in units:
                _q(res, f"CL-S{str(cv).replace('.', '_')}", times * 1, lbl)
                _q(res, "EL-CLA", times * 1, lbl)
                L = 5.0 if r.facade_cells else 5.0 + min(abs(r.cx - sm.td[0]), 15)
                _q(res, "CL-LIA", times * L, lbl)
                _q(res, "CL-CON", times * L, lbl)
        # circuits et tableau divisionnaire
        nc_l = math.ceil(n_light_pts / E["points_par_circuit_eclairage"]) if n_light_pts else 0
        nc_p = math.ceil(n_pc / E["prises_par_circuit"]) if n_pc else 0
        sm.circuits = {"eclairage": nc_l, "prises": nc_p, "clim": n_splits}
        sm.power_kw = round((p_light + p_pc + p_clim) / 1000 * E["ks_general"], 2)
        sm.current_a = round(sm.power_kw * 1000 / (math.sqrt(3) * E["tension_v"] * E["cos_phi"]), 1)
        L_feed = abs(sm.td[0] - tgbt_pos[0]) + abs(sm.td[1] - tgbt_pos[1]) + (alt[k] if not project.single_plan else 0) + 5
        sec = None
        for s_mm2, iz in CABLE_SECTIONS:
            du = math.sqrt(3) * sm.current_a * L_feed * (0.0225 * E["cos_phi"] / s_mm2) / E["tension_v"]
            if iz >= 1.25 * sm.current_a and du <= E["chute_tension_max"]:
                sec = (s_mm2, du)
                break
        sec = sec or (CABLE_SECTIONS[-1][0], 0)
        sm.feeder = {"longueur_m": round(L_feed, 1), "section_mm2": sec[0], "chute_tension": round(sec[1] * 100, 2)}
        lbl = sm.name
        modules = 2 * (nc_l + nc_p + n_splits) + 4
        _q(res, "EL-TD" if modules <= 26 else "EL-TDM", times * 1, f"{lbl} : {nc_l + nc_p + n_splits} circuits")
        _q(res, "EL-D15", times * nc_l, f"{lbl} : circuits éclairage")
        _q(res, "EL-D20", times * (nc_p + n_splits), f"{lbl} : circuits prises et climatisation")
        _q(res, "EL-ID", times * max(1, math.ceil((nc_l + nc_p + n_splits) / 8)), f"{lbl} : différentiels 30 mA")
        cab = {6: "EL-C6", 10: "EL-C10", 16: "EL-C16", 25: "EL-C25", 35: "EL-C35", 70: "EL-C70", 95: "EL-C95", 150: "EL-C150"}[sec[0]]
        _q(res, cab, times * L_feed, f"{lbl} : colonne TGBT → TD ({sec[0]} mm²)")
        _q(res, "EL-TUB", times * (len_light + len_pc + len_clim), f"{lbl} : conduits des circuits")
        # ----------------------------------------------------------- plomberie
        flows = PL["appareils"]
        fx = list(plan.fixtures or [])
        sm.fixtures = fx
        groups: list[list[dict]] = []
        for f in fx:
            for g in groups:
                if any(abs(f["x"] - h["x"]) + abs(f["y"] - h["y"]) <= PL["regroupement_m"] for h in g):
                    g.append(f)
                    break
            else:
                groups.append([f])
        for g in groups:
            gx = float(np.mean([f["x"] for f in g])) + 0.6
            gy = float(np.mean([f["y"] for f in g]))
            col = next((c for c in columns if abs(c["x"] - gx) + abs(c["y"] - gy) <= 3.0), None)
            if col is None:
                col = {"id": f"C{len(columns) + 1}", "x": gx, "y": gy, "storeys": {}}
                columns.append(col)
            gx, gy = col["x"], col["y"]
            q_sum = sum(flows[f["type"]]["debit"] for f in g)
            qp = q_sum * _simultaneity(len(g))
            dn, v = _dn_pressure(qp, PL["vitesse_max_branche"])
            has_wc = any(f["type"] == "wc" for f in g)
            br_ef = br_eu = 0.0
            for f in g:
                L = (abs(f["x"] - gx) + abs(f["y"] - gy)) * 1.1 + 0.5
                br_ef += L
                br_eu += L
                ev = flows[f["type"]]["evacuation"]
                _q(res, f"PL-EV{ev}", times * L, f"{sm.name} — {f['local']} : {f['type']}")
                _q(res, {"wc": "PL-WC", "lavabo": "PL-LAV", "douche": "PL-DOU", "evier": "PL-EVI",
                         "urinoir": "PL-URI"}[f["type"]], times * 1, f"{sm.name} — {f['local']}")
                if f["type"] == "douche":
                    _q(res, "PL-MDO", times * 1, f"{sm.name} — {f['local']}")
                    _q(res, "PL-SIP", times * 1, f"{sm.name} — {f['local']}")
            _q(res, "PL-EF20", times * br_ef, f"{sm.name} : branchements d'appareils (Ø20)")
            _q(res, "PL-VAN", times * 1, f"{sm.name} : vanne d'arrêt du bloc {col['id']}")
            if any(f["type"] == "douche" for f in g):
                _q(res, "PL-CHE", times * 1, f"{sm.name} : chauffe-eau du bloc {col['id']}")
            prev = col["storeys"].get(k, {"n": 0, "q": 0.0, "wc": False})
            col["storeys"][k] = {"n": prev["n"] + len(g), "q": prev["q"] + q_sum, "wc": prev["wc"] or has_wc}
            sm.groups.append({"colonne": col["id"], "x": round(gx, 2), "y": round(gy, 2), "appareils": len(g),
                              "debit_base_ls": round(q_sum, 3), "debit_probable_ls": round(qp, 3),
                              "dn_alimentation": dn, "vitesse_ms": round(v, 2),
                              "dn_chute": 100 if has_wc else 90})
        res.storeys.append(sm)
    # colonnes montantes : chaque tronçon porte les appareils des étages supérieurs
    # (plan unique répété : la colonne traverse tous les niveaux réels)
    if project.single_plan:
        levels = [(project.storeys[j].name, project.storeys[j].height, 0) for j in range(project.n)]
    else:
        levels = [(st.name, st.height, j) for j, st in enumerate(storeys)]
    for col in columns:
        segs = []
        for k, (name, h, _) in enumerate(levels):
            above = [col["storeys"][src] for _, _, src in levels[k:] if src in col["storeys"]]
            n = sum(a["n"] for a in above)
            if not n:
                continue
            q = sum(a["q"] for a in above)
            qp = q * _simultaneity(n)
            dn, v = _dn_pressure(qp, PL["vitesse_max_colonne"])
            wc = any(a["wc"] for a in above)
            segs.append({"niveau": name, "appareils": n, "debit_probable_ls": round(qp, 3), "dn": dn,
                         "vitesse_ms": round(v, 2), "chute_dn": 100 if wc else 90})
            _q(res, f"PL-EF{dn}", h, f"Colonne {col['id']} — {name}")
            _q(res, "PL-EV100" if wc else "PL-EV90", h, f"Chute {col['id']} — {name}")
        col["segments"] = segs
        # collecteur en pied de colonne vers l'extérieur + regard
        L = 8.0
        _q(res, "PL-COL", L, f"Collecteur en pied de colonne {col['id']}")
        _q(res, "PL-REG", 2, f"Regards de la colonne {col['id']}")
    res.columns = columns
    occupants = sum(r["surface"] for s in res.storeys for r in s.rooms
                    if U.get(r["usage"], U["_defaut"]).get("clim_w_m2")) / CL["occupation_m2_par_personne"]
    occupants *= times_list[0] if project.single_plan else 1
    if columns:
        _q(res, "PL-FOS", 1, f"Fosse septique : {occupants:.0f} usagers estimés")
        res.notes.append(f"Fosse septique dimensionnée pour {occupants:.0f} usagers (à remplacer par un "
                         "raccordement au réseau public s'il existe).")
    # TGBT
    p_tot = sum(s.power_kw * (times_list[0] if project.single_plan else 1) for s in res.storeys) * 0.9
    i_tot = p_tot * 1000 / (math.sqrt(3) * E["tension_v"] * E["cos_phi"])
    res.tgbt = {"puissance_kw": round(p_tot, 1), "puissance_kva": round(p_tot / E["cos_phi"], 1),
                "courant_a": round(i_tot, 1), "x": tgbt_pos[0] if tgbt_pos else 0, "y": tgbt_pos[1] if tgbt_pos else 0}
    _q(res, "EL-TGB", 1, f"TGBT : {res.tgbt['puissance_kva']} kVA")
    _q(res, "EL-DGT", 1, f"Disjoncteur de tête : {res.tgbt['courant_a']:.0f} A")
    if i_tot > 100:
        res.notes.append(f"Courant total {i_tot:.0f} A > 100 A : poste de transformation / tarif jaune ou vert à "
                         "étudier avec le distributeur (CIE).")
    big = [u for s in res.storeys for u in s.units]
    if any(s.cool_kw > 30 for s in res.storeys):
        res.notes.append("Puissances frigorifiques importantes par plateau : un système VRV ou gainable est à "
                         "comparer aux splits individuels.")
    res.notes.append(f"{len(big)} unités de climatisation, {sum(len(s.lights) for s in res.storeys)} luminaires, "
                     f"{sum(len(s.fixtures) for s in res.storeys)} appareils sanitaires (par niveau type pour un plan "
                     "unique).")
    return res
