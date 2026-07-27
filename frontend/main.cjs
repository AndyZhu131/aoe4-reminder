const { app, BrowserWindow, globalShortcut, ipcMain, screen } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const appRoot = path.resolve(__dirname, "..");
const catalogPath = path.join(appRoot, "data", "technologies.json");
const runtimeStatePath = path.join(appRoot, "runtime", "overlay-state.json");
const exampleStatePath = path.join(appRoot, "runtime", "overlay-state.example.json");
const villagerIconPath = path.join(appRoot, "templates", "queue", "villager.png");
const railSize = { width: 248, height: 120 };

let overlayWindow;
let latestState;
let flashingEnabled = true;
let calibrationProcess;

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function defaultState() {
  return {
    version: 1,
    civilization: "sis",
    age: "unknown",
    villagerProductionActive: null,
    researchedTechnologies: [],
    inProgressTechnologies: [],
  };
}

function readState() {
  for (const candidate of [runtimeStatePath, exampleStatePath]) {
    try {
      return readJson(candidate);
    } catch {
      // A writer may be between atomic replacements; retain the latest state.
    }
  }
  return latestState || defaultState();
}

function readCatalog() {
  const catalog = readJson(catalogPath);
  return catalog.technologies.map((technology) => ({
    ...technology,
    iconUrl: pathToFileURL(
      path.join(appRoot, catalog.templatesRoot, technology.templates[0]),
    ).href,
  }));
}

function savedPosition() {
  try {
    return readJson(path.join(app.getPath("userData"), "overlay-position.json"));
  } catch {
    return null;
  }
}

function readSettings() {
  try {
    const settings = readJson(path.join(app.getPath("userData"), "overlay-settings.json"));
    return { flashingEnabled: settings.flashingEnabled !== false };
  } catch {
    return { flashingEnabled: true };
  }
}

function persistSettings() {
  fs.writeFileSync(
    path.join(app.getPath("userData"), "overlay-settings.json"),
    JSON.stringify({ flashingEnabled }, null, 2),
  );
}

function defaultPosition(height = railSize.height) {
  const workArea = screen.getPrimaryDisplay().workArea;
  return {
    x: workArea.x + workArea.width - railSize.width - 28,
    y: workArea.y + Math.max(72, Math.round((workArea.height - height) / 2)),
  };
}

function persistPosition() {
  if (!overlayWindow) return;
  const [x, y] = overlayWindow.getPosition();
  fs.writeFileSync(
    path.join(app.getPath("userData"), "overlay-position.json"),
    JSON.stringify({ x, y }, null, 2),
  );
}

function sendState() {
  latestState = readState();
  overlayWindow?.webContents.send("overlay:state", latestState);
}

function resizeOverlay(requestedHeight) {
  if (!overlayWindow || overlayWindow.isDestroyed()) return;
  const display = screen.getDisplayMatching(overlayWindow.getBounds());
  const maxHeight = Math.max(96, display.workArea.height - 16);
  const height = Math.max(42, Math.min(Math.round(requestedHeight), maxHeight));
  overlayWindow.setSize(railSize.width, height);
}

function toggleOverlayVisibility() {
  if (overlayWindow.isVisible()) {
    overlayWindow.hide();
  } else {
    overlayWindow.showInactive();
  }
}

function launchCalibration() {
  if (calibrationProcess) {
    return Promise.resolve({ started: false, message: "Calibration is already running." });
  }

  const python = process.platform === "win32" ? "python.exe" : "python3";
  const child = spawn(python, ["scripts/aoe4_assistant.py", "calibrate"], {
    cwd: appRoot,
    detached: true,
    stdio: "ignore",
    windowsHide: false,
  });
  calibrationProcess = child;

  child.once("exit", () => {
    calibrationProcess = undefined;
  });

  return new Promise((resolve) => {
    child.once("spawn", () => {
      child.unref();
      overlayWindow?.hide();
      resolve({ started: true });
    });
    child.once("error", (error) => {
      calibrationProcess = undefined;
      resolve({ started: false, message: error.message });
    });
  });
}

function createWindow() {
  const position = savedPosition() || defaultPosition();
  overlayWindow = new BrowserWindow({
    ...railSize,
    ...position,
    transparent: true,
    frame: false,
    resizable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    focusable: true,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  overlayWindow.setAlwaysOnTop(true, "screen-saver");
  overlayWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  overlayWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
  overlayWindow.on("move", persistPosition);
}

app.whenReady().then(() => {
  latestState = readState();
  flashingEnabled = readSettings().flashingEnabled;
  ipcMain.handle("overlay:bootstrap", () => ({
    state: latestState,
    technologies: readCatalog(),
    villagerIconUrl: pathToFileURL(villagerIconPath).href,
    flashingEnabled,
  }));
  ipcMain.handle("overlay:hide", () => overlayWindow?.hide());
  ipcMain.handle("overlay:close", () => app.quit());
  ipcMain.handle("overlay:set-flashing", (_event, enabled) => {
    flashingEnabled = Boolean(enabled);
    persistSettings();
    overlayWindow?.webContents.send("overlay:flashing", flashingEnabled);
    return flashingEnabled;
  });
  ipcMain.handle("overlay:reset-position", () => {
    if (!overlayWindow) return;
    const [, height] = overlayWindow.getSize();
    const position = defaultPosition(height);
    overlayWindow.setPosition(position.x, position.y);
    persistPosition();
  });
  ipcMain.handle("overlay:calibrate", launchCalibration);
  ipcMain.on("overlay:resize", (_event, height) => resizeOverlay(height));
  createWindow();
  fs.watchFile(runtimeStatePath, { interval: 500 }, sendState);
  globalShortcut.register("CommandOrControl+Alt+O", toggleOverlayVisibility);
});

app.on("will-quit", () => {
  fs.unwatchFile(runtimeStatePath);
  globalShortcut.unregisterAll();
});
