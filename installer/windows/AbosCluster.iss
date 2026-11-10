; =============================================================================
;  Installeur Windows d'AbosCluster (Inno Setup 6.3 ou plus recent)
;  - installation 100 % hors ligne (tout est embarque dans le .exe)
;  - pour l'utilisateur courant (sans droits administrateur) ou tous les utilisateurs
;  - fichiers installes masques ; desinstallation complete
;  Compilation (apres PyInstaller) :  iscc /DAppVersion=1.0.0 installer\windows\AbosCluster.iss
;  Resultat : dist\AbosCluster-Windows-Setup.exe
; =============================================================================

#define AppName "AbosCluster"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#define AppPublisher "Inria - Komlan Noukpoape, Cristian Preda"
#define AppExe "AbosCluster.exe"

[Setup]
; Identifiant unique : ne jamais le changer (sert aux mises a jour et a la desinstallation)
AppId={{6E3F2B71-4C8D-4A5E-9B1F-AB05C1A57E10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableWelcomePage=no
WizardStyle=modern
ShowLanguageDialog=auto
UsePreviousLanguage=no
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
SetupIconFile=..\icons\AbosCluster.ico
WizardSmallImageFile=wizard_small.bmp
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
OutputDir=..\..\dist
OutputBaseFilename=AbosCluster-Windows-Setup
Compression=lzma2/max
SolidCompression=yes
CloseApplications=no

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"; InfoBeforeFile: "info_fr.txt"
Name: "english"; MessagesFile: "compiler:Default.isl"; InfoBeforeFile: "info_en.txt"

[CustomMessages]
french.UninstallShortcut=Désinstaller {#AppName}
english.UninstallShortcut=Uninstall {#AppName}
french.AppIsRunning={#AppName} est ouvert. Fermez-le (après avoir enregistré votre projet), puis cliquez sur OK.
english.AppIsRunning={#AppName} is running. Close it (after saving your project), then click OK.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Dirs]
; dossier d'installation masque
Name: "{app}"; Attribs: hidden

[Files]
; tout le contenu produit par PyInstaller (exe, _internal, icones, manuels), masque
Source: "..\..\dist\AbosCluster\*"; DestDir: "{app}"; Attribs: hidden; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{userdocs}"
Name: "{autoprograms}\{#AppName}\{cm:UninstallShortcut}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; WorkingDir: "{userdocs}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; reste du dossier d'installation et preferences de l'utilisateur (les projets ne sont pas touches)
Type: filesandordirs; Name: "{app}"
Type: files; Name: "{%USERPROFILE}\.abos_preferences.json"
Type: files; Name: "{%USERPROFILE}\.abos_filtres.json"
Type: files; Name: "{%USERPROFILE}\.abos_parametres_graphiques.json"

[Code]
{ AbosCluster en cours d'execution ? }
function AppEnCours(): Boolean;
var
  Code: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'),
    '/C tasklist /FI "IMAGENAME eq {#AppExe}" /NH | find /I "{#AppExe}" >NUL',
    '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

{ demande de fermer l'application ; False si l'utilisateur abandonne }
function AttendreFermeture(): Boolean;
begin
  Result := True;
  while AppEnCours() do
    if MsgBox(CustomMessage('AppIsRunning'), mbInformation, MB_OKCANCEL) = IDCANCEL then
    begin
      Result := False;
      Exit;
    end;
end;

{ attribut masque pose (Masque = True) ou retire, sur le dossier et tout son contenu }
procedure Masquer(const Dossier: String; Masque: Boolean);
var
  Code: Integer;
  Option: String;
begin
  if not DirExists(Dossier) then Exit;
  if Masque then Option := '+h' else Option := '-h -s';
  Exec(ExpandConstant('{sys}\attrib.exe'), Option + ' "' + Dossier + '\*" /S /D', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\attrib.exe'), Option + ' "' + Dossier + '"', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;

function InitializeSetup(): Boolean;
begin
  Result := AttendreFermeture();
end;

function InitializeUninstall(): Boolean;
begin
  Result := AttendreFermeture();
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  { mise a jour : fichiers precedents demasques pour pouvoir etre remplaces }
  if CurStep = ssInstall then
    Masquer(ExpandConstant('{app}'), False);
  { fin : tous les fichiers (y compris le desinstalleur) et dossiers masques }
  if CurStep = ssDone then
    Masquer(ExpandConstant('{app}'), True);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    Masquer(ExpandConstant('{app}'), False);
end;
