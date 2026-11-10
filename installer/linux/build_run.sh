#!/bin/sh
# =============================================================================
#  Construit l'installeur Linux d'AbosCluster, apres PyInstaller.
#  Usage (depuis la racine du depot) :  installer/linux/build_run.sh 1.0.0
#  Resultat : dist/AbosCluster-Linux-x86_64.run (un seul fichier executable)
# =============================================================================
set -eu
VERSION="${1:-1.0.0}"
cd "$(dirname "$0")/../.."
[ -x dist/AbosCluster/AbosCluster ] || { echo "Introuvable : dist/AbosCluster/AbosCluster (lancez d'abord PyInstaller)"; exit 1; }

TRAVAIL="build/run"
rm -rf "$TRAVAIL"
mkdir -p "$TRAVAIL/charge"
cp -a dist/AbosCluster "$TRAVAIL/charge/AbosCluster"
cp installer/icons/AbosCluster.png "$TRAVAIL/charge/aboscluster.png"
tar -czf "$TRAVAIL/charge.tar.gz" -C "$TRAVAIL/charge" AbosCluster aboscluster.png

SORTIE="dist/AbosCluster-Linux-x86_64.run"
sed "s/@VERSION@/$VERSION/g" installer/linux/header.sh > "$SORTIE"
cat "$TRAVAIL/charge.tar.gz" >> "$SORTIE"
chmod 755 "$SORTIE"
echo "Termine : $SORTIE"
