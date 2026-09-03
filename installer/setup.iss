; Inno Setup — NeuroPipeline / NeuroBIDS (Windows)
; Requires a prior PyInstaller onedir build:
;   pyinstaller installer\neuro_pipeline.spec --noconfirm --clean
; Expected tree: dist\NeuroPipeline\NeuroPipeline.exe (+ bundled dcm2niix.exe when present)
;
; Output: release\NeuroPipeline_DICOM_Converter_Setup.exe

#define MyAppName "NeuroPipeline DICOM Converter"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Alexandre Rees"
#define MyAppURL "https://github.com/AlexandreRees/NeuroBIDS_DICOM_Converter"
#define MyAppExeName "NeuroPipeline.exe"

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
VersionInfoDescription=Neuroimaging DICOM to BIDS converter
VersionInfoProductName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: checkedonce

[Files]
; Full onedir PyInstaller bundle (GUI runtime + bundled dcm2niix when present)
Source: "..\dist\NeuroPipeline\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Runtime configs (editable after install)
Source: "..\configs\*"; DestDir: "{app}\configs"; Flags: ignoreversion recursesubdirs createallsubdirs
; End-user documentation only (no tests, no datasets, no secrets)
Source: "..\docs\user_manual.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\docs\INSTALL.md"; DestDir: "{app}\docs"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\docs\USER_GUIDE.md"; DestDir: "{app}\docs"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\README_WINDOWS.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{group}\User Guide"; Filename: "{app}\docs\USER_GUIDE.md"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
