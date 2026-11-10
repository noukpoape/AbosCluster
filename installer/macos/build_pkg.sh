#!/bin/bash
# =============================================================================
#  Construit l'installeur macOS d'AbosCluster (.pkg), apres PyInstaller.
#  Usage (depuis la racine du depot, sur un Mac) :
#     installer/macos/build_pkg.sh 1.0.0            # architecture du Mac utilise
#  Resultat :
#     dist/AbosCluster-macOS-AppleSilicon.pkg      (Mac M1, M2, M3...)
#     dist/AbosCluster-macOS-Intel.pkg             (Mac Intel)
#  Le .pkg installe dans /Applications/AbosCluster :
#     AbosCluster.app                 (tous les fichiers sont dans le paquet .app)
#     Désinstaller AbosCluster.app
# =============================================================================
set -euo pipefail

VERSION="${1:-1.0.0}"
cd "$(dirname "$0")/../.."
RACINE="$(pwd)"
MAC="$RACINE/installer/macos"
APP="$RACINE/dist/AbosCluster.app"
IDENTIFIANT="fr.inria.aboscluster"
DESINSTALLEUR="Désinstaller AbosCluster.app"

case "$(uname -m)" in
  arm64)  ARCH="arm64";  VARIANTE="AppleSilicon" ;;
  x86_64) ARCH="x86_64"; VARIANTE="Intel" ;;
  *) echo "Architecture non prise en charge : $(uname -m)"; exit 1 ;;
esac

[ -d "$APP" ] || { echo "Introuvable : $APP (lancez d'abord PyInstaller)"; exit 1; }

TRAVAIL="$RACINE/build/pkg"
rm -rf "$TRAVAIL"
mkdir -p "$TRAVAIL/racine/Applications/AbosCluster" "$TRAVAIL/scripts"
CIBLE="$TRAVAIL/racine/Applications/AbosCluster"

echo "== Application"
ditto "$APP" "$CIBLE/AbosCluster.app"
xattr -cr "$CIBLE/AbosCluster.app"                                 # attributs etendus : genent codesign
codesign --force --deep --sign - "$CIBLE/AbosCluster.app"          # signature ad hoc (Apple silicon)

echo "== Desinstalleur"
osacompile -o "$CIBLE/$DESINSTALLEUR" "$MAC/uninstaller.applescript"
cp "$RACINE/installer/icons/AbosCluster.icns" "$CIBLE/$DESINSTALLEUR/Contents/Resources/applet.icns"
xattr -cr "$CIBLE/$DESINSTALLEUR"
codesign --force --deep --sign - "$CIBLE/$DESINSTALLEUR"

echo "== Paquet composant"
cp "$MAC/scripts/preinstall" "$TRAVAIL/scripts/preinstall"
chmod 755 "$TRAVAIL/scripts/preinstall"
pkgbuild --analyze --root "$TRAVAIL/racine" "$TRAVAIL/composants.plist"
# l'application est toujours installee dans /Applications/AbosCluster (jamais « deplacee »
# vers une autre copie trouvee sur le disque)
python3 - "$TRAVAIL/composants.plist" <<'PY'
import plistlib, sys
chemin = sys.argv[1]
with open(chemin, "rb") as f:
    composants = plistlib.load(f)
for c in composants:
    c["BundleIsRelocatable"] = False
    c["BundleIsVersionChecked"] = False
    c["BundleOverwriteAction"] = "upgrade"
with open(chemin, "wb") as f:
    plistlib.dump(composants, f)
PY
pkgbuild --root "$TRAVAIL/racine" \
         --component-plist "$TRAVAIL/composants.plist" \
         --scripts "$TRAVAIL/scripts" \
         --identifier "$IDENTIFIANT" \
         --version "$VERSION" \
         --install-location / \
         "$TRAVAIL/AbosCluster-composant.pkg"

echo "== Installeur final"
sed -e "s/@VERSION@/$VERSION/g" -e "s/@ARCH@/$ARCH/g" "$MAC/distribution.xml" > "$TRAVAIL/distribution.xml"
mkdir -p "$RACINE/dist"
SORTIE="$RACINE/dist/AbosCluster-macOS-$VARIANTE.pkg"
productbuild --distribution "$TRAVAIL/distribution.xml" \
             --resources "$MAC/resources" \
             --package-path "$TRAVAIL" \
             "$SORTIE"
echo "Termine : $SORTIE"
