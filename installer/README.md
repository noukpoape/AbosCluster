# Construction des installeurs (mainteneur)

Les installeurs sont construits automatiquement par GitHub Actions (`.github/workflows/release.yml`) : rien à installer sur votre ordinateur.

## Publier une nouvelle version

1. Mettez à jour le code et, si besoin, les manuels (`aboscluster/ABOS/manuals/`).
2. Validez et poussez, puis créez et poussez un tag de version :
   ```bash
   git tag v1.0.0
   git push origin v1.0.0
   ```
3. Le workflow `release` (onglet **Actions**, 15 à 30 minutes) construit et teste :
   - `AbosCluster-Windows-Setup.exe` (Windows 10 / 11, 64 bits)
   - `AbosCluster-macOS-AppleSilicon.pkg` (serveur macOS arm64)
   - `AbosCluster-macOS-Intel.pkg` (serveur macOS x86_64)
   - `AbosCluster-Linux-x86_64.run` (serveur Ubuntu 22.04)

   puis les joint à une Release. Les noms de fichiers ne contiennent pas le numéro de version : les liens du README pointent donc toujours vers la dernière version.

**Essai sans publication** : Actions → `release` → **Run workflow**. Les installeurs sont alors dans les *Artifacts* de l'exécution.

Chaque construction vérifie que l'application démarre (lancement pendant 20 s) et que les deux manuels sont inclus ; sous Linux, l'installation et la désinstallation sont aussi testées.

## Construction manuelle

Prérequis communs : Python 3.10+ (avec Tkinter), puis depuis la racine du dépôt :
```bash
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean installer/aboscluster.spec
```

| Système | Commande suivante | Résultat |
|---|---|---|
| Windows (avec [Inno Setup 6](https://jrsoftware.org/isdl.php)) | `"%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" /DAppVersion=1.0.0 installer\windows\AbosCluster.iss` | `dist\AbosCluster-Windows-Setup.exe` |
| macOS (sur un Mac de l'architecture visée) | `installer/macos/build_pkg.sh 1.0.0` | `dist/AbosCluster-macOS-AppleSilicon.pkg` ou `-Intel.pkg` |
| Linux | `installer/linux/build_run.sh 1.0.0` | `dist/AbosCluster-Linux-x86_64.run` |

## Contenu du dossier

| Fichier ou dossier | Rôle |
|---|---|
| `aboscluster.spec` | Recette PyInstaller : programme autonome (Python, bibliothèques, icônes, manuels) |
| `windows/AbosCluster.iss` | Script Inno Setup : assistant, raccourcis, fichiers masqués, désinstalleur |
| `windows/info_fr.txt`, `info_en.txt` | Texte de la page Information de l'assistant Windows |
| `macos/build_pkg.sh` | Construit le `.pkg` (pkgbuild + productbuild) |
| `macos/distribution.xml` | Étapes de l'installeur macOS et architecture visée |
| `macos/resources/` | Pages de l'installeur en français (`fr.lproj`) et en anglais (`en.lproj`), logo |
| `macos/scripts/preinstall` | Retire l'ancienne version avant une mise à jour |
| `macos/uninstaller.applescript` | Source de l'application « Désinstaller AbosCluster » |
| `linux/header.sh` | Installeur / désinstalleur Linux (en tête du fichier `.run`) |
| `linux/build_run.sh` | Assemble le `.run` (script + archive du programme) |
| `icons/` | Icônes `.ico` (Windows), `.icns` (macOS), `.png` (Linux) créées à partir de `aboscluster/ABOS/macOS/AppIcon.appiconset` |

## Signature

Les installeurs ne sont pas signés : Windows SmartScreen et macOS Gatekeeper affichent un avertissement à la première ouverture (voir [INSTALL.md](../INSTALL.md)). Les supprimer nécessite un certificat de signature de code payant (Windows) et un compte Apple Developer avec notarisation (macOS).
