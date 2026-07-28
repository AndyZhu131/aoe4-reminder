const { app, BrowserWindow, globalShortcut, ipcMain, screen } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const appRoot = path.resolve(__dirname, "..");
const catalogPath = path.join(appRoot, "data", "technologies.json");
const runtimeStatePath = path.join(appRoot, "runtime", "overlay-state.json");
const runtimeControlsPath = path.join(appRoot, "runtime", "overlay-controls.json");
const exampleStatePath = path.join(appRoot, "runtime", "overlay-state.example.json");
const villagerIconPath = path.join(appRoot, "templates", "queue", "villager.png");
const railSize = { width: 248, height: 120 };
const startingAvailableTechnologies = ["wheelbarrow"];
const startingLockedTechnologies = [
  "wood_1",
  "food_1",
  "mine_1",
  "survivalTechnique",
  "melee_def_1",
  "melee_atk_1",
  "range_def_1",
  "range_atk_1",
  "militaryAcademy",
  "siege",
];

let overlayWindow;
let latestState;
let flashingEnabled = true;
let remindersPaused = false;
let calibrationProcess;
let monitorProcess;
let developerWindow;
const developerLogLines = [];
const maxDeveloperLogLines = 500;

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function defaultState() {
  return {
    version: 1,
    civilization: "sis",
    age: "age_1",
    villagerProductionActive: null,
    villagerReminder: null,
    researchedTechnologies: [],
    inProgressTechnologies: [],
    detectedTechnologies: [],
    availableTechnologies: startingAvailableTechnologies,
    lockedTechnologies: startingLockedTechnologies,
    remindersPaused: false,
    session: {
      status: "starting",
      estimatedTimer: "00:00",
      timerMismatchCount: 0,
    },
  };
}

function readOverlayControls() {
  try {
    return readJson(runtimeControlsPath);
  } catch {
    return { paused: false };
  }
}

function writeOverlayControls(controls) {
  const temporaryPath = `${runtimeControlsPath}.tmp`;
  fs.writeFileSync(temporaryPath, JSON.stringify(controls, null, 2));
  fs.renameSync(temporaryPath, runtimeControlsPath);
}

function writeRuntimeState(state) {
  const temporaryPath = `${runtimeStatePath}.tmp`;
  fs.writeFileSync(temporaryPath, JSON.stringify(state, null, 2));
  fs.renameSync(temporaryPath, runtimeStatePath);
}

function appendDeveloperLog(source, message) {
  for (const line of String(message).split(/\r?\n/)) {
    if (!line) continue;
    const entry = {
      timestamp: new Date().toLocaleTimeString(),
      source,
      message: line,
    };
    developerLogLines.push(entry);
    if (developerLogLines.length > maxDeveloperLogLines) developerLogLines.shift();
    developerWindow?.webContents.send("developer-console:log", entry);
  }
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
  remindersPaused = readOverlayControls().paused === true;
  latestState = { ...readState(), remindersPaused };
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

function openDeveloperConsole() {
  if (developerWindow && !developerWindow.isDestroyed()) {
    developerWindow.show();
    developerWindow.focus();
    return;
  }

  developerWindow = new BrowserWindow({
    width: 760,
    height: 520,
    minWidth: 520,
    minHeight: 340,
    title: "AoE4 Reminder Developer Console",
    backgroundColor: "#11161a",
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  developerWindow.loadFile(path.join(__dirname, "developer-console.html"));
  developerWindow.on("closed", () => {
    developerWindow = undefined;
  });
}

function launchMonitor() {
  if (monitorProcess) return;

  const python = process.platform === "win32" ? "python.exe" : "python3";
  const child = spawn(python, ["scripts/aoe4_assistant.py", "watch-monitor"], {
    cwd: appRoot,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  monitorProcess = child;
  appendDeveloperLog("monitor", "starting");

  child.stdout.on("data", (data) => {
    process.stdout.write(`[monitor] ${data}`);
    appendDeveloperLog("monitor", data);
  });
  child.stderr.on("data", (data) => {
    process.stderr.write(`[monitor] ${data}`);
    appendDeveloperLog("monitor", data);
  });
  child.once("error", (error) => {
    appendDeveloperLog("monitor", `failed to start: ${error.message}`);
  });
  child.once("exit", (code, signal) => {
    monitorProcess = undefined;
    appendDeveloperLog("monitor", `stopped (code=${code}, signal=${signal})`);
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
  remindersPaused = readOverlayControls().paused === true;
  latestState = { ...latestState, remindersPaused };
  ipcMain.handle("overlay:bootstrap", () => ({
    state: latestState,
    technologies: readCatalog(),
    villagerIconUrl: pathToFileURL(villagerIconPath).href,
    flashingEnabled,
    remindersPaused,
  }));
  ipcMain.handle("overlay:hide", () => overlayWindow?.hide());
  ipcMain.handle("overlay:close", () => app.quit());
  ipcMain.handle("overlay:set-flashing", (_event, enabled) => {
    flashingEnabled = Boolean(enabled);
    persistSettings();
    overlayWindow?.webContents.send("overlay:flashing", flashingEnabled);
    return flashingEnabled;
  });
  ipcMain.handle("overlay:set-reminders-paused", (_event, paused) => {
    remindersPaused = Boolean(paused);
    writeOverlayControls({
      ...readOverlayControls(),
      paused: remindersPaused,
    });
    latestState = { ...latestState, remindersPaused };
    writeRuntimeState(latestState);
    appendDeveloperLog("overlay", `reminders ${remindersPaused ? "paused" : "resumed"}`);
    overlayWindow?.webContents.send("overlay:state", latestState);
    overlayWindow?.webContents.send("overlay:paused", remindersPaused);
    return remindersPaused;
  });
  ipcMain.handle("overlay:reset-reminders", () => {
    remindersPaused = false;
    writeOverlayControls({
      paused: false,
      resetToken: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    });
    latestState = defaultState();
    writeRuntimeState(latestState);
    appendDeveloperLog("overlay", "reminder session reset requested");
    overlayWindow?.webContents.send("overlay:state", latestState);
    overlayWindow?.webContents.send("overlay:paused", remindersPaused);
    return remindersPaused;
  });
  ipcMain.handle("developer-console:open", () => openDeveloperConsole());
  ipcMain.handle("developer-console:bootstrap", () => developerLogLines);
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
  launchMonitor();
  fs.watchFile(runtimeStatePath, { interval: 500 }, sendState);
  globalShortcut.register("CommandOrControl+Alt+O", toggleOverlayVisibility);
});

app.on("will-quit", () => {
  fs.unwatchFile(runtimeStatePath);
  globalShortcut.unregisterAll();
  monitorProcess?.kill();
});
