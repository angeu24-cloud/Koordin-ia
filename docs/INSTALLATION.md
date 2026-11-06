# Installer BatiCalc sur un serveur

Deux façons de faire, selon l'endroit d'où l'équipe travaille :

| | **A. Serveur au bureau** | **B. Serveur sur internet** |
|---|---|---|
| Accès | Ordinateurs et tablettes connectés au réseau (Wi-Fi) du bureau | Partout : bureau, chantier, domicile |
| Matériel | Un PC allumé en permanence (Windows ou Linux) | Un serveur loué (VPS), environ 5 à 10 € par mois |
| Adresse | `http://192.168.1.20:8000` (exemple) | `https://baticalc.mon-bureau.ci` |
| Difficulté | Facile | Moyenne (nom de domaine à configurer) |

On peut commencer par A et passer à B plus tard : les données se transfèrent avec une
sauvegarde (voir la fin du guide).

---

## A. Serveur au bureau

### 1. Choisir la machine

Un PC qui reste allumé pendant les heures de travail. Configuration conseillée :
- 4 Go de mémoire au moins, 8 Go conseillés ;
- 20 Go d'espace libre ;
- branché au réseau par câble, de préférence.

Les calculs se font sur ce PC : les tablettes ne servent qu'à afficher.

### 2. Installer Docker

- **Windows 10/11** : installer *Docker Desktop* (docker.com › Download), redémarrer, puis
  ouvrir Docker Desktop une fois. Dans ses réglages, cocher *Start Docker Desktop when you sign
  in*.
- **Linux (Ubuntu)** : `curl -fsSL https://get.docker.com | sh`

### 3. Récupérer BatiCalc

Télécharger le dépôt depuis GitHub (bouton *Code › Download ZIP*) et le décompresser, par
exemple dans `C:\BatiCalc`. Ou, avec git :

```bash
git clone https://github.com/angeu24-cloud/Koordin-ia.git BatiCalc
```

### 4. Lancer

Ouvrir un terminal (Windows : *PowerShell*) dans le dossier `deploy/bureau` puis :

```bash
docker compose up -d --build
```

La première fois, la construction prend 5 à 10 minutes : LibreDWG, le lecteur de fichiers
DWG, est compilé. Ensuite, BatiCalc redémarre tout seul avec le PC.

### 5. Ouvrir l'application

- Sur le serveur : `http://localhost:8000`.
- Sur les autres postes et les tablettes : `http://<adresse-du-serveur>:8000`.
  L'adresse s'obtient avec `ipconfig` sous Windows (ligne *Adresse IPv4*) ou `ip a` sous Linux.
- **Le premier compte créé est celui de l'administrateur** : créez-le tout de suite.
- **Windows** : à la première connexion d'un autre poste, autoriser Docker dans le pare-feu
  si Windows le demande (réseau *privé*).
- Conseil : dans votre box ou routeur, réservez une adresse IP fixe au serveur (*bail DHCP
  statique*) pour que l'adresse ne change pas.

---

## B. Serveur sur internet (HTTPS)

### 1. Louer un serveur

Un VPS **Ubuntu 24.04** avec 2 processeurs, 4 Go de mémoire et 40 Go de disque. On en trouve
chez OVHcloud, Hetzner, Contabo, DigitalOcean… Pour une équipe en Côte d'Ivoire, choisissez
un centre de données en Europe de l'Ouest (Paris, Francfort) ou en Afrique s'il est proposé.

Vous recevez une **adresse IP** (par exemple `51.75.10.20`) et un accès `root` en SSH.

### 2. Nom de domaine

Chez le fournisseur de votre nom de domaine (ou en louer un, par exemple `mon-bureau.ci`),
créer un enregistrement DNS :

| Type | Nom | Valeur |
|---|---|---|
| A | `baticalc` | `51.75.10.20` (l'IP du serveur) |

Votre adresse sera `https://baticalc.mon-bureau.ci`. La prise en compte peut demander
jusqu'à quelques heures.

### 3. Installer sur le serveur

Se connecter en SSH (`ssh root@51.75.10.20`, ou avec PuTTY sous Windows), puis :

```bash
curl -fsSL https://get.docker.com | sh
git clone https://github.com/angeu24-cloud/Koordin-ia.git /opt/baticalc
cd /opt/baticalc/deploy/internet
cp .env.exemple .env
nano .env        # DOMAINE=baticalc.mon-bureau.ci et un code d'invitation à vous
docker compose up -d --build
```

Le certificat HTTPS est obtenu automatiquement (Let's Encrypt) dès que le nom de domaine
pointe vers le serveur. Les ports 80 et 443 doivent être ouverts : c'est le cas par défaut
chez la plupart des hébergeurs.

### 4. Les comptes de l'équipe

1. Ouvrez `https://baticalc.mon-bureau.ci` et créez **votre compte en premier** : c'est
   l'administrateur, aucun code n'est demandé pour lui.
2. Donnez à chaque collègue l'adresse et le **code d'invitation** du fichier `.env`.
   Chacun crée son compte avec ce code.
3. Dans chaque projet, ajoutez les collègues avec leur rôle (*éditeur* ou *lecteur*), dans
   l'onglet *Équipe*.
4. Quand tout le monde a son compte, vous pouvez changer le code dans `.env`, puis relancer
   avec `docker compose up -d`.

Sans code d'invitation, personne d'autre ne peut créer de compte : un serveur sur internet
ne doit jamais rester ouvert à tous.

---

## Mettre à jour BatiCalc

Dans le dossier `deploy/bureau` ou `deploy/internet` :

```bash
git pull
docker compose up -d --build
```

Les comptes et les projets sont conservés : ils sont dans le volume Docker
`baticalc_donnees`, pas dans l'image.

## Sauvegarder (indispensable)

```bash
../sauvegarde.sh /chemin/vers/sauvegardes
```

Le script crée une archive datée `baticalc_AAAA-MM-JJ_HHMM.tar.gz` (comptes, projets, plans,
résultats) et garde les 30 dernières. Pour une sauvegarde automatique chaque nuit sur
Linux, ajouter cette ligne avec `crontab -e` :

```
30 2 * * *  cd /opt/baticalc/deploy/internet && ../sauvegarde.sh /sauvegardes
```

Copiez régulièrement les archives **hors du serveur** : disque externe, Google Drive, autre
machine.

## Restaurer (ou déménager vers un autre serveur)

```bash
docker compose down
docker run --rm -v baticalc_donnees:/donnees -v /chemin/vers/sauvegardes:/s alpine:3.20 \
    sh -c "rm -rf /donnees/* && tar xzf /s/baticalc_2026-11-06_0230.tar.gz -C /donnees \
           && mv /donnees/copie_sauvegarde.sqlite /donnees/baticalc.sqlite"
docker compose up -d
```

## En cas de problème

| Symptôme | Que faire |
|---|---|
| La page ne s'ouvre pas | `docker compose ps` (le service doit être *running*) puis `docker compose logs --tail 50 baticalc` |
| Les tablettes n'accèdent pas au serveur du bureau | Vérifier qu'elles sont sur le même Wi-Fi, et le pare-feu Windows (port 8000) |
| HTTPS ne fonctionne pas | Vérifier le DNS (`ping baticalc.mon-bureau.ci` doit donner l'IP du serveur), puis `docker compose logs caddy` |
| Un DWG n'est pas lu | `docker compose exec baticalc dwg2dxf --version` doit répondre ; sinon envoyer le fichier pour analyse |
