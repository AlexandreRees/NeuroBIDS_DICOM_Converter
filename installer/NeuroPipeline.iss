; Inno Setup script for NeuroPipeline_Setup.exe
; Requires a prior `build.bat` run so dist\NeuroPipeline exists.

#define MyAppName "NeuroPipeline DICOM Converter"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "NeuroPipeline"
#define MyAppExeName "NeuroPipeline.exe"

[Setup]
AppId={{8F3C2B1A-9D4E-4F70-A1B2-C3D4E5F60718}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\NeuroPipeline
DefaultGroupName=NeuroPipeline
OutputDir=Output
OutputBaseFilename=NeuroPipeline_Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"

[Files]
Source: "dist\NeuroPipeline\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Optional: ship dcm2niix if present
Source: "tools\dcm2niix.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
