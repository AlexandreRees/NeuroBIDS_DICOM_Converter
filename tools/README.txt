Place dcm2niix.exe in this folder before building the Windows package:

  tools\dcm2niix.exe

Copy from your known good binary, e.g.:
  <path-to-dcm2niix>\dcm2niix.exe

The PyInstaller spec embeds the first match among:
  tools\dcm2niix.exe
  .\dcm2niix.exe
