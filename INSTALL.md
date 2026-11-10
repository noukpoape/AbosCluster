# Installer AbosCluster / Installing AbosCluster

*English version below.*

## Français

L'installation ne nécessite **aucune connexion internet** : chaque installeur contient le logiciel et toutes ses bibliothèques. Téléchargez une fois le fichier correspondant à votre système dans la page [Releases](https://github.com/noukpoape/AbosCluster/releases/latest), puis copiez-le sur n'importe quel ordinateur (clé USB, réseau…).

| Système | Fichier à télécharger |
|---|---|
| Windows 10 ou 11 (64 bits) | `AbosCluster-Windows-Setup.exe` |
| Mac avec puce Apple silicon (M1, M2, M3…) | `AbosCluster-macOS-AppleSilicon.pkg` |
| Mac avec processeur Intel | `AbosCluster-macOS-Intel.pkg` |
| Linux 64 bits (x86_64) | `AbosCluster-Linux-x86_64.run` |

Quel Mac ? Menu Apple  → **À propos de ce Mac** : la ligne « Puce » indique un Mac Apple silicon, la ligne « Processeur » un Mac Intel.

### Windows

**Installer**
1. Double-cliquez sur `AbosCluster-Windows-Setup.exe`.
2. Si SmartScreen affiche « Windows a protégé votre ordinateur », cliquez sur **Informations complémentaires** puis **Exécuter quand même** (le logiciel n'est pas signé par un certificat payant).
3. Suivez l'assistant : langue → mode d'installation (*pour moi uniquement*, sans droits administrateur, ou *pour tous les utilisateurs*) → Bienvenue → Information → Tâches supplémentaires (icône sur le Bureau) → Prêt à installer → Fin (case pour lancer AbosCluster).

**Où sont les fichiers ?** Les fichiers du programme sont dans un dossier masqué. Lancez AbosCluster depuis le menu Démarrer ou l'icône du Bureau.

**Désinstaller** : menu Démarrer → AbosCluster → **Désinstaller AbosCluster**, ou Paramètres → Applications → AbosCluster → Désinstaller.

### macOS (Apple silicon et Intel)

**Installer**
1. Double-cliquez sur le fichier `.pkg`.
2. L'installeur d'Apple s'ouvre : Introduction → Lisez-moi → Type d'installation → Installation → Résumé. Votre mot de passe est demandé à l'étape Installation.

**Si macOS refuse d'ouvrir le paquet (« développeur non identifié »)**
- macOS 15 (Sequoia) ou plus récent : Réglages Système → **Confidentialité et sécurité**, descendez jusqu'au message concernant le paquet AbosCluster et cliquez sur **Ouvrir quand même**.
- macOS 14 ou plus ancien : clic droit (ou Ctrl-clic) sur le `.pkg` → **Ouvrir** → **Ouvrir**.

**Où sont les fichiers ?** Applications → **AbosCluster** contient deux icônes : **AbosCluster** (tous les fichiers sont masqués dans l'application) et **Désinstaller AbosCluster**. Le fichier `.pkg` peut être supprimé après l'installation.

**Désinstaller** : Applications → AbosCluster → double-cliquez sur **Désinstaller AbosCluster**, confirmez, puis saisissez votre mot de passe.

### Linux

Distributions de 2022 ou plus récentes (Ubuntu 22.04+, Debian 12+, Fedora 36+, Linux Mint 21+…), avec un bureau graphique.

**Installer** : dans un terminal, dans le dossier du fichier téléchargé :
```bash
chmod +x AbosCluster-Linux-x86_64.run
./AbosCluster-Linux-x86_64.run
```
Répondez **O** (ou Entrée). Aucun mot de passe administrateur n'est demandé.

**Où sont les fichiers ?** Dans le dossier masqué `~/.local/share/AbosCluster`. Lancez AbosCluster depuis le menu des applications, l'icône du Bureau ou la commande `aboscluster`. (Sous GNOME, la première fois, clic droit sur l'icône du Bureau → **Autoriser le lancement**.)

**Désinstaller** : menu des applications → **Désinstaller AbosCluster**, ou dans un terminal :
```bash
./AbosCluster-Linux-x86_64.run --uninstall
```

### Vos projets

La désinstallation ne supprime **jamais** vos projets ni vos données (fichiers `.json`, `.csv`, graphiques…) ; seules les préférences du logiciel (langue, police, filtres) sont effacées. Pour mettre à jour AbosCluster, lancez l'installeur de la nouvelle version : il remplace l'ancienne.

---

## English

Installation needs **no internet connection**: each installer contains the software and all its libraries. Download the file for your system once from the [Releases](https://github.com/noukpoape/AbosCluster/releases/latest) page, then copy it to any computer (USB drive, network…).

| System | File |
|---|---|
| Windows 10 or 11 (64-bit) | `AbosCluster-Windows-Setup.exe` |
| Mac with Apple silicon (M1, M2, M3…) | `AbosCluster-macOS-AppleSilicon.pkg` |
| Mac with an Intel processor | `AbosCluster-macOS-Intel.pkg` |
| 64-bit Linux (x86_64) | `AbosCluster-Linux-x86_64.run` |

Which Mac? Apple menu  → **About This Mac**: a “Chip” line means Apple silicon, a “Processor” line means Intel.

### Windows

**Install**
1. Double-click `AbosCluster-Windows-Setup.exe`.
2. If SmartScreen shows “Windows protected your PC”, click **More info** then **Run anyway** (the software is not signed with a paid certificate).
3. Follow the wizard: language → install mode (*just for me*, no administrator rights, or *for all users*) → Welcome → Information → Additional tasks (desktop icon) → Ready to install → Finish (box to start AbosCluster).

**Where are the files?** The program files are in a hidden folder. Start AbosCluster from the Start menu or the desktop icon.

**Uninstall**: Start menu → AbosCluster → **Uninstall AbosCluster**, or Settings → Apps → AbosCluster → Uninstall.

### macOS (Apple silicon and Intel)

**Install**
1. Double-click the `.pkg` file.
2. Apple's Installer opens: Introduction → Read Me → Installation Type → Installation → Summary. Your password is requested at the Installation step.

**If macOS refuses to open the package (“unidentified developer”)**
- macOS 15 (Sequoia) or later: System Settings → **Privacy & Security**, scroll down to the message about the AbosCluster package and click **Open Anyway**.
- macOS 14 or earlier: right-click (or Ctrl-click) the `.pkg` → **Open** → **Open**.

**Where are the files?** Applications → **AbosCluster** contains two icons: **AbosCluster** (all files are hidden inside the application) and **Désinstaller AbosCluster** (uninstaller). The `.pkg` file can be deleted after installation.

**Uninstall**: Applications → AbosCluster → double-click **Désinstaller AbosCluster**, confirm, then enter your password.

### Linux

Distributions from 2022 or later (Ubuntu 22.04+, Debian 12+, Fedora 36+, Linux Mint 21+…), with a graphical desktop.

**Install**: in a terminal, in the folder of the downloaded file:
```bash
chmod +x AbosCluster-Linux-x86_64.run
./AbosCluster-Linux-x86_64.run
```
Answer **Y** (or Enter). No administrator password is needed.

**Where are the files?** In the hidden folder `~/.local/share/AbosCluster`. Start AbosCluster from the applications menu, the desktop icon or the `aboscluster` command. (On GNOME, the first time, right-click the desktop icon → **Allow Launching**.)

**Uninstall**: applications menu → **Uninstall AbosCluster**, or in a terminal:
```bash
./AbosCluster-Linux-x86_64.run --uninstall
```

### Your projects

Uninstalling **never** deletes your projects or data (`.json`, `.csv`, plot files…); only the software preferences (language, font, filters) are removed. To update AbosCluster, run the installer of the new version: it replaces the old one.
