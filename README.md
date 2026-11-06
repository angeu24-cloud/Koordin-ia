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
Plan DWG / DXF / PDF  (dessin unique ou planches multiples)
   → choix de la planche « étage courant » (cadres et titres détectés)
   → reconnaissance : poteaux, files et repères d'axes de l'architecte, poutres,
        contour du plancher déduit des murs (balcons compris)
   → modèle structurel (modele.json, modifiable) + plan de contrôle DXF
   → descente de charges par surfaces d'influence (trames régulières ou irrégulières)
        planchers → poutres → poteaux → semelles
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

**Fichiers DWG** : le format DWG est fermé. Le `.dwg` est lu directement si l'un de ces
convertisseurs est installé (sinon, enregistrer le plan en DXF depuis AutoCAD : `ENREGSOUS` → DXF) :

1. **LibreDWG** (libre, testé avec AutoCAD 2018) : outil `dwg2dxf` dans le `PATH`,
   ou chemin donné par la variable `KOORDINIA_DWG2DXF`. Compilation :
   ```bash
   git clone --depth 1 https://github.com/LibreDWG/libredwg && cd libredwg
   git submodule update --init && sh autogen.sh
   ./configure --disable-bindings --disable-docs --prefix=$HOME/.local && make -j && make install
   ```
2. **ODA File Converter** (gratuit) : <https://www.opendesign.com/guestfiles/oda_file_converter>.

## Application web (équipe, navigateur, tablette)

```bash
pip install -e .
koordinia serveur --port 8000 --donnees ./donnees_koordinia
# puis ouvrir http://adresse-du-serveur:8000 depuis un ordinateur ou une tablette
```

L'application reprend tout le moteur, sans aucune ligne de commande pour l'utilisateur :

| Onglet | Contenu |
|---|---|
| **Plan & niveaux** | dépôt du DWG/DXF/PDF ; planches et niveaux détectés (hauteurs et planche de chaque niveau modifiables) |
| **Hypothèses** | règlement (BAEL, EC2), matériaux, plancher, charges, contrainte du sol |
| **Géotechnique** | import du rapport, valeurs extraites avec leur phrase source, correction, **validation** |
| **Calcul** | lancement en tâche de fond, chiffres clés, métré, points à vérifier, journal |
| **Modèle 2D / 3D** | plan de chaque plancher (zoom, déplacement, toucher un élément pour ses résultats) et **vue 3D** du bâtiment |
| **Plans & note** | téléchargement de la note de calcul et des plans DXF |
| **Équipe** | membres et rôles (propriétaire, éditeur, lecteur), journal d'activité partagé |

- **Comptes et sécurité** : mots de passe chiffrés (scrypt), session par cookie protégé,
  droits vérifiés à chaque requête. Le lecteur consulte, l'éditeur modifie et calcule,
  le propriétaire gère l'équipe.
- **Données** : une base SQLite et un dossier par projet (plans, configuration,
  résultats), dans le dossier `--donnees`, à sauvegarder régulièrement.
- **Installable** sur tablette ou ordinateur (« Ajouter à l'écran d'accueil »).
  three.js est intégré à l'application, qui fonctionne donc sur un réseau local sans internet.
- **Mise en service pour une équipe** : sur un serveur du bureau ou un serveur loué, avec
  l'image Docker fournie (`Dockerfile`, LibreDWG inclus pour les DWG). Pour un accès par
  internet, placer l'application derrière un proxy HTTPS (Caddy, Nginx).

## Démarrer un nouveau projet

Chaque projet a son dossier et son fichier `koordinia.json`. Ce fichier contient le plan,
la norme, les matériaux, les charges, la contrainte du sol et le choix des planches. Les
calculs sont ainsi reproductibles, archivables, et faciles à relancer après une
modification d'hypothèse.

```bash
koordinia init Projets/Immeuble_X --plan plans_archi.dwg --nom "Immeuble X R+4" --norme bael
#   → Projets/Immeuble_X/koordinia.json   (à compléter : charges, sol…)
#   → Projets/Immeuble_X/plans/plans_archi.dwg

koordinia niveaux  --config Projets/Immeuble_X/koordinia.json   # contrôle niveaux / planches
koordinia detecter --config Projets/Immeuble_X/koordinia.json   # modèle + plans de contrôle
koordinia calculer --config Projets/Immeuble_X/koordinia.json   # → Projets/Immeuble_X/resultats/

# variante : une option en ligne de commande remplace la configuration
koordinia calculer --config Projets/Immeuble_X/koordinia.json --norme ec2 -o Projets/Immeuble_X/variante_ec2
```

Extrait de `koordinia.json` :

```json
{
  "projet":    { "nom": "Immeuble X R+4", "plan": "plans/plans_archi.dwg", "tous_niveaux": true },
  "lecture":   { "affectation": null, "hauteurs": "RDC=3.29", "calque_poteaux": null },
  "reglement": { "norme": "bael", "fc": 25, "fe": 400, "enrobage": 0.03 },
  "charges":   { "plancher": "corps_creux", "g_plancher": 3.30, "q": 2.5, "q_terrasse": 1.5, "facade": 7.0 },
  "sol":       { "sol": 0.20 }
}
```

La configuration utilisée est recopiée dans `resultats/resultats.json`, ce qui assure la
traçabilité de chaque calcul.

## Utilisation

```bash
# 0. Si le DWG contient plusieurs planches (RDC, étages, façades…), les lister
koordinia planches plans_archi.dwg

# 1. Lire la planche de l'étage courant et proposer le modèle (à contrôler)
koordinia detecter plans_archi.dwg --planche "etage courant" --niveaux 5 --hauteur 3.40 -o projet/

#    → ouvrir projet/controle_modele.dxf dans AutoCAD pour vérifier,
#      corriger si besoin projet/modele.json (sections, poutres…)

# 1 bis. Modéliser TOUS les niveaux (une planche par niveau, hauteurs lues sur les coupes)
koordinia niveaux plans_archi.dwg                       # niveaux, hauteurs et planches retenues
koordinia detecter plans_archi.dwg --tous-niveaux -o projet/
koordinia calculer --modele projet/projet.json --norme bael -o projet/

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
| `--planche` | — | Planche à traiter : numéro ou mots du titre (`"etage courant"`) |
| `--calque-poteaux` | détecté | Calque des poteaux (nom ou expression régulière) |
| `--sans-contour` | — | Ne pas déduire le contour du plancher des murs |
| `--tous-niveaux` | — | Un modèle par niveau (planches et hauteurs lues dans le dessin) |
| `--affectation` | auto | Planche par niveau : `"RDC=3,ETAGE 2=4"` (numéros de `koordinia planches`) |
| `--hauteurs` | coupes | Hauteurs imposées : `"RDC=3.29"` |
| `--liste-niveaux` | coupes | Niveaux si les coupes n'en donnent pas : `"RDC,ETAGE 1,ETAGE 2,TERRASSE"` |

## Comment les plans sont lus

- **Planches** : les cadres sont détectés (les cadres généraux qui regroupent plusieurs
  planches sont ignorés). Le titre de chaque planche est lu (« VUE EN PLAN ÉTAGE COURANT… »).
  Si le dessin contient plusieurs plans, il faut choisir la planche avec `--planche`.
- **DWG/DXF** : les poteaux sont cherchés sur un calque dont le nom contient
  `POT`, `POTEAU`, `COLUMN`… À défaut, le programme prend les petits rectangles
  hachurés (15 à 120 cm) du calque où ils sont majoritaires (par exemple `COTATI0N`
  chez certains architectes), puis tous les petits rectangles. Les blocs sont explosés.
- **Contour du plancher** : il est déduit des murs, menuiseries et garde-corps. Les axes
  et lignes en tirets, les cotations et le mobilier sont ignorés. Une zone fait partie
  du plancher si elle est fermée de murs dans les 4 directions, ou si elle reste fermée
  une fois les ouvertures de moins de 3 m rebouchées. Les décrochements du bâtiment
  (cours, retraits) restent à l'extérieur.
- **Repères d'axes** : les étiquettes des bulles d'axes de l'architecte (A, C', 11'…)
  sont reprises sur les plans d'exécution.
- **PDF** : seuls les PDF **vectoriels** sont exploitables (exports AutoCAD/Revit/ArchiCAD).
  Les poteaux sont généralement les rectangles remplis. L'échelle est lue dans le
  cartouche (« Ech : 1/100 ») ou imposée par `--echelle`. Les **PDF scannés sont refusés**.
- Les poteaux alignés forment les files. Les poutres relient deux poteaux consécutifs
  d'une file, à condition de rester dans le plancher, avec une hauteur prédimensionnée à L/12.
- **Descente de charges** : le plancher est découpé en cellules de 10 cm.
  - Plancher à corps creux : chaque cellule va à la poutre la plus proche dans le sens
    où la portée des poutrelles est la plus courte.
  - Dalle pleine : chaque cellule va à la poutre la plus proche, ce qui reproduit les
    triangles et trapèzes à 45°.
  - Porte-à-faux sans poutre en vis-à-vis : la cellule va au poteau le plus proche,
    avec un avertissement.

## Modélisation multi-niveaux (`--tous-niveaux`)

1. **Niveaux et hauteurs** : lus sur les coupes et façades. Les étiquettes « RDJ, RDC,
   Étage 1… Terrasse » alignées verticalement sont prises en compte. Quand plusieurs
   coupes ou façades sont cotées, le programme retient la médiane des écarts et signale
   les divergences. Une « Toiture » à moins de 2,5 m au-dessus de la terrasse est un
   acrotère ou un édicule, pas un niveau.
2. **Planche de chaque niveau** : choisie d'après son titre. « ÉTAGE COURANT 1 ET 3 »
   couvre tous les étages courants. Quand plusieurs planches se disputent un niveau
   (par exemple « ensemble RDC » avec les clôtures et « aménagement RDC »), le
   programme retient celle dont les poteaux se superposent le mieux aux étages voisins.
3. **Calage** : toutes les planches sont ramenées dans le repère de l'étage le plus haut,
   par superposition des poteaux. Les repères d'axes peuvent changer d'un niveau à l'autre.
4. **Plancher haut de chaque étage** : il est porté par les poteaux de l'étage, et son
   contour est celui du plan de l'étage supérieur (balcons compris). Les zones d'un étage
   non couvertes par l'étage du dessus (cour, rampe) sont signalées.
5. **Continuité verticale** : un poteau superposé garde le même repère P… à tous les
   niveaux. Un poteau qui ne descend pas est traité ainsi :
   - s'il est **sur un mur** de l'étage inférieur, sa charge est transmise au mur
     (voile et semelle filante à vérifier) ;
   - s'il est **sur une poutre**, il devient une charge ponctuelle et la poutre est
     signalée comme **poutre de transfert** ;
   - **sinon**, sa charge est reportée sur le poteau le plus proche, avec l'alerte
     « structure à revoir ».
6. **Descente de charges** : du haut vers le bas, en gardant la charge d'exploitation de
   chaque plancher séparément. La dégression est ainsi exacte, même avec des transferts.
   Les tests vérifient l'équilibre global (tout ce qui est appliqué arrive aux fondations
   ou aux murs).

## Locaux, usages, trémies et balcons

Les étiquettes de pièces du plan (« Bureau 40,00 m² », « Balcon », « ASC. », « Local
technique », « Bâche à eau »…) sont lues et classées grâce au **catalogue d'usages**
`koordinia/data/usages.json`, établi d'après la NF P06-001. Ce catalogue est modifiable,
et chaque projet peut le compléter dans `koordinia.json` (clé `usages.regles`).

| Type | Exemples | Traitement |
|---|---|---|
| Trémie | ascenseur, gaine, vide, patio | retirée du plancher (la croix du symbole est ignorée) |
| Escalier | escalier | G = 7 kN/m² en projection (paillasse + marches), Q = 2,5 |
| Balcon | balcon, loggia | dalle pleine, Q = 3,5, **calcul en console** (porte-à-faux, h ≥ L/10, chapeaux) |
| Extérieur | terrasse, espace vert | ajouté au plancher s'il surplombe l'étage inférieur ; terre comptée pour les jardins |
| Local | bureaux 2,5 · logement 1,5 · stockage / technique 5 · commerce 5 · bâche à eau 10… | charge du local |

- **Délimitation** : remplissage depuis l'étiquette jusqu'aux murs, portes refermées. La
  surface obtenue est comparée à la surface écrite. Les locaux découpés (marches,
  garde-corps) ou ouverts sont approchés par leur surface écrite, et signalés.
- **Charges** : chaque cellule du plancher porte la charge de son local. La descente de
  charges, la dégression et l'équilibre en tiennent compte. Le permanent des locaux
  sans usage particulier reste celui de l'étage.
- **Sorties** : section « Locaux, usages et trémies » et tableau des balcons en console
  dans la note de calcul ; contours des locaux à charge particulière et des trémies sur
  les plans de coffrage.
- Option `--sans-locaux` : désactive la lecture des locaux (charges uniformes).

## Poutres de transfert automatiques

Pour un poteau qui ne descend pas et qui ne repose ni sur une poutre ni sur un mur, le
programme cherche les **deux appuis les plus proches de part et d'autre**, en X et en Y,
au niveau inférieur. Ces appuis peuvent être un poteau aligné, un mur perpendiculaire ou
une **poutre existante** (poutre secondaire). Il crée une poutre de transfert de portée
au plus 12 m (`transfer_max_span`).

- Les poteaux d'une même poutre sont regroupés. La poutre est calculée en isostatique
  (charges ponctuelles et poids propre), puis agrandie si nécessaire.
- Ses réactions descendent dans les poteaux, les murs ou les poutres d'appui ; une
  poutre d'appui reçoit une charge ponctuelle et est recalculée.
- Faute d'appui, l'alerte « ajouter un poteau ou un voile » est émise.

## Escaliers

Chaque escalier détecté sur un plan est calculé avec la hauteur d'étage :
- **géométrie** : nombre de marches (h ≈ 17 cm), giron par Blondel (2h + g ≈ 63 cm),
  une ou deux volées selon la largeur de la cage, contrôle d'encombrement et
  d'emmarchement ;
- **paillasse et palier** sur poutres palières : épaisseur ≥ L/30, charges réelles,
  Mt = 0,85·M0 et Ma = 0,30·M0 ;
- **ferraillage** : aciers inférieurs, chapeaux, répartition, et charge transmise aux
  poutres palières ;
- **contrôle** du forfait utilisé dans la descente de charges ;
- **sorties** : coupe ferraillée dans les plans de ferraillage.

## Rapport géotechnique

```bash
koordinia geotech rapport_sol.pdf -o Projets/Immeuble_X     # → geotech.json (« valide » : false)
# contrôler / corriger geotech.json, passer « valide » à true, puis dans koordinia.json :
#   "sol": { "geotech": "geotech.json" }
koordinia calculer --config Projets/Immeuble_X/koordinia.json
koordinia geotech --vierge -o Projets/Immeuble_X              # rapport scanné : saisie manuelle
```

- **Données lues** : contrainte admissible ELS et contrainte ELU (bars, kPa, MPa, kg/cm²
  et t/m², convertis), profondeur d'ancrage, type de fondation recommandé, nappe,
  tassement, classe de sol sismique, charge admissible et diamètre des pieux.
- **Traçabilité** : chaque valeur est accompagnée de la phrase du rapport (avec sa page)
  d'où elle vient. Tant que `valide` est à false, la note de calcul l'indique en rouge.
- **Fondations selon le rapport** :
  - semelles isolées avec la profondeur d'ancrage et le poids des terres ;
  - **radier** : contrainte moyenne, épaisseur (portée/20 et poinçonnement), aciers ;
  - **pieux** : charges en tête et nombre de pieux par appui.
- **Alertes** : nappe au-dessus du fond de fouille, semelles filantes recommandées.
- **Priorité de la contrainte du sol** : `--sol` (ou `sol.sol` dans la configuration),
  puis le rapport, puis 0,20 MPa.

## Hypothèses et limites actuelles

- Bâtiment à ossature poteaux-poutres. Sans `--tous-niveaux`, les étages sont supposés
  identiques (un plan d'étage courant + nombre de niveaux).
- Poteaux en compression centrée, lf = 0,7·l0. Leur section est augmentée automatiquement si elle est insuffisante.
- Poutres : moments par **méthode forfaitaire simplifiée**. Un avertissement apparaît si ses
  conditions ne sont pas remplies (rapport de portées, Q > 2G).
- Les sections de poteaux sont reprises telles que dessinées, **enduits compris**
  (23×43 pour un 20×40 enduit, par exemple). À corriger dans `modele.json` si besoin.
- Semelles isolées homothétiques au poteau, allongement limité à 1,5. Le chevauchement
  des semelles et leur surface totale sont contrôlés (semelles filantes ou radier).
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
