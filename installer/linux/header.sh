#!/bin/sh
# =============================================================================
#  Installeur Linux d'AbosCluster (hors ligne, sans droits administrateur)
#  Usage :  chmod +x AbosCluster-Linux-x86_64.run && ./AbosCluster-Linux-x86_64.run
#  Options : --yes (sans question)   --uninstall (desinstaller)   --help
#  Installe dans ~/.local/share/AbosCluster (dossier masque), ajoute AbosCluster
#  au menu des applications et sur le Bureau, avec « Désinstaller AbosCluster ».
#  Le logiciel et toutes ses bibliotheques sont inclus a la fin de ce fichier.
# =============================================================================
set -eu

VERSION="@VERSION@"
DONNEES="${XDG_DATA_HOME:-$HOME/.local/share}"
DEST="$DONNEES/AbosCluster"
MENU="$DONNEES/applications"
ICONES="$DONNEES/icons/hicolor/256x256/apps"
BIN="$HOME/.local/bin"

case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in fr*) FR=1 ;; *) FR=0 ;; esac
txt () { if [ "$FR" = 1 ]; then printf '%s\n' "$1"; else printf '%s\n' "$2"; fi; }

OUI=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes) OUI=1 ;;
    --uninstall)
      if [ -x "$DEST/uninstall.sh" ]; then exec "$DEST/uninstall.sh"; fi
      txt "AbosCluster n'est pas installé." "AbosCluster is not installed."; exit 1 ;;
    -h|--help)
      txt "Usage : $0 [--yes] [--uninstall]" "Usage: $0 [--yes] [--uninstall]"; exit 0 ;;
  esac
done

# --- dialogue : terminal, sinon fenetre (zenity), sinon sans question ---------
question () {
  [ "$OUI" = 1 ] && return 0
  if [ -t 0 ]; then
    printf '%s ' "$1"; read -r rep || rep=""
    case "$rep" in ""|o|O|oui|Oui|y|Y|yes|Yes) return 0 ;; *) return 1 ;; esac
  elif command -v zenity >/dev/null 2>&1; then
    zenity --question --title="AbosCluster" --width=420 --text="$1" 2>/dev/null
  else
    return 0
  fi
}
info () {
  printf '%s\n' "$1"
  if [ ! -t 0 ] && command -v zenity >/dev/null 2>&1; then
    zenity --info --title="AbosCluster" --width=420 --text="$1" 2>/dev/null || true
  fi
}

[ "$(uname -m)" = "x86_64" ] || { info "$(txt "Cet installeur est prévu pour Linux 64 bits (x86_64)." "This installer is for 64-bit Linux (x86_64).")"; exit 1; }

question "$(txt "Installer AbosCluster $VERSION (aucune connexion internet nécessaire) ? [O/n]" \
                "Install AbosCluster $VERSION (no internet connection needed)? [Y/n]")" || exit 0

while pgrep -f "$DEST/AbosCluster/AbosCluster" >/dev/null 2>&1; do
  if [ "$OUI" = 1 ]; then txt "AbosCluster est ouvert : fermez-le puis relancez l'installation." "AbosCluster is running: close it and run the installer again."; exit 1; fi
  question "$(txt "AbosCluster est ouvert : fermez-le (après avoir enregistré votre projet), puis validez. [O/n]" \
                  "AbosCluster is running: close it (after saving your project), then confirm. [Y/n]")" || exit 0
done

txt "Installation en cours..." "Installing..."
TMP="$(mktemp -d "${TMPDIR:-/tmp}/aboscluster.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
LIGNE=$(awk '/^__ABOSCLUSTER_ARCHIVE__$/ { print NR + 1; exit 0 }' "$0")
tail -n +"$LIGNE" "$0" | tar -xzf - -C "$TMP"

# --- installation (une version precedente est remplacee) ----------------------
rm -rf "$DEST"
mkdir -p "$DEST" "$MENU" "$ICONES" "$BIN"
mv "$TMP/AbosCluster" "$DEST/AbosCluster"
cp "$TMP/aboscluster.png" "$ICONES/aboscluster.png"
printf '%s\n' "$VERSION" > "$DEST/VERSION"

# lanceur en ligne de commande : aboscluster
rm -f "$BIN/aboscluster"
printf '#!/bin/sh\nexec "%s" "$@"\n' "$DEST/AbosCluster/AbosCluster" > "$BIN/aboscluster"
chmod 755 "$BIN/aboscluster"

# --- desinstalleur --------------------------------------------------------------
cat > "$DEST/uninstall.sh" <<EOF_DESINSTALLEUR
#!/bin/sh
# Désinstaller AbosCluster (les projets et les données ne sont jamais supprimés)
case "\${LC_ALL:-\${LC_MESSAGES:-\${LANG:-}}}" in fr*) FR=1 ;; *) FR=0 ;; esac
txt () { if [ "\$FR" = 1 ]; then printf '%s\n' "\$1"; else printf '%s\n' "\$2"; fi; }
Q="\$(txt "Désinstaller AbosCluster ? Vos projets et vos données ne seront pas supprimés." "Uninstall AbosCluster? Your projects and data will not be deleted.")"
if [ "\${1:-}" != "--yes" ]; then
  if [ -t 0 ]; then
    printf '%s [o/N] ' "\$Q"; read -r rep || rep=""
    case "\$rep" in o|O|oui|Oui|y|Y|yes|Yes) ;; *) exit 0 ;; esac
  elif command -v zenity >/dev/null 2>&1; then
    zenity --question --title="AbosCluster" --width=420 --text="\$Q" 2>/dev/null || exit 0
  fi
fi
while pgrep -f "$DEST/AbosCluster/AbosCluster" >/dev/null 2>&1; do
  F="\$(txt "AbosCluster est ouvert : fermez-le (après avoir enregistré votre projet), puis validez." "AbosCluster is running: close it (after saving your project), then confirm.")"
  if [ -t 0 ]; then printf '%s [Entrée/Enter] ' "\$F"; read -r rep || exit 0
  elif command -v zenity >/dev/null 2>&1; then zenity --question --title="AbosCluster" --width=420 --text="\$F" 2>/dev/null || exit 0
  else exit 1; fi
done
rm -f "$MENU/aboscluster.desktop" "$MENU/aboscluster-uninstall.desktop" "$ICONES/aboscluster.png" "$BIN/aboscluster"
for f in "\$(xdg-user-dir DESKTOP 2>/dev/null || echo "\$HOME/Desktop")/aboscluster.desktop" "\$HOME/Desktop/aboscluster.desktop" "\$HOME/Bureau/aboscluster.desktop"; do
  rm -f "\$f"
done
rm -f "\$HOME/.abos_preferences.json" "\$HOME/.abos_filtres.json" "\$HOME/.abos_parametres_graphiques.json"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$MENU" >/dev/null 2>&1 || true
rm -rf "$DEST"
M="\$(txt "AbosCluster a été désinstallé." "AbosCluster has been uninstalled.")"
printf '%s\n' "\$M"
if [ ! -t 0 ] && command -v zenity >/dev/null 2>&1; then zenity --info --title="AbosCluster" --width=320 --text="\$M" 2>/dev/null || true; fi
EOF_DESINSTALLEUR
chmod 755 "$DEST/uninstall.sh"

# --- menu des applications et Bureau --------------------------------------------
if command -v zenity >/dev/null 2>&1; then TERMINAL=false; else TERMINAL=true; fi
cat > "$MENU/aboscluster.desktop" <<EOF_MENU
[Desktop Entry]
Type=Application
Name=AbosCluster
Comment=Clustering sparse longitudinal trajectories
Comment[fr]=Clustering de trajectoires longitudinales éparses
Exec="$DEST/AbosCluster/AbosCluster"
Path=$HOME
Icon=aboscluster
Terminal=false
Categories=Science;Education;MedicalSoftware;
StartupWMClass=AbosCluster
EOF_MENU
cat > "$MENU/aboscluster-uninstall.desktop" <<EOF_MENU
[Desktop Entry]
Type=Application
Name=Uninstall AbosCluster
Name[fr]=Désinstaller AbosCluster
Exec="$DEST/uninstall.sh"
Icon=aboscluster
Terminal=$TERMINAL
Categories=Science;Education;
EOF_MENU
chmod 755 "$MENU/aboscluster.desktop" "$MENU/aboscluster-uninstall.desktop"

BUREAU="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
[ -n "$BUREAU" ] || BUREAU="$HOME/Desktop"
if [ -d "$BUREAU" ] && [ "$BUREAU" != "$HOME" ]; then
  cp "$MENU/aboscluster.desktop" "$BUREAU/aboscluster.desktop"
  chmod 755 "$BUREAU/aboscluster.desktop"
  gio set "$BUREAU/aboscluster.desktop" metadata::trusted true >/dev/null 2>&1 || true   # GNOME : icône autorisée
fi
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$MENU" >/dev/null 2>&1 || true
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$DONNEES/icons/hicolor" >/dev/null 2>&1 || true

info "$(txt "AbosCluster $VERSION est installé. Lancez-le depuis le menu des applications ou l'icône du Bureau (commande : aboscluster). Pour le désinstaller : « Désinstaller AbosCluster » dans le menu." \
            "AbosCluster $VERSION is installed. Start it from the applications menu or the desktop icon (command: aboscluster). To uninstall: \"Uninstall AbosCluster\" in the menu.")"
exit 0
__ABOSCLUSTER_ARCHIVE__
