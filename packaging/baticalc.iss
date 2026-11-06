; Installateur Windows de BatiCalc (Inno Setup 6) : iscc packaging\baticalc.iss
; Prérequis : dist\BatiCalc\ produit par « pyinstaller packaging\baticalc.spec ».
#define AppVersion GetEnv("BATICALC_VERSION")
#if AppVersion == ""
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{8F3C2A51-6B7D-4E2A-9C1B-BA71CA1C0B1C}
AppName=BatiCalc
AppVersion={#AppVersion}
AppVerName=BatiCalc {#AppVersion}
AppPublisher=BatiCalc
AppComments=Modélisation, descente de charges et dimensionnement de bâtiments à partir des plans d'architecte
DefaultDirName={autopf}\BatiCalc
DefaultGroupName=BatiCalc
DisableProgramGroupPage=yes
; installation sans droits d'administrateur (dans le profil de l'utilisateur), ou pour tous si choisi
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=BatiCalc-Setup-{#AppVersion}
SetupIconFile=baticalc.ico
UninstallDisplayIcon={app}\BatiCalc.exe
UninstallDisplayName=BatiCalc
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\BatiCalc\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "baticalc.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\BatiCalc"; Filename: "{app}\BatiCalc.exe"; IconFilename: "{app}\baticalc.ico"
Name: "{group}\Désinstaller BatiCalc"; Filename: "{uninstallexe}"
Name: "{autodesktop}\BatiCalc"; Filename: "{app}\BatiCalc.exe"; IconFilename: "{app}\baticalc.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\BatiCalc.exe"; Description: "{cm:LaunchProgram,BatiCalc}"; Flags: nowait postinstall skipifsilent
