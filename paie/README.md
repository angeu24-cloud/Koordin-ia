# Koordin Paie

Gestion des **contrats de travail** et de la **paie** pour une entreprise en **Côte d'Ivoire**.
Application web (ordinateur, tablette, téléphone), indépendante de BatiCalc.

> ⚠️ Les taux et plafonds (CNPS, CMU, ITS, impôt patronal, FDFP, SMIG) sont livrés dans
> `koordinpaie/bareme_ci.json` et **modifiables dans Paramètres > Barème**. Vérifiez-les auprès de
> la CNPS et de la DGI avant la première paie, puis à chaque loi de finances.

## Fonctions

| Domaine | Ce que fait l'application |
|---|---|
| **Salariés** | Fiche complète : identité, n° CNPS, situation familiale (parts fiscales), personnes CMU, expatrié, mode de paiement |
| **Contrats** | CDI, CDD, journalier ; rémunération mensuelle, journalière ou horaire ; sursalaire, transport, primes fixes ; période d'essai |
| **Avenants** | Augmentation, changement de poste ou de catégorie, renouvellement de CDD — pris en compte à leur date d'effet |
| **Fin de contrat** | Date de sortie et motif ; prorata du dernier mois ; indemnité de fin de CDD (3 %) automatique |
| **Alertes** | CDD qui se termine sous 30 jours ou échu, CDD de plus de 2 ans, fin d'essai, salaire sous le SMIG, n° CNPS manquant |
| **Paie mensuelle** | Un bulletin par contrat en cours ; saisie des heures sup., absences, primes du mois, acomptes, retenues ; recalcul immédiat |
| **Clôture** | Bulletins figés (les modifications ultérieures des fiches ne les changent plus) ; cumuls annuels ; réouverture par un administrateur |
| **Documents** | Contrat de travail PDF, bulletin de paie PDF (un ou tous), livre de paie Excel + récapitulatif des déclarations CNPS / DGI / FDFP |
| **Simulateur** | Du salaire de base au net à payer et au coût employeur |
| **Comptes** | Administrateur, gestionnaire de paie, lecture seule ; journal des opérations |

## Calcul d'un bulletin

```
salaire de base (au prorata, ou jours × taux journalier, ou heures × taux horaire)
+ prime d'ancienneté (2 % à 2 ans, +1 % par an, 25 % au plus)
+ sursalaire, heures supplémentaires (+15 / +50 / +75 / +100 %), primes, transport
− absences non payées
= salaire brut          → brut imposable = brut − transport (30 000 FCFA au plus) − primes non imposables
− CNPS retraite 6,3 % (plafond mensuel), CMU 500 FCFA (+ personnes à charge)
− ITS : barème progressif mensuel (0 / 16 / 21 / 24 / 28 / 32 %) − réduction pour charges de famille
− acomptes et autres retenues
= net à payer
Part patronale : CNPS retraite 7,7 %, prestations familiales 5 %, maternité 0,75 %, accident du travail
(taux de l'entreprise), CMU, impôt sur salaires 2,8 % (12 % expatriés), FDFP 0,4 % + 1,2 %.
```

## Lancer l'application

```bash
cd paie
pip install -e .
koordinpaie serveur --donnees ./donnees_koordinpaie          # http://localhost:8100
koordinpaie serveur --hote 0.0.0.0 --port 8100               # accessible depuis le réseau du bureau
```

Au premier lancement, la page d'accueil crée le compte **administrateur** ; il crée ensuite les comptes
des autres utilisateurs (Paramètres > Utilisateurs). Il n'y a pas d'inscription libre : les données de
paie sont confidentielles. Sur un serveur accessible depuis internet, placez l'application derrière HTTPS.

Toutes les données sont dans le dossier `--donnees` (`koordinpaie.sqlite`) : sauvegardez-le régulièrement.

Calcul rapide en ligne de commande :

```bash
koordinpaie calcul 250000 --transport 30000 --marie --enfants 2 --embauche 2019-03-01
```

## Tests

```bash
cd paie
pip install -e .[dev]
pytest
```
