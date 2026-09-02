; Inno Setup script — NeuroPipeline DICOM Converter
; Build the EXE first (pyinstaller build_windows.spec), then compile this script.
;
; Output: release\NeuroPipeline_DICOM_Converter_Setup.exe

#define MyAppName "NeuroPipeline DICOM Converter"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Alexandre Rees"
#define MyAppURL "https://github.com/AlexandreRees/neuro_pipeline"
#define MyAppExeName "NeuroPipeline_DICOM_Converter.exe"

[Setup]
AppId={{A7C41E2F-9B18-4D55-9F0E-2E6C8A1B4D90}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\NeuroPipeline DICOM Converter
DefaultGroupName=NeuroPipeline DICOM Converter
DisableProgramGroupPage=no
LicenseFile=
OutputDir=..\release
OutputBaseFilename=NeuroPipeline_DICOM_Converter_Setup
SetupIconFile=NeuroPipeline.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
VersionInfoVersion=1.0.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Medical imaging DICOM to NIfTI converter
VersionInfoProductName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: checkedonce

[Files]
; Primary one-file executable produced by PyInstaller
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; Runtime configs (editable after install)
Source: "..\configs\*"; DestDir: "{app}\configs"; Flags: ignoreversion recursesubdirs createallsubdirs
; Documentation
Source: "..\docs\user_manual.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\README_WINDOWS.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
; Optional bundled dcm2niix
Source: "tools\dcm2niix.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\tools\dcm2niix.exe"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\User Manual"; Filename: "{app}\docs\user_manual.md"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
