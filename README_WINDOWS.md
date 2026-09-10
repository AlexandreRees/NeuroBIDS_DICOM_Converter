# NeuroPipeline DICOM Converter — Windows (Classic / Main)

Medical imaging DICOM → NIfTI desktop application for Windows.

**Product line:** Classic / Main
**Not:** Copilot development branch / `neurobids-copilot-v1.0.0`
**Copilot:** not included · **Ollama:** not required · **Version:** 1.0.0

## Requirements

- Windows 10/11
- ~200 MB free disk space for installation

**Not required for end users (PI):**

- Python
- Git
- PyInstaller
- Ollama / any LLM
- A separate `dcm2niix` install (`dcm2niix.exe` is bundled by the installer)

## Installation

1. Download `NeuroPipeline_DICOM_Converter_Setup.exe` (from GitHub Actions artifact `NeuroPipeline_DICOM_Converter_Setup`)
2. Double-click the installer
3. Follow the wizard
4. Launch from the Desktop icon or Start Menu

## Quick use

1. Open **Convert**
2. Select DICOM folder
3. Select output folder
4. Click **START CONVERSION**
5. Open the HTML report

Navigation: **Convert · Queue · Settings · Logs**

## Uninstall

Use **Apps & features** (Windows Settings) or the Start Menu uninstall entry.

## Support files

- User manual: `docs\user_manual.md` (installed with the app)
- Build / Actions instructions: `installer\BUILD_WINDOWS.md`
- PI packaging checklist: `BUILD_INSTALLER_FOR_PI.md`
