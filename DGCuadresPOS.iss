#define MyAppName "DGCuadres/POS"
#define MyAppVersion "2.0.0"
#define MyAppPublisher "DGCuadres"
#define MyAppExeName "DG POS v1.exe"

[Setup]
AppId={{80F8FB77-78B2-4C0F-A19B-1B7A8AB920D2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\DGCuadresPOS
DefaultGroupName=DGCuadres
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=DGCuadresPOS-Setup
SetupIconFile=dg.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
ArchitecturesInstallIn64BitMode=x64

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\DGCuadres\DGCuadres POS"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\DGCuadres POS"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Iniciar {#MyAppName}"; Flags: postinstall nowait skipifsilent
