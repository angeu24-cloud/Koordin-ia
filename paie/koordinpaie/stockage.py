"""Stockage : base SQLite (comptes, entreprise, salariés, contrats, avenants, périodes, bulletins)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

ROLES = "admin", "gestionnaire", "lecteur"
TYPES_CONTRAT = ("CDI", "CDD", "JOURNALIER")
SESSION_JOURS = 14

SCHEMA = """
CREATE TABLE IF NOT EXISTS utilisateurs (
    id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, nom TEXT NOT NULL, role TEXT NOT NULL,
    mdp TEXT NOT NULL, cree REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessions (
    jeton TEXT PRIMARY KEY, utilisateur_id INTEGER NOT NULL, expire REAL NOT NULL);
CREATE TABLE IF NOT EXISTS reglages (cle TEXT PRIMARY KEY, valeur TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS salaries (
    id INTEGER PRIMARY KEY, matricule TEXT UNIQUE NOT NULL, nom TEXT NOT NULL, prenoms TEXT NOT NULL DEFAULT '',
    donnees TEXT NOT NULL DEFAULT '{}', actif INTEGER NOT NULL DEFAULT 1, cree REAL NOT NULL, modifie REAL NOT NULL);
CREATE TABLE IF NOT EXISTS contrats (
    id INTEGER PRIMARY KEY, salarie_id INTEGER NOT NULL, type TEXT NOT NULL, date_debut TEXT NOT NULL,
    date_fin TEXT, statut TEXT NOT NULL DEFAULT 'actif', donnees TEXT NOT NULL DEFAULT '{}',
    cree REAL NOT NULL, modifie REAL NOT NULL);
CREATE TABLE IF NOT EXISTS avenants (
    id INTEGER PRIMARY KEY, contrat_id INTEGER NOT NULL, date_effet TEXT NOT NULL, objet TEXT NOT NULL,
    modifications TEXT NOT NULL DEFAULT '{}', cree REAL NOT NULL);
CREATE TABLE IF NOT EXISTS periodes (
    id INTEGER PRIMARY KEY, annee INTEGER NOT NULL, mois INTEGER NOT NULL, statut TEXT NOT NULL DEFAULT 'ouverte',
    cloture REAL, UNIQUE (annee, mois));
CREATE TABLE IF NOT EXISTS bulletins (
    id INTEGER PRIMARY KEY, periode_id INTEGER NOT NULL, salarie_id INTEGER NOT NULL, contrat_id INTEGER NOT NULL,
    variables TEXT NOT NULL DEFAULT '{}', resultat TEXT, instantane TEXT,
    UNIQUE (periode_id, contrat_id));
CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY, utilisateur_id INTEGER, ts REAL NOT NULL, texte TEXT NOT NULL);
"""

# Champs du contrat qu'un avenant peut modifier
CHAMPS_AVENANT = ("poste", "categorie", "salaire_base", "sursalaire", "transport", "primes_fixes", "lieu",
                  "heures_mensuelles", "date_fin", "mode")


def hacher(mdp: str, sel: bytes | None = None) -> str:
    sel = sel or os.urandom(16)
    dk = hashlib.scrypt(mdp.encode(), salt=sel, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${sel.hex()}${dk.hex()}"


def verifier(mdp: str, stocke: str) -> bool:
    try:
        _, sel, dk = stocke.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hacher(mdp, bytes.fromhex(sel)).split("$")[2], dk)


class Stockage:
    def __init__(self, dossier: str | Path):
        self.dossier = Path(dossier)
        self.dossier.mkdir(parents=True, exist_ok=True)
        self._verrou = threading.Lock()
        self.db = sqlite3.connect(self.dossier / "koordinpaie.sqlite", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def fermer(self) -> None:
        with self._verrou:
            self.db.close()

    # ------------------------------------------------------------------ outils
    def q(self, sql: str, args: tuple = (), un: bool = False):
        with self._verrou:
            rows = self.db.execute(sql, args).fetchall()
        if un:
            return dict(rows[0]) if rows else None
        return [dict(r) for r in rows]

    def x(self, sql: str, args: tuple = ()) -> int:
        with self._verrou:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return cur.lastrowid

    def journaliser(self, uid: int | None, texte: str) -> None:
        self.x("INSERT INTO journal(utilisateur_id,ts,texte) VALUES(?,?,?)", (uid, time.time(), texte))

    def journal(self, limite: int = 50) -> list[dict]:
        return self.q("SELECT j.ts, j.texte, u.nom FROM journal j LEFT JOIN utilisateurs u ON u.id=j.utilisateur_id "
                      "ORDER BY j.id DESC LIMIT ?", (limite,))

    # ------------------------------------------------------------------ comptes
    def nb_utilisateurs(self) -> int:
        return self.q("SELECT COUNT(*) n FROM utilisateurs", un=True)["n"]

    def creer_utilisateur(self, email: str, nom: str, mdp: str, role: str) -> int:
        if role not in ROLES:
            raise ValueError("Rôle invalide.")
        if len(mdp) < 8:
            raise ValueError("Le mot de passe doit contenir au moins 8 caractères.")
        email = email.strip().lower()
        if not email or "@" not in email:
            raise ValueError("Adresse électronique invalide.")
        if self.q("SELECT id FROM utilisateurs WHERE email=?", (email,), un=True):
            raise ValueError("Un compte existe déjà avec cette adresse.")
        return self.x("INSERT INTO utilisateurs(email,nom,role,mdp,cree) VALUES(?,?,?,?,?)",
                      (email, nom.strip() or email, role, hacher(mdp), time.time()))

    def utilisateurs(self) -> list[dict]:
        return self.q("SELECT id, email, nom, role, cree FROM utilisateurs ORDER BY id")

    def modifier_utilisateur(self, uid: int, role: str | None = None, mdp: str | None = None) -> None:
        if role:
            if role not in ROLES:
                raise ValueError("Rôle invalide.")
            if role != "admin" and self.q("SELECT role FROM utilisateurs WHERE id=?", (uid,), un=True)["role"] == "admin" \
                    and self.q("SELECT COUNT(*) n FROM utilisateurs WHERE role='admin'", un=True)["n"] <= 1:
                raise ValueError("Il doit rester au moins un administrateur.")
            self.x("UPDATE utilisateurs SET role=? WHERE id=?", (role, uid))
        if mdp:
            if len(mdp) < 8:
                raise ValueError("Le mot de passe doit contenir au moins 8 caractères.")
            self.x("UPDATE utilisateurs SET mdp=? WHERE id=?", (hacher(mdp), uid))
            self.x("DELETE FROM sessions WHERE utilisateur_id=?", (uid,))

    def supprimer_utilisateur(self, uid: int) -> None:
        u = self.q("SELECT role FROM utilisateurs WHERE id=?", (uid,), un=True)
        if u and u["role"] == "admin" and self.q("SELECT COUNT(*) n FROM utilisateurs WHERE role='admin'", un=True)["n"] <= 1:
            raise ValueError("Il doit rester au moins un administrateur.")
        self.x("DELETE FROM sessions WHERE utilisateur_id=?", (uid,))
        self.x("DELETE FROM utilisateurs WHERE id=?", (uid,))

    def authentifier(self, email: str, mdp: str) -> dict | None:
        u = self.q("SELECT * FROM utilisateurs WHERE email=?", (email.strip().lower(),), un=True)
        return u if u and verifier(mdp, u["mdp"]) else None

    def nouvelle_session(self, uid: int) -> str:
        jeton = secrets.token_urlsafe(32)
        self.x("INSERT INTO sessions(jeton,utilisateur_id,expire) VALUES(?,?,?)",
               (jeton, uid, time.time() + SESSION_JOURS * 86400))
        return jeton

    def utilisateur_session(self, jeton: str | None) -> dict | None:
        if not jeton:
            return None
        r = self.q("SELECT u.id, u.email, u.nom, u.role, s.expire FROM sessions s JOIN utilisateurs u "
                   "ON u.id=s.utilisateur_id WHERE s.jeton=?", (jeton,), un=True)
        if not r or r["expire"] < time.time():
            return None
        r.pop("expire")
        return r

    def fin_session(self, jeton: str) -> None:
        self.x("DELETE FROM sessions WHERE jeton=?", (jeton,))

    # ------------------------------------------------------------------ réglages
    def reglage(self, cle: str, defaut=None):
        r = self.q("SELECT valeur FROM reglages WHERE cle=?", (cle,), un=True)
        return json.loads(r["valeur"]) if r else defaut

    def regler(self, cle: str, valeur) -> None:
        self.x("INSERT OR REPLACE INTO reglages(cle,valeur) VALUES(?,?)", (cle, json.dumps(valeur, ensure_ascii=False)))

    # ------------------------------------------------------------------ salariés
    @staticmethod
    def _salarie(r: dict | None) -> dict | None:
        if not r:
            return None
        d = json.loads(r.pop("donnees") or "{}")
        d.update(r)
        d["actif"] = bool(d["actif"])
        return d

    def salaries(self, tous: bool = True) -> list[dict]:
        sql = "SELECT * FROM salaries" + ("" if tous else " WHERE actif=1") + " ORDER BY nom, prenoms"
        return [self._salarie(r) for r in self.q(sql)]

    def salarie(self, sid: int) -> dict | None:
        return self._salarie(self.q("SELECT * FROM salaries WHERE id=?", (sid,), un=True))

    def prochain_matricule(self) -> str:
        n = self.q("SELECT COUNT(*) n FROM salaries", un=True)["n"] + 1
        while self.q("SELECT 1 FROM salaries WHERE matricule=?", (f"S{n:04d}",), un=True):
            n += 1
        return f"S{n:04d}"

    def enregistrer_salarie(self, d: dict, sid: int | None = None) -> int:
        d = dict(d)
        nom = str(d.pop("nom", "")).strip()
        if not nom:
            raise ValueError("Le nom est obligatoire.")
        prenoms = str(d.pop("prenoms", "")).strip()
        matricule = str(d.pop("matricule", "") or "").strip() or (
            self.salarie(sid)["matricule"] if sid else self.prochain_matricule())
        actif = 1 if d.pop("actif", True) else 0
        for k in ("id", "cree", "modifie"):
            d.pop(k, None)
        doublon = self.q("SELECT id FROM salaries WHERE matricule=?", (matricule,), un=True)
        if doublon and doublon["id"] != sid:
            raise ValueError(f"Le matricule {matricule} est déjà attribué.")
        now = time.time()
        donnees = json.dumps(d, ensure_ascii=False)
        if sid:
            self.x("UPDATE salaries SET matricule=?, nom=?, prenoms=?, donnees=?, actif=?, modifie=? WHERE id=?",
                   (matricule, nom, prenoms, donnees, actif, now, sid))
            return sid
        return self.x("INSERT INTO salaries(matricule,nom,prenoms,donnees,actif,cree,modifie) VALUES(?,?,?,?,?,?,?)",
                      (matricule, nom, prenoms, donnees, actif, now, now))

    def supprimer_salarie(self, sid: int) -> None:
        if self.q("SELECT 1 FROM bulletins b JOIN periodes p ON p.id=b.periode_id "
                  "WHERE b.salarie_id=? AND p.statut='cloturee'", (sid,), un=True):
            raise ValueError("Ce salarié a des bulletins clôturés : marquez-le inactif au lieu de le supprimer.")
        for c in self.q("SELECT id FROM contrats WHERE salarie_id=?", (sid,)):
            self.x("DELETE FROM avenants WHERE contrat_id=?", (c["id"],))
        self.x("DELETE FROM bulletins WHERE salarie_id=?", (sid,))
        self.x("DELETE FROM contrats WHERE salarie_id=?", (sid,))
        self.x("DELETE FROM salaries WHERE id=?", (sid,))

    # ------------------------------------------------------------------ contrats
    @staticmethod
    def _contrat(r: dict | None) -> dict | None:
        if not r:
            return None
        d = json.loads(r.pop("donnees") or "{}")
        d.update(r)
        return d

    def contrats(self, salarie_id: int | None = None) -> list[dict]:
        if salarie_id:
            rows = self.q("SELECT * FROM contrats WHERE salarie_id=? ORDER BY date_debut DESC", (salarie_id,))
        else:
            rows = self.q("SELECT * FROM contrats ORDER BY date_debut DESC")
        return [self._contrat(r) for r in rows]

    def contrat(self, cid: int) -> dict | None:
        return self._contrat(self.q("SELECT * FROM contrats WHERE id=?", (cid,), un=True))

    def enregistrer_contrat(self, salarie_id: int, d: dict, cid: int | None = None) -> int:
        d = dict(d)
        type_ = str(d.pop("type", "CDI")).upper()
        if type_ not in TYPES_CONTRAT:
            raise ValueError("Type de contrat invalide (CDI, CDD ou JOURNALIER).")
        debut = str(d.pop("date_debut", "") or "")[:10]
        if not debut:
            raise ValueError("La date de début est obligatoire.")
        fin = str(d.pop("date_fin", "") or "")[:10] or None
        if type_ == "CDD" and not fin:
            raise ValueError("Un CDD doit avoir une date de fin.")
        if fin and fin < debut:
            raise ValueError("La date de fin précède la date de début.")
        statut = d.pop("statut", None)
        for k in ("id", "salarie_id", "cree", "modifie", "avenants"):
            d.pop(k, None)
        now = time.time()
        donnees = json.dumps(d, ensure_ascii=False)
        if cid:
            self.x("UPDATE contrats SET type=?, date_debut=?, date_fin=?, statut=COALESCE(?,statut), donnees=?, "
                   "modifie=? WHERE id=?", (type_, debut, fin, statut, donnees, now, cid))
            return cid
        return self.x("INSERT INTO contrats(salarie_id,type,date_debut,date_fin,statut,donnees,cree,modifie) "
                      "VALUES(?,?,?,?,?,?,?,?)", (salarie_id, type_, debut, fin, statut or "actif", donnees, now, now))

    def terminer_contrat(self, cid: int, date_fin: str, motif: str) -> None:
        c = self.contrat(cid)
        if date_fin < c["date_debut"]:
            raise ValueError("La date de fin précède la date de début.")
        donnees = {k: v for k, v in c.items() if k not in ("id", "salarie_id", "type", "date_debut", "date_fin",
                                                           "statut", "cree", "modifie")}
        donnees["motif_fin"] = motif
        self.x("UPDATE contrats SET date_fin=?, statut='termine', donnees=?, modifie=? WHERE id=?",
               (date_fin[:10], json.dumps(donnees, ensure_ascii=False), time.time(), cid))

    def supprimer_contrat(self, cid: int) -> None:
        if self.q("SELECT 1 FROM bulletins b JOIN periodes p ON p.id=b.periode_id "
                  "WHERE b.contrat_id=? AND p.statut='cloturee'", (cid,), un=True):
            raise ValueError("Ce contrat figure sur des bulletins clôturés : terminez-le au lieu de le supprimer.")
        self.x("DELETE FROM bulletins WHERE contrat_id=?", (cid,))
        self.x("DELETE FROM avenants WHERE contrat_id=?", (cid,))
        self.x("DELETE FROM contrats WHERE id=?", (cid,))

    def avenants(self, cid: int) -> list[dict]:
        out = self.q("SELECT * FROM avenants WHERE contrat_id=? ORDER BY date_effet, id", (cid,))
        for a in out:
            a["modifications"] = json.loads(a["modifications"])
        return out

    def ajouter_avenant(self, cid: int, date_effet: str, objet: str, modifications: dict) -> int:
        c = self.contrat(cid)
        if not c:
            raise LookupError("Contrat introuvable.")
        if date_effet[:10] < c["date_debut"]:
            raise ValueError("L'avenant prend effet avant le début du contrat.")
        modifs = {k: v for k, v in modifications.items() if k in CHAMPS_AVENANT and v not in (None, "")}
        if not modifs:
            raise ValueError("L'avenant ne modifie aucun élément du contrat.")
        aid = self.x("INSERT INTO avenants(contrat_id,date_effet,objet,modifications,cree) VALUES(?,?,?,?,?)",
                     (cid, date_effet[:10], objet.strip() or "Avenant", json.dumps(modifs, ensure_ascii=False),
                      time.time()))
        if "date_fin" in modifs:   # renouvellement d'un CDD
            self.x("UPDATE contrats SET date_fin=?, statut='actif' WHERE id=?", (str(modifs["date_fin"])[:10], cid))
        return aid

    def supprimer_avenant(self, aid: int) -> None:
        self.x("DELETE FROM avenants WHERE id=?", (aid,))

    def contrat_au(self, cid: int, jour: str) -> dict:
        """Clauses du contrat en vigueur à une date : contrat initial + avenants déjà entrés en vigueur."""
        c = self.contrat(cid)
        for a in self.avenants(cid):
            if a["date_effet"] <= jour:
                c.update({k: v for k, v in a["modifications"].items() if k != "date_fin"})
        return c

    # ------------------------------------------------------------------ périodes et bulletins
    def periodes(self) -> list[dict]:
        return self.q("SELECT * FROM periodes ORDER BY annee DESC, mois DESC")

    def periode(self, pid: int) -> dict | None:
        return self.q("SELECT * FROM periodes WHERE id=?", (pid,), un=True)

    def creer_periode(self, annee: int, mois: int) -> int:
        if not (1 <= mois <= 12 and 2000 <= annee <= 2100):
            raise ValueError("Période invalide.")
        if self.q("SELECT 1 FROM periodes WHERE annee=? AND mois=?", (annee, mois), un=True):
            raise ValueError("Cette période existe déjà.")
        return self.x("INSERT INTO periodes(annee,mois) VALUES(?,?)", (annee, mois))

    def supprimer_periode(self, pid: int) -> None:
        p = self.periode(pid)
        if p and p["statut"] == "cloturee":
            raise ValueError("Une période clôturée ne peut pas être supprimée : rouvrez-la d'abord.")
        self.x("DELETE FROM bulletins WHERE periode_id=?", (pid,))
        self.x("DELETE FROM periodes WHERE id=?", (pid,))

    def bulletins(self, pid: int) -> list[dict]:
        out = self.q("SELECT * FROM bulletins WHERE periode_id=? ORDER BY id", (pid,))
        for b in out:
            self._decoder_bulletin(b)
        return out

    def bulletin(self, bid: int) -> dict | None:
        b = self.q("SELECT * FROM bulletins WHERE id=?", (bid,), un=True)
        return self._decoder_bulletin(b) if b else None

    @staticmethod
    def _decoder_bulletin(b: dict) -> dict:
        b["variables"] = json.loads(b["variables"] or "{}")
        b["resultat"] = json.loads(b["resultat"]) if b["resultat"] else None
        b["instantane"] = json.loads(b["instantane"]) if b["instantane"] else None
        return b

    def ajouter_bulletin(self, pid: int, sid: int, cid: int, variables: dict) -> int:
        return self.x("INSERT OR IGNORE INTO bulletins(periode_id,salarie_id,contrat_id,variables) VALUES(?,?,?,?)",
                      (pid, sid, cid, json.dumps(variables, ensure_ascii=False)))

    def modifier_variables(self, bid: int, variables: dict) -> None:
        self.x("UPDATE bulletins SET variables=? WHERE id=?", (json.dumps(variables, ensure_ascii=False), bid))

    def figer_bulletin(self, bid: int, resultat: dict | None, instantane: dict | None) -> None:
        self.x("UPDATE bulletins SET resultat=?, instantane=? WHERE id=?",
               (json.dumps(resultat, ensure_ascii=False) if resultat else None,
                json.dumps(instantane, ensure_ascii=False) if instantane else None, bid))

    def statut_periode(self, pid: int, statut: str) -> None:
        self.x("UPDATE periodes SET statut=?, cloture=? WHERE id=?",
               (statut, time.time() if statut == "cloturee" else None, pid))

    def supprimer_bulletin(self, bid: int) -> None:
        self.x("DELETE FROM bulletins WHERE id=?", (bid,))
