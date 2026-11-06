#!/bin/sh
# Sauvegarde de BatiCalc (comptes, projets, plans, résultats) dans une archive datée.
# Usage : ./sauvegarde.sh [dossier_de_destination]     (à lancer depuis deploy/bureau ou deploy/internet)
# Planification quotidienne (crontab -e) :  30 2 * * *  cd /chemin/deploy/internet && ../sauvegarde.sh /sauvegardes
set -e
DEST="${1:-$PWD/sauvegardes}"
mkdir -p "$DEST"
# copie cohérente de la base pendant que l'application tourne
docker compose exec -T baticalc python -c "import sqlite3; s=sqlite3.connect('/donnees/baticalc.sqlite'); d=sqlite3.connect('/donnees/copie_sauvegarde.sqlite'); s.backup(d); d.close()"
docker run --rm -v baticalc_donnees:/donnees:ro -v "$DEST":/sauvegardes alpine:3.20 \
    tar czf "/sauvegardes/baticalc_$(date +%Y-%m-%d_%H%M).tar.gz" -C /donnees .
# on garde les 30 dernières archives
ls -1t "$DEST"/baticalc_*.tar.gz | tail -n +31 | xargs -r rm --
echo "Sauvegarde terminée dans $DEST"
