# Koordin-IA

Dimensionnement de bâtiments en **béton armé** à partir des plans d'architecte
(**DWG / DXF / PDF**), avec descente de charges, note de calcul et plans d'exécution.

| Règlement | Domaine | État |
|---|---|---|
| **BAEL 91 mod. 99** | Béton armé | ✅ disponible |
| **Eurocode 2** (NF EN 1992-1-1/NA) | Béton armé | ✅ disponible |
| **CM66** | Charpente métallique | 🔜 phase 2 |
| **Eurocode 3** | Charpente métallique | 🔜 phase 2 |

> ⚠️ Outil d'aide au pré-dimensionnement. Les résultats doivent être vérifiés et
> visés par un ingénieur structure avant exécution.

## Ce que fait le programme

```
Plan DWG / DXF / PDF
   → reconnaissance : poteaux, files (axes), poutres, panneaux de plancher
   → modèle structurel (modele.json, modifiable) + plan de contrôle DXF
   → descente de charges : planchers → poutres → poteaux → semelles
        (dégression NF P06-001, majorations 10 % / 15 % voisins de rive)
   → dimensionnement BAEL ou EC2 : poteaux (par niveau), poutres, semelles isolées
   → sorties : note de calcul PDF/HTML, plans DXF, métré béton/acier, résultats JSON
```

### Fichiers produits

| Fichier | Contenu |
|---|---|
| `note_de_calcul.pdf` / `.html` | Hypothèses, charges, descente de charges, poteaux, poutres, semelles, métré |
| `plan_coffrage_etage_courant.dxf` | Axes, cotes, poteaux, poutres (b×h), sens porteur des planchers |
| `plan_coffrage_terrasse.dxf` | Idem pour la terrasse |
| `plan_fondations.dxf` | Semelles isolées repérées et cotées |
| `plans_ferraillage.dxf` | Sections de poteaux, élévations + coupes de poutres, nappes des semelles (par type) |
| `controle_modele.dxf` | Plan importé (gris) superposé au modèle reconnu (rouge) |
| `modele.json` | Modèle structurel éditable |
| `resultats.json` | Résultats synthétiques + métré |

## Installation

```bash
pip install -e .
```

**Fichiers DWG** : le format DWG est fermé. Deux possibilités :
1. installer le convertisseur gratuit **ODA File Converter**
   (<https://www.opendesign.com/guestfiles/oda_file_converter>), puis donner le `.dwg` directement ;
2. ou, dans AutoCAD, `ENREGSOUS` → **DXF**, et donner le `.dxf`.

## Utilisation

```bash
# 1. Lire le plan et proposer le modèle (à contrôler)
koordinia detecter plan_etage.dwg --niveaux 4 --hauteur 3.06 -o projet/

#    → ouvrir projet/controle_modele.dxf dans AutoCAD pour vérifier,
#      corriger si besoin projet/modele.json (sections, poutres…)

# 2. Calculer (BAEL ou Eurocode 2)
koordinia calculer --modele projet/modele.json --norme bael --fc 25 --fe 400 --sol 0.2 -o projet/

# En une seule étape, depuis un PDF au 1/100 :
koordinia calculer plan.pdf --echelle 100 --niveaux 4 --norme ec2 -o projet/

# Plan d'exemple pour essayer :
koordinia exemple -o essai/ && koordinia calculer essai/exemple_plan.dxf --niveaux 5 -o essai/res
```

Principales options de `calculer` (`koordinia calculer -h` pour la liste complète) :

| Option | Défaut | Rôle |
|---|---|---|
| `--norme` | `bael` | `bael` ou `ec2` |
| `--fc`, `--fe` | 25 / 400 (BAEL), 25 / 500 (EC2) | Matériaux (MPa) |
| `--plancher` | `corps_creux` | `corps_creux` (1 sens) ou `dalle_pleine` (2 sens) |
| `--g-plancher` | 2,85 kN/m² | Poids propre plancher (16+4) |
| `--g-revetement` | 2,00 kN/m² | Revêtements + cloisons |
| `--q` / `--q-terrasse` | 1,5 / 1,0 kN/m² | Charges d'exploitation |
| `--facade` | 0 kN/m | Maçonnerie sur poutres de rive |
| `--sol` | 0,20 MPa | Contrainte admissible du sol |
| `--echelle` | détectée | Échelle d'un plan PDF (100 = 1/100) |
| `--unites` | `$INSUNITS` | Unités d'un DXF sans unité (`mm`, `cm`, `m`) |

## Comment les plans sont lus

- **DWG/DXF** : les poteaux sont cherchés sur un calque dont le nom contient
  `POT`, `POTEAU`, `COLUMN`… À défaut, le programme prend les petits rectangles
  hachurés ou remplis (15 à 120 cm), puis tous les petits rectangles.
  Les blocs sont explosés automatiquement.
- **PDF** : seuls les PDF **vectoriels** sont exploitables (exports AutoCAD/Revit/ArchiCAD).
  Les poteaux sont généralement les rectangles remplis. L'échelle est lue dans le
  cartouche (« Ech : 1/100 ») ou imposée par `--echelle`. Les **PDF scannés sont refusés**.
- Les poteaux alignés forment les files. Les poutres relient deux poteaux consécutifs
  d'une file, avec une hauteur prédimensionnée à L/12. Chaque maille complète devient
  un panneau de plancher.

## Hypothèses et limites actuelles

- Bâtiment à ossature poteaux-poutres, **étages identiques** (un plan d'étage courant + nombre de niveaux).
- Poteaux en compression centrée, lf = 0,7·l0. Leur section est augmentée automatiquement si elle est insuffisante.
- Poutres : moments par **méthode forfaitaire simplifiée**. Un avertissement apparaît si ses
  conditions ne sont pas remplies (rapport de portées, Q > 2G).
- Fissuration peu préjudiciable ; pas de vérification ELS des flèches ni de l'ouverture des fissures.
- Pas encore traités : voiles, escaliers, vent, séisme (RPA / EC8), longrines, semelles filantes, radiers.

## Feuille de route

1. Charpente métallique : **CM66** et **Eurocode 3**
2. Calcul de continuité (Caquot / EF), ELS (flèches), voiles, escaliers
3. Vent et séisme (EC1, EC8, RPA)
4. Interface web pour visualiser et corriger le modèle
5. Lecture IFC (Revit, ArchiCAD), plans multi-niveaux différents

## Tests

```bash
pip install -e .[dev]
pytest
```
