<a href="aboscluster/ABOS/icon.png"><img src="aboscluster/ABOS/icon.png" alt="AbosCluster" width="120"></a>

# AbosCluster

**AbosCluster** is a desktop application (Python / Tkinter) for the clustering of sparse longitudinal data observed at irregular time points, such as weight trajectories after bariatric surgery (ABOS cohort — *A Biological Atlas of Severe Obesity*, CHU de Lille). Without any programming, it performs exploratory analyses and fits, compares and exports several clustering models, with or without covariates.

> **En français :** AbosCluster est un logiciel de clustering de trajectoires longitudinales éparses (mesures à des temps irréguliers propres à chaque patient), appliqué aux trajectoires de poids après chirurgie bariatrique. Il réalise sans programmation les analyses descriptives, l'ajustement et la comparaison de plusieurs modèles de clustering, avec ou sans covariables. L'interface et le manuel d'utilisation sont disponibles en français et en anglais.

## Features

- **Data:** import CSV, text and Excel files (one or several sheets); missing-value codes; type conversion; filters; long-format preparation (identifier, time, response, covariates).
- **Descriptive analysis:** overview tables (Overview stat); trajectory plots, box plots, bar plots and histograms, with interactive zoom, legend and axis bounds; export to CSV, Excel or Word.
- **InfoMergeCluster:** mixture of linear mixed models with penalized spline mean curves, individual random effects, initialization by micro-classes and merges, automatic choice of the number of classes (BIC / ICL), covariate-dependent class weights; optional Min-Max standardization (results returned on the original scale); mean curves at the covariate means of each cluster, with confidence envelopes.
- **FKMS:** functional k-means with covariates and GCV choice of the smoothing parameter.
- **Covariates:** qualitative covariates (including numeric codes declared in *Categorizing variables*) coded as indicators, the most frequent modality being the reference.
- **Comparison of models:** comparison boxes, adjusted Rand index (ARI) and Jaccard index, raw vs covariate-adjusted (regressed) curves.
- **Export data:** mean curves with their confidence envelopes and individual trajectories of a model, with the class of each subject, to CSV.
- **Projects:** saved as JSON, undo / redo, autosave every 5 minutes, interruptible computations, export of all analyses.
- **Help:** the user manual (French or English, following the interface language) is displayed inside the application.

## Installation

### Installers (recommended, no internet needed)

Download the installer for your system from the [Download](#download) section. Each installer contains Python and all libraries: it can be copied to a USB drive and installed on a computer without an internet connection. An uninstaller is included. Step-by-step instructions: [INSTALL.md](INSTALL.md).

### From source (developers)

Python 3.10 or later with Tkinter:

```bash
git clone https://github.com/noukpoape/AbosCluster.git
cd AbosCluster
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements.txt
```

The interface uses `tkmacosx` and was developed on macOS.

## Usage

```bash
python run_aboscluster.py
```

Typical workflow: **New** (project) → **Import data** → **Edit data** → **Plots** → create an analysis box (left bar) and choose its method → **Run** → **Log** (results) → compare models (right bar) → export. The **Help** button opens the user manual.

## Repository layout

```
AbosCluster/
├── aboscluster/
│   ├── AbosCluster.py              application (interface and algorithms)
│   └── ABOS/                       icons
│       └── manuals/                user manuals (FR, EN) shown by the Help button
├── installer/
│   ├── aboscluster.spec            PyInstaller recipe (Windows, macOS, Linux)
│   ├── windows/                    Inno Setup script and information pages
│   ├── macos/                      .pkg build script, installer pages, uninstaller
│   ├── linux/                      self-extracting .run installer
│   ├── icons/                      .ico, .icns, .png
│   └── README.md                   build notes
├── .github/workflows/release.yml   builds and publishes the installers
├── INSTALL.md                      installation guide (FR / EN)
├── requirements.txt
└── run_aboscluster.py
```

## Building the installers

The installers are built by GitHub Actions on Windows, macOS (Apple silicon and Intel) and Linux machines when a version tag is pushed:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Actions → `release` → installers attached to the Release. Manual build: [installer/README.md](installer/README.md).

## Download

| System | Installer |
|---|---|
| Windows 10 / 11 (64-bit) | **[AbosCluster-Windows-Setup.exe](https://github.com/noukpoape/AbosCluster/releases/latest/download/AbosCluster-Windows-Setup.exe)** |
| macOS — Apple silicon (M1, M2, M3…) | **[AbosCluster-macOS-AppleSilicon.pkg](https://github.com/noukpoape/AbosCluster/releases/latest/download/AbosCluster-macOS-AppleSilicon.pkg)** |
| macOS — Intel | **[AbosCluster-macOS-Intel.pkg](https://github.com/noukpoape/AbosCluster/releases/latest/download/AbosCluster-macOS-Intel.pkg)** |
| Linux (64-bit, x86_64) | **[AbosCluster-Linux-x86_64.run](https://github.com/noukpoape/AbosCluster/releases/latest/download/AbosCluster-Linux-x86_64.run)** |

Install: double-click the file (Linux: `chmod +x AbosCluster-Linux-x86_64.run && ./AbosCluster-Linux-x86_64.run`). Uninstalling never deletes your projects or data: on Windows, Settings → Apps; on macOS, *Désinstaller AbosCluster* in Applications → AbosCluster; on Linux, *Uninstall AbosCluster* in the applications menu. Details in [INSTALL.md](INSTALL.md); previous versions on the [Releases](https://github.com/noukpoape/AbosCluster/releases) page.

## Authors

Komlan Noukpoape and Cristian Preda (Inria). Sponsor: CHU de Lille (Lille University Hospital).

## License

To be defined.
