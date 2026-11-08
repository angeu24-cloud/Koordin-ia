# BatiCalc

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
| `reseau_plomberie.dxf` | Appareils, blocs sanitaires, colonnes EF/EU + schéma des colonnes montantes |
| `reseau_electricite.dxf` | Luminaires, prises, interrupteurs, TD par niveau + schéma unifilaire |
| `reseau_climatisation.dxf` | Splits (CV / kW) par local et liaisons |
| `reseaux.json` | Pré-dimensionnement des réseaux (locaux, circuits, colonnes, TGBT, quantités) |
| `devis.xlsx` / `devis.json` | Devis quantitatif et estimatif, tous lots |
| `modele_saf.xlsx` | Modèle de calcul SAF : Graitec Advance Design, SCIA, RFEM… |
| `robot/` (`robot_baticalc.zip`) | Script qui crée, calcule et enregistre le modèle dans Robot |

## Installation

```bash
pip install -e .
```

**Fichiers DWG** : le format DWG est fermé. Le `.dwg` est lu directement si l'un de ces
convertisseurs est installé (sinon, enregistrer le plan en DXF depuis AutoCAD : `ENREGSOUS` → DXF) :

1. **LibreDWG** (libre, testé avec AutoCAD 2018) : outil `dwg2dxf` dans le `PATH`,
   ou chemin donné par la variable `BATICALC_DWG2DXF`. Compilation :
   ```bash
   git clone --depth 1 https://github.com/LibreDWG/libredwg && cd libredwg
   git submodule update --init && sh autogen.sh
   ./configure --disable-bindings --disable-docs --prefix=$HOME/.local && make -j && make install
   ```
2. **ODA File Converter** (gratuit) : <https://www.opendesign.com/guestfiles/oda_file_converter>.

## Logiciel Windows (installateur)

`BatiCalc-Setup-x.y.z.exe` s'installe comme un logiciel classique : un double-clic, sans
droits d'administrateur, avec un raccourci dans le menu Démarrer et sur le bureau. Tout est
inclus (Python, moteur de calcul, LibreDWG pour les DWG), sans connexion internet nécessaire.

- **Téléchargement** : page *Releases* du dépôt GitHub.
  - *BatiCalc — dernière version* : reconstruite automatiquement à chaque modification.
  - *vX.Y.Z* : versions officielles.
- **Utilisation** :
  - BatiCalc s'ouvre dans sa propre fenêtre ;
  - une petite fenêtre de contrôle permet de rouvrir l'application, de la **partager avec
    l'équipe** sur le réseau du bureau, puis de quitter ;
  - les autres postes et les tablettes ouvrent alors l'adresse affichée.
- **Données** : `%LOCALAPPDATA%\BatiCalc\donnees`, à sauvegarder. Le journal est
  `%LOCALAPPDATA%\BatiCalc\baticalc.log`.
- **Ligne de commande** : `baticalc.exe calculer …`, dans le dossier d'installation.
- **Construction** : `.github/workflows/installateur-windows.yml`. La construction se fait sur
  GitHub Actions :
  1. empaquetage PyInstaller (`packaging/baticalc.spec`) ;
  2. auto-contrôle du logiciel ;
  3. installateur Inno Setup (`packaging/baticalc.iss`) ;
  4. essai d'installation silencieuse ;
  5. publication.

  Pour publier une version officielle : `git tag v1.0.0 && git push --tags`.

## Application web (équipe, navigateur, tablette)

```bash
pip install -e .
baticalc serveur --port 8000 --donnees ./donnees_baticalc
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
- **Inscriptions** : le premier compte créé est l'administrateur. Sur un serveur accessible
  par internet, protéger les inscriptions par un code d'invitation
  (`--code-inscription CODE` ou variable `BATICALC_CODE_INSCRIPTION`), ou les fermer
  (`--inscription fermee`).
- **Mise en service pour une équipe** : guide pas à pas dans
  [docs/INSTALLATION.md](docs/INSTALLATION.md) :
  - serveur du bureau : `deploy/bureau` ;
  - serveur sur internet avec HTTPS automatique : `deploy/internet` ;
  - sauvegarde : `deploy/sauvegarde.sh`.

  LibreDWG est inclus dans l'image Docker pour lire les DWG.

## Échanges IFC (Revit, ArchiCAD, Robot, CYPECAD, Graitec…)

- **Export** : chaque calcul produit `resultats/modele.ifc` (IFC4, validé). Il contient :
  - les niveaux avec leurs altitudes ;
  - les poteaux, les poutres (dont les transferts), les planchers et les semelles, avec leur
    géométrie réelle et le matériau béton armé ;
  - les résultats de dimensionnement dans le jeu de propriétés `BatiCalc_Dimensionnement`
    (section, armatures, cadres, Nu, vérification) ;
  - les quantités (`Qto_…BaseQuantities`).
- **Import** : une maquette IFC exportée de Revit, ArchiCAD, Tekla, Robot ou CYPECAD est
  acceptée en entrée (`baticalc calculer maquette.ifc`, ou dépôt dans l'application web).
  Le programme lit les niveaux, les poteaux, les poutres (sections), les dalles (contour),
  les murs porteurs et les locaux (IfcSpace → usages et charges).

## Liens directs avec les logiciels de calcul (Robot, Graitec Advance Design…)

Chaque calcul produit aussi un **modèle analytique filaire**, prêt à être recalculé :
- poteaux et poutres en barres, avec leurs sections béton ;
- poutres recoupées à chaque appui de poutre ou de poteau naissant (raccordement
  automatique jusqu'à 60 cm de décalage) ;
- encastrements en pied ;
- appuis articulés sous les poteaux posés sur des murs ; ceux sans appui trouvé sont signalés
  « provisoires » ;
- cas de charge **PP** (poids propre, calculé par le logiciel), **G** et **Q** (charges de plancher
  réparties par BatiCalc sur chaque poutre, zones et balcons compris) ;
- combinaisons ELU (1,35 G + 1,5 Q) et ELS (G + Q).

- **Graitec Advance Design, SCIA Engineer, Dlubal RFEM / RSTAB, SOFiSTiK** :
  `resultats/modele_saf.xlsx`, au format ouvert **SAF 2.0** (Structural Analysis Format).
  Dans le logiciel : *Importer › SAF*.
- **Autodesk Robot Structural Analysis**, avec un pilotage direct par l'API officielle RobotOM :
  - `resultats/robot/` (ou `robot_baticalc.zip` dans l'application web) contient
    `robot_modele.py`, `robot_modele.json` et `lancer_robot.bat` ;
  - sur un poste Windows où Robot est installé, double-cliquer sur `lancer_robot.bat` (Python 3
    requis ; le script installe `pythonnet`). Le script :
    - ouvre Robot et crée le modèle ;
    - lance le calcul ;
    - enregistre `modele_baticalc.rtd` ;
    - exporte les réactions d'appui dans `robot_reactions.csv` ;
  - puis comparer les réactions de Robot à la descente de charges de BatiCalc :

    ```bash
    baticalc robot-comparer Projets/Immeuble_X/resultats
    ```

    Le tableau donne, poteau par poteau, l'écart entre les deux. Un écart de plus de 15 % est
    signalé : effet de portique, de continuité ou erreur de modèle à examiner.
- **IFC** (ci-dessus) : maquette physique pour Revit, ArchiCAD, Tekla, ou en complément pour
  Robot et Graitec.

## Devis quantitatif et estimatif

```bash
baticalc bpu BORDEREAU_DE_PRIX.xls -o Projets/Immeuble_X     # → bpu.json
# baticalc.json : "devis": {"bpu": "bpu.json", "categorie": "2EME", "dosage": 350, "hourdis": null, "tva": 0.18}
baticalc calculer --config Projets/Immeuble_X/baticalc.json  # → resultats/devis.xlsx
```

- **Bordereau** : formats xls, xlsx et csv. La ligne d'en-tête et les colonnes
  (désignation, unité, P.U HT ou TTC) sont reconnues automatiquement. Chaque prix est
  repéré par son chemin complet « Lot > chapitre > désignation » (les libellés répétés,
  comme « 2ème catégorie », sont ainsi distingués). Testé avec le bordereau officiel du
  Ministère de la Construction de Côte d'Ivoire (2012, 823 articles).
- **Métré** tiré du calcul :
  - fouilles en puits, remblais et évacuation (ancrage pris dans le rapport géotechnique) ;
  - béton de propreté, semelles et amorces ;
  - poteaux, poutres et poutres de transfert ;
  - planchers à corps creux (net des poutres et des balcons), balcons, escaliers ;
  - aciers HA (barres réellement calculées, ratios pour les dalles) ;
  - coffrages par type ; radier ou pieux selon le type de fondation.
- **Rattachement aux prix** : chaque ouvrage est relié à sa ligne du bordereau par des
  règles modifiables (`baticalc/data/ouvrages.json`). Un ouvrage sans prix est signalé
  « à saisir ».
- **Excel** :
  - feuille **DQE** avec de vraies formules (quantité × P.U), sous-totaux par lot, TVA,
    total TTC ;
  - feuille **Métré** avec le détail par élément ;
  - feuille **Prix** avec la ligne exacte du bordereau utilisée.
- **Second œuvre** (à partir des plans d'architecte) :
  - murs lus sur les calques de murs, tronçons alignés fusionnés, classés par épaisseur
    (agglos 20, 15 ou 10 cm) ; façades reconnues, balcons compris ;
  - ouvertures (portes, fenêtres, baies) lues sur les calques de menuiserie, avec leur
    largeur et leur position (intérieure ou en façade) ;
  - quantités par lot :
    - maçonnerie nette des ouvertures ;
    - enduits intérieurs, extérieurs et plafonds ;
    - sols selon l'usage des locaux (grès, antidérapant pour pièces d'eau et balcons,
      chape pour parkings et locaux techniques, dallage au niveau bas) ;
    - plinthes, faïence des pièces d'eau ;
    - étanchéité de terrasse (forme de pente, revêtement, relevés, protection) ;
    - menuiseries aluminium et bois, appuis de fenêtre, peintures.
- **Application web** : onglet *Devis* (import du bordereau, réglages, tableau, téléchargement).

## Réseaux : plomberie, électricité, climatisation

Calculés automatiquement à partir des locaux lus sur les plans d'architecte (désactivable
par `--sans-reseaux`). Paramètres modifiables : `baticalc/data/mep.json`.

- **Appareils sanitaires**, dans cet ordre de priorité :
  1. blocs nommés (WC, lavabo, douche, évier, urinoir) ;
  2. étiquettes des pièces d'eau (« W.C », « Douche », « Toilettes », « Vestiaires »,
     « Cuisine », « SDB »…), avec un équipement déduit du nom et de la surface ;
  3. tracés sur des calques sanitaires.
- **Plomberie (DTU 60.11)** :
  - appareils regroupés en blocs sanitaires, avec une colonne montante par gaine ;
  - débit probable Qp = y·ΣQb, avec y = 0,8/√(n−1) ;
  - diamètres PVC pression pour v ≤ 2 m/s (branches) et v ≤ 1,5 m/s (colonnes) ;
  - chutes Ø100 (avec WC) ou Ø90 ;
  - collecteurs, regards et fosse septique dimensionnée d'après le nombre d'usagers.
- **Électricité (NF C 15-100)** :
  - luminaires n = E·S/(Φ·η) selon l'éclairement de l'usage ;
  - prises, interrupteurs et circuits (éclairage 16 A, prises 20 A, clim 20 A, différentiels 30 mA) ;
  - un tableau divisionnaire par niveau ;
  - câble TGBT → TD choisi pour Iz ≥ 1,25·Ib et ΔU ≤ 3 % ;
  - puissance du TGBT, avec une alerte au-delà de 100 A (poste à étudier avec la CIE).
- **Climatisation** :
  - bilan simplifié en climat tropical (apports surfaciques par usage + vitrages en façade) ;
  - splits muraux de 1 à 5 CV ;
  - alerte VRV / gainable pour les gros plateaux.
- **Sorties** :
  - trois plans DXF, avec les niveaux côte à côte ;
  - une section « Réseaux » dans la note de calcul ;
  - les quantités, intégrées au devis dans les lots Plomberie, Assainissement, Électricité et
    Climatisation, avec les prix du bordereau.

Ce sont des pré-dimensionnements d'avant-projet : ils sont à reprendre par le bureau
d'études fluides pour l'exécution.

## Démarrer un nouveau projet

Chaque projet a son dossier et son fichier `baticalc.json`. Ce fichier contient le plan,
la norme, les matériaux, les charges, la contrainte du sol et le choix des planches. Les
calculs sont ainsi reproductibles, archivables, et faciles à relancer après une
modification d'hypothèse.

```bash
baticalc init Projets/Immeuble_X --plan plans_archi.dwg --nom "Immeuble X R+4" --norme bael
#   → Projets/Immeuble_X/baticalc.json   (à compléter : charges, sol…)
#   → Projets/Immeuble_X/plans/plans_archi.dwg

baticalc niveaux  --config Projets/Immeuble_X/baticalc.json   # contrôle niveaux / planches
baticalc detecter --config Projets/Immeuble_X/baticalc.json   # modèle + plans de contrôle
baticalc calculer --config Projets/Immeuble_X/baticalc.json   # → Projets/Immeuble_X/resultats/

# variante : une option en ligne de commande remplace la configuration
baticalc calculer --config Projets/Immeuble_X/baticalc.json --norme ec2 -o Projets/Immeuble_X/variante_ec2
```

Extrait de `baticalc.json` :

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
baticalc planches plans_archi.dwg

# 1. Lire la planche de l'étage courant et proposer le modèle (à contrôler)
baticalc detecter plans_archi.dwg --planche "etage courant" --niveaux 5 --hauteur 3.40 -o projet/

#    → ouvrir projet/controle_modele.dxf dans AutoCAD pour vérifier,
#      corriger si besoin projet/modele.json (sections, poutres…)

# 1 bis. Modéliser TOUS les niveaux (une planche par niveau, hauteurs lues sur les coupes)
baticalc niveaux plans_archi.dwg                       # niveaux, hauteurs et planches retenues
baticalc detecter plans_archi.dwg --tous-niveaux -o projet/
baticalc calculer --modele projet/projet.json --norme bael -o projet/

# 2. Calculer (BAEL ou Eurocode 2)
baticalc calculer --modele projet/modele.json --norme bael --fc 25 --fe 400 --sol 0.2 -o projet/

# En une seule étape, depuis un PDF au 1/100 :
baticalc calculer plan.pdf --echelle 100 --niveaux 4 --norme ec2 -o projet/

# Plan d'exemple pour essayer :
baticalc exemple -o essai/ && baticalc calculer essai/exemple_plan.dxf --niveaux 5 -o essai/res
```

Principales options de `calculer` (`baticalc calculer -h` pour la liste complète) :

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
| `--affectation` | auto | Planche par niveau : `"RDC=3,ETAGE 2=4"` (numéros de `baticalc planches`) |
| `--hauteurs` | coupes | Hauteurs imposées : `"RDC=3.29"` |
| `--liste-niveaux` | coupes | Niveaux si les coupes n'en donnent pas : `"RDC,ETAGE 1,ETAGE 2,TERRASSE"` |

## Ossature proposée et toiture légère (villas, plans sans poteaux)

Quand le plan d'architecte ne dessine pas la structure (cas courant des villas), BatiCalc propose
l'ossature à partir des axes des murs :

```python
from baticalc.ossature import structure_from_walls
bld = structure_from_walls(murs, max_span=4.5, col=(0.20, 0.20), beam=(0.20, 0.30), footprint=toiture)
```

- **Poteaux** : aux angles, aux croisements et aux extrémités des murs, plus des poteaux
  intermédiaires si la portée dépasse `max_span`, alignés si possible sur les files existantes.
  Les murs voisins décalés de quelques centimètres sont ramenés sur le même axe.
- **Chaînages** : sur tous les murs, entre poteaux consécutifs.
- **Toiture légère** (charpente et tôles) : configuration `charges.plancher = "charpente"`,
  `g_plancher` = poids de la couverture (≈ 0,40 kN/m²), `g_terrasse` = 0. La charge est répartie sur
  les chaînages. Le métré compte la charpente, la couverture, les rives, les faîtages et le faux
  plafond, sans dalle ni étanchéité.
- **Longrines** : `charges.longrines` = poids de la maçonnerie du rez-de-chaussée (kN/m). Les
  longrines (20×35 par défaut) sont dimensionnées sous tous les murs, et leurs réactions sont
  ajoutées aux semelles.

## Plusieurs fichiers de plans

Quand l'architecte livre un fichier par niveau, ainsi que les coupes et les façades :

- **Application web** : déposez ou sélectionnez tous les fichiers d'un coup dans l'onglet *Plan &
  niveaux*. Vous pouvez ensuite en ajouter ou en retirer.
- **Ligne de commande** : `baticalc calculer rdc.pdf etage1.pdf coupe.pdf --tous-niveaux`.
- **Configuration** : `"plan": ["plans/rdc.dwg", "plans/etage.dwg"]`.

Les fichiers sont assemblés côte à côte comme les planches d'un même dessin. Chacun garde son
échelle. Un fichier sans cadre titré reçoit un cadre, avec un titre tiré de son nom (« rdc.pdf »
devient « PLAN RDC »). L'affectation des planches aux niveaux fonctionne ensuite comme pour un DWG
multi-planches. Une maquette IFC se dépose seule.

## Plans scannés (PDF image, PNG, JPG, TIFF)

Un plan d'architecte scanné ou photographié bien à plat se lit comme un DWG :
`baticalc detecter plan_scan.pdf` (ou dépôt dans l'application web). Il faut l'option
`pip install -e .[scan]`, déjà incluse dans le logiciel Windows et l'image Docker.

- **Échelle** : lue sur les **chaînes de cotes**. Deux cotes voisines d'une même chaîne
  (v1, v2 en cm) sont distantes de (v1 + v2)/2 × échelle ; on retient la valeur la plus
  fréquente. À défaut, la donner en pixels par mètre (`--echelle-px-m`, ou `lecture.echelle_px_m`).
- **Murs** : traits doubles parallèles (7 à 40 cm) ou traits épais. Sont écartés les lignes de
  cote (un nombre à leur extrémité), les lettres, les hachures et escaliers en rouge. Les
  fenêtres bleues comptent comme murs.
- **Poteaux** : taches noircies de 15 à 60 cm, même traversées par les murs.
- **Textes** : OCR hors ligne (RapidOCR), sur l'image et sur l'image tournée (cotes
  verticales), à deux agrandissements. Les noms de pièces sont corrigés (« CUISNE » →
  « CUISINE ») et les noms sur deux lignes fusionnés.
- **Pièces** : délimitées depuis leur nom, portes refermées jusqu'à 1,25 m, sans déborder de
  l'emprise du bâtiment. Une surface plausible est imposée aux pièces sans surface écrite. Les
  petites pièces fermées sans nom lisible (1,5 à 6,5 m²) sont proposées comme « salle d'eau à
  confirmer », et la plomberie les équipe.
- **Limites** : la qualité dépend du scan (300 dpi conseillés, plan droit). Les poteaux sont
  rarement dessinés sur un plan d'architecte : pour le calcul de structure, un DWG reste
  préférable. Contrôler toujours `controle_modele.dxf` et les avertissements.

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
`baticalc/data/usages.json`, établi d'après la NF P06-001. Ce catalogue est modifiable,
et chaque projet peut le compléter dans `baticalc.json` (clé `usages.regles`).

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
baticalc geotech rapport_sol.pdf -o Projets/Immeuble_X     # → geotech.json (« valide » : false)
# contrôler / corriger geotech.json, passer « valide » à true, puis dans baticalc.json :
#   "sol": { "geotech": "geotech.json" }
baticalc calculer --config Projets/Immeuble_X/baticalc.json
baticalc geotech --vierge -o Projets/Immeuble_X              # rapport scanné : saisie manuelle
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
