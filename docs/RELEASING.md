# Windows Release Build

The installer bundles Electron, the Python monitor, OpenCV, and Tesseract OCR.
Players do not need Python, Node.js, or Tesseract installed separately.

## Prerequisites for the release machine

- Windows x64
- Python 3.13 (or set `AOE4_PYTHON` to the Python executable used to build)
- Node.js and the frontend dependencies (`npm.cmd install` in `frontend/`)
- Tesseract OCR at `C:\Program Files\Tesseract-OCR`, or set
  `AOE4_TESSERACT_ROOT` to its installation directory

## Build

From the repository root:

```powershell
Set-Location frontend
npm.cmd run dist
```

The command creates a private `.venv-build` environment, freezes the backend
into `dist/backend/aoe4-assistant/`, then produces the NSIS installer under a
versioned directory such as `release/1.0.0/`. The directory is derived from
`frontend/package.json`.

`scripts/build-backend.ps1` includes the Tesseract executable, its DLLs, and
its language data. The Electron package copies the backend, templates,
calibration defaults, technology catalog, and alert sounds into its resources.

## Installed data

Read-only assets remain alongside the installed application. On first launch,
the app copies calibration defaults into the current user's Electron data
directory. Runtime state, controls, debug captures, and any recalibration are
also written there, so standard Windows users do not need permission to modify
the installation directory.

## Release checklist

1. Run `npm.cmd run dist` from `frontend/`.
2. Install the generated `release/<version>/AoE4-Reminder-Setup-*.exe` on a Windows account that
   does not have Python or Tesseract installed.
3. Open the app, confirm the overlay starts, then run a calibration and a live
   monitor session.
4. Code-sign the installer before broad distribution to reduce Windows
   SmartScreen warnings.
