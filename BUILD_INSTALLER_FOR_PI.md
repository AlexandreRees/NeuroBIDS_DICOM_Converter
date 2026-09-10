# Classic / Main Windows installer for PI distribution

This packaging targets GitHub **`main`** (Classic / Main · NO Copilot · NO Ollama).

Reference commit for the Classic app tree: `861b6ae`.

## Important distinctions

| Classic / Main | Copilot line (do not use here) |
|----------------|--------------------------------|
| Branch `main` | `neurobids-copilot-v1` / tag `neurobids-copilot-v1.0.0` |
| Convert · Queue · Settings · Logs | Discover/Map/Audit + Copilot |
| No Ollama | Optional LLM providers |

Numeric app version `1.0.0` on Classic/Main is **not** the Copilot tag.

## What GitHub Actions produces

- Artifact name: `NeuroPipeline_DICOM_Converter_Setup`
- File inside: `NeuroPipeline_DICOM_Converter_Setup.exe`
- No tag / no GitHub Release created by the workflow

## Trigger

1. Merge `chore/classic-windows-gha` into `main`
2. GitHub → **Actions** → **Build Windows Installer (Classic / Main)**
3. **Run workflow** on branch **`main`**
4. Download artifact → extract Setup.exe → install on your Windows → test → send to PI

## Local Windows build

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

## End-user (PI) requirements

None of: Python, PyInstaller, dcm2niix (manual), Ollama.

`tools\dcm2niix.exe` is downloaded during the Windows build when absent (pinned + SHA256-verified) and is **not** versioned in Git.