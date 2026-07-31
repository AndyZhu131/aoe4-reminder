const {
  app,
  BrowserWindow,
  globalShortcut,
  ipcMain,
  Menu,
  nativeImage,
  screen,
  Tray,
} = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

app.commandLine.appendSwitch("autoplay-policy", "no-user-gesture-required");
if (process.platform === "win32") app.setAppUserModelId("com.andyzhu.aoe4reminder");

const sourceRoot = path.resolve(__dirname, "..");
const repositoryRoot = path.resolve(sourceRoot, "..");
const staticAssetsRoot = app.isPackaged
  ? path.join(process.resourcesPath, "app-assets")
  : repositoryRoot;
const templateAssetsRoot = app.isPackaged
  ? path.join(staticAssetsRoot, "templates")
  : path.join(sourceRoot, "templates");
const mutableDataRoot = app.isPackaged ? app.getPath("userData") : repositoryRoot;
const catalogPath = path.join(staticAssetsRoot, "data", "technologies.json");
const runtimeRoot = path.join(mutableDataRoot, "runtime");
const runtimeStatePath = path.join(runtimeRoot, "overlay-state.json");
const runtimeControlsPath = path.join(runtimeRoot, "overlay-controls.json");
const exampleStatePath = path.join(staticAssetsRoot, "runtime", "overlay-state.example.json");
const debugEventsPath = path.join(mutableDataRoot, "captures", "debug-events");
const resolutionProfilesPath = path.join(staticAssetsRoot, "data", "resolution-profiles.json");
const userConfigRoot = path.join(mutableDataRoot, "config");
const staticConfigRoot = path.join(staticAssetsRoot, "config");
const calibrationPaths = {
  "1920x1080": path.join(userConfigRoot, "calibration.1920x1080.json"),
  "2560x1440": path.join(userConfigRoot, "calibration.2560x1440.json"),
  "3840x2160": path.join(userConfigRoot, "calibration.3840x2160.json"),
};
const villagerIconPath = path.join(templateAssetsRoot, "queue", "villager.png");
const villagerSoundDirectory = path.join(staticAssetsRoot, "sound", "villager_mc");
const railSize = { width: 720, height: 178 };
const overlayLayout = "horizontal-two-row-calibrated-top";
const resolutionProfiles = readJson(resolutionProfilesPath);
const templateResolutions = new Set(Object.keys(resolutionProfiles));
const startingAvailableTechnologies = ["wheelbarrow"];
const startingLockedTechnologies = [
  "wood_1",
  "food_1",
  "mine_1",
  "survivalTechnique",
  "textiles",
  "melee_def_1",
  "melee_atk_1",
  "range_def_1",
  "range_atk_1",
  "militaryAcademy",
  "siege",
];

let overlayWindow;
let tray;
let latestState;
let remindersPaused = false;
let overlayInteractionLocked = true;
let captureSettings = {
  resolution: "2560x1440",
  monitor: 1,
  villagerSoundEnabled: true,
};
let calibrationProcess;
let monitorProcess;
let developerWindow;
let quitCleanupStarted = false;
const developerLogLines = [];
const maxDeveloperLogLines = 500;
const preferredWindowsPython = "C:\\Python313\\python.exe";

function pythonCommand() {
  if (process.platform !== "win32") return "python3";
  return process.env.AOE4_PYTHON
    || (fs.existsSync(preferredWindowsPython) ? preferredWindowsPython : "python.exe");
}

function backendInvocation(argumentsList) {
  if (app.isPackaged) {
    return {
      command: path.join(process.resourcesPath, "backend", "aoe4-assistant.exe"),
      arguments: argumentsList,
      cwd: staticAssetsRoot,
    };
  }
  return {
    command: pythonCommand(),
    arguments: ["src/backend/app/aoe4_assistant.py", ...argumentsList],
    cwd: repositoryRoot,
  };
}

function packagedTesseractCommand() {
  if (!app.isPackaged) return [];
  return [
    "--tesseract-cmd",
    path.join(process.resourcesPath, "backend", "_internal", "tesseract", "tesseract.exe"),
  ];
}

function ensureUserStorage() {
  fs.mkdirSync(runtimeRoot, { recursive: true });
  fs.mkdirSync(debugEventsPath, { recursive: true });
  fs.mkdirSync(userConfigRoot, { recursive: true });
  for (const resolution of templateResolutions) {
    const fileName = `calibration.${resolution}.json`;
    const source = path.join(staticConfigRoot, fileName);
    const destination = path.join(userConfigRoot, fileName);
    if (!fs.existsSync(destination) && fs.existsSync(source)) {
      fs.copyFileSync(source, destination);
    }
  }
}

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
      resetReady: false,
      actionsPerMinute: 0,
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

function clearDebugEvents() {
  try {
    if (!fs.existsSync(debugEventsPath)) return 0;
    const entries = fs.readdirSync(debugEventsPath, { withFileTypes: true });
    for (const entry of entries) {
      fs.rmSync(path.join(debugEventsPath, entry.name), {
        force: true,
        recursive: entry.isDirectory(),
        maxRetries: 3,
        retryDelay: 100,
      });
    }
    return entries.length;
  } catch (error) {
    appendDeveloperLog("overlay", `debug event cleanup failed: ${error.message}`);
    return null;
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
  const catalogTemplateRoot = String(catalog.templatesRoot || "tech")
    .replace(/\\/g, "/")
    .replace(/^(?:src\/)?templates\//, "");
  return catalog.technologies.map((technology) => ({
    ...technology,
    iconUrl: pathToFileURL(
      path.join(templateAssetsRoot, catalogTemplateRoot, technology.templates[0]),
    ).href,
  }));
}

function readVillagerAlertSounds() {
  try {
    return fs.readdirSync(villagerSoundDirectory)
      .filter((fileName) => /\.(ogg|mp3)$/i.test(fileName))
      .sort()
      .map((fileName) => pathToFileURL(path.join(villagerSoundDirectory, fileName)).href);
  } catch {
    return [];
  }
}

function savedPosition() {
  try {
    const position = readJson(path.join(app.getPath("userData"), "overlay-position.json"));
    return position.layout === overlayLayout && position.monitor === captureSettings.monitor
      ? position
      : null;
  } catch {
    return null;
  }
}

function readSettings() {
  try {
    const settings = readJson(path.join(app.getPath("userData"), "overlay-settings.json"));
    return {
      resolution: templateResolutions.has(settings.resolution) ? settings.resolution : "2560x1440",
      monitor: settings.monitor === 2 ? 2 : 1,
      villagerSoundEnabled: settings.villagerSoundEnabled !== false,
    };
  } catch {
    return { resolution: "2560x1440", monitor: 1, villagerSoundEnabled: true };
  }
}

function persistSettings() {
  fs.writeFileSync(
    path.join(app.getPath("userData"), "overlay-settings.json"),
    JSON.stringify(captureSettings, null, 2),
  );
}

function interactionSettingsPath() {
  return path.join(app.getPath("userData"), "overlay-interaction.json");
}

function readInteractionLock() {
  try {
    return readJson(interactionSettingsPath()).locked !== false;
  } catch {
    return true;
  }
}

function persistInteractionLock() {
  fs.writeFileSync(
    interactionSettingsPath(),
    JSON.stringify({ locked: overlayInteractionLocked }, null, 2),
  );
}

function resolutionMultiplier(resolution = captureSettings.resolution) {
  return resolutionProfiles[resolution]?.multiplier || 1;
}

function scaleCalibrationPixels(value, resolution = captureSettings.resolution) {
  return Math.round(value * resolutionMultiplier(resolution));
}

function calibrationPathForResolution(resolution = captureSettings.resolution) {
  return calibrationPaths[resolution] || calibrationPaths["2560x1440"];
}

function scaledCalibrationRegion(calibration, regionName) {
  if (Array.isArray(calibration.regions?.[regionName])) return calibration.regions[regionName];
  if (!calibration.scaleFrom) return null;
  const source = readJson(path.join(userConfigRoot, calibration.scaleFrom));
  const values = source.regions?.[regionName];
  if (!Array.isArray(values)) return null;
  return values.map((value) => scaleCalibrationPixels(Number(value), calibration.resolution));
}

function selectedDisplay() {
  return screen.getAllDisplays()[captureSettings.monitor - 1] || screen.getPrimaryDisplay();
}

function calibratedAgeTimerRegion() {
  try {
    const calibration = readJson(calibrationPathForResolution());
    const values = scaledCalibrationRegion(calibration, "ageAndTimer");
    if (!Array.isArray(values) || values.length !== 4) return null;
    const [x, y, width, height] = values.map(Number);
    if (![x, y, width, height].every(Number.isFinite) || width <= 0 || height <= 0) {
      return null;
    }
    if (calibration.coordinateSpace === "monitor") {
      const display = selectedDisplay().bounds;
      return { x: x + display.x, y: y + display.y, width, height };
    }
    return { x, y, width, height };
  } catch {
    return null;
  }
}

function defaultPosition(height = railSize.height) {
  const workArea = selectedDisplay().workArea;
  const region = calibratedAgeTimerRegion();
  if (region) {
    const display = screen.getDisplayNearestPoint({ x: region.x, y: region.y }).workArea;
    const desired = { x: region.x + region.width + 20, y: display.y + 1 };
    return {
      x: Math.max(
        display.x + 8,
        Math.min(desired.x, display.x + display.width - railSize.width - 8),
      ),
      y: desired.y,
    };
  }
  return {
    x: workArea.x + Math.max(8, Math.round((workArea.width - railSize.width) / 2)),
    y: workArea.y + Math.max(8, workArea.height - height - 28),
  };
}

function persistPosition() {
  if (!overlayWindow) return;
  const [x, y] = overlayWindow.getPosition();
  fs.writeFileSync(
    path.join(app.getPath("userData"), "overlay-position.json"),
    JSON.stringify({ x, y, layout: overlayLayout, monitor: captureSettings.monitor }, null, 2),
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
  if (!overlayWindow || overlayWindow.isDestroyed()) return;
  if (overlayWindow.isVisible()) {
    overlayWindow.hide();
  } else {
    overlayWindow.showInactive();
  }
}

function refreshTrayMenu() {
  if (!tray) return;
  const locked = overlayInteractionLocked;
  tray.setContextMenu(Menu.buildFromTemplate([
    {
      label: "Show overlay",
      click: () => overlayWindow?.showInactive(),
    },
    {
      label: "Hide overlay",
      click: () => overlayWindow?.hide(),
    },
    {
      label: locked ? "Unlock overlay controls (Ctrl+Alt+L)" : "Lock overlay controls (Ctrl+Alt+L)",
      click: () => setOverlayInteractionLocked(!locked),
    },
    { type: "separator" },
    {
      label: "Quit AoE4 Reminder",
      click: () => app.quit(),
    },
  ]));
}

function setOverlayInteractionLocked(locked, { persist = true } = {}) {
  overlayInteractionLocked = Boolean(locked);
  if (persist) persistInteractionLock();
  if (overlayWindow && !overlayWindow.isDestroyed()) {
    overlayWindow.setIgnoreMouseEvents(overlayInteractionLocked, { forward: true });
    overlayWindow.setFocusable(!overlayInteractionLocked);
    overlayWindow.webContents.send("overlay:interaction-locked", overlayInteractionLocked);
  }
  refreshTrayMenu();
  return overlayInteractionLocked;
}

function createTray() {
  if (tray) return;

  const icon = nativeImage.createFromPath(villagerIconPath).resize({ width: 32, height: 32 });
  tray = new Tray(icon);
  tray.setToolTip("AoE4 Reminder");
  refreshTrayMenu();
  tray.on("click", toggleOverlayVisibility);
}

function launchCalibration() {
  if (calibrationProcess) {
    return Promise.resolve({ started: false, message: "Calibration is already running." });
  }

  const backend = backendInvocation([
    "calibrate",
    "--monitor",
    String(captureSettings.monitor),
    "--output",
    calibrationPathForResolution(),
    "--seed",
    path.join(staticConfigRoot, "calibration.sample.json"),
  ]);
  const child = spawn(
    backend.command,
    backend.arguments,
    {
      cwd: backend.cwd,
      detached: true,
      stdio: "ignore",
      windowsHide: false,
    },
  );
  calibrationProcess = child;

  child.once("exit", () => {
    calibrationProcess = undefined;
    restartMonitor();
    overlayWindow?.showInactive();
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

  const backend = backendInvocation([
    "watch-monitor",
    "--monitor",
    String(captureSettings.monitor),
    "--template-resolution",
    captureSettings.resolution,
    "--config",
    calibrationPathForResolution(),
    "--output",
    runtimeStatePath,
    "--controls",
    runtimeControlsPath,
    "--catalog",
    catalogPath,
    "--template-root",
    path.join(templateAssetsRoot, "tech"),
    "--debug-events",
    "--debug-event-dir",
    debugEventsPath,
    ...packagedTesseractCommand(),
  ]);
  const child = spawn(backend.command, backend.arguments, {
    cwd: backend.cwd,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });
  monitorProcess = child;
  appendDeveloperLog(
    "monitor",
    `starting (monitor=${captureSettings.monitor}, resolution=${captureSettings.resolution})`,
  );

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

function restartMonitor() {
  if (!monitorProcess) {
    launchMonitor();
    return;
  }
  const child = monitorProcess;
  appendDeveloperLog("monitor", "restarting for updated capture settings");
  child.once("exit", () => launchMonitor());
  child.kill();
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
    focusable: !overlayInteractionLocked,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  overlayWindow.setAlwaysOnTop(true, "screen-saver");
  overlayWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  overlayWindow.setIgnoreMouseEvents(overlayInteractionLocked, { forward: true });
  overlayWindow.loadFile(path.join(__dirname, "renderer", "index.html"));
  overlayWindow.on("move", persistPosition);
}

app.whenReady().then(() => {
  ensureUserStorage();
  latestState = readState();
  captureSettings = readSettings();
  overlayInteractionLocked = readInteractionLock();
  remindersPaused = readOverlayControls().paused === true;
  latestState = { ...latestState, remindersPaused };
  ipcMain.handle("overlay:bootstrap", () => ({
    state: latestState,
    technologies: readCatalog(),
    villagerIconUrl: pathToFileURL(villagerIconPath).href,
    villagerAlertSounds: readVillagerAlertSounds(),
    captureSettings,
    remindersPaused,
    interactionLocked: overlayInteractionLocked,
  }));
  ipcMain.handle("overlay:hide", () => overlayWindow?.hide());
  ipcMain.handle("overlay:close", () => app.quit());
  ipcMain.handle("overlay:set-capture-settings", (_event, settings) => {
    const previousMonitor = captureSettings.monitor;
    captureSettings = {
      resolution: templateResolutions.has(settings?.resolution)
        ? settings.resolution
        : captureSettings.resolution,
      monitor: settings?.monitor === 2 ? 2 : 1,
      villagerSoundEnabled: captureSettings.villagerSoundEnabled,
    };
    persistSettings();
    appendDeveloperLog(
      "overlay",
      `capture settings monitor=${captureSettings.monitor} resolution=${captureSettings.resolution}`,
    );
    if (captureSettings.monitor !== previousMonitor && overlayWindow) {
      const position = defaultPosition();
      overlayWindow.setPosition(position.x, position.y);
      persistPosition();
    }
    restartMonitor();
    return captureSettings;
  });
  ipcMain.handle("overlay:set-villager-sound-enabled", (_event, enabled) => {
    captureSettings = {
      ...captureSettings,
      villagerSoundEnabled: Boolean(enabled),
    };
    persistSettings();
    appendDeveloperLog(
      "overlay",
      `villager alert sound ${captureSettings.villagerSoundEnabled ? "enabled" : "disabled"}`,
    );
    return captureSettings.villagerSoundEnabled;
  });
  ipcMain.handle("overlay:set-interaction-locked", (_event, locked) => {
    const nextLocked = setOverlayInteractionLocked(locked);
    appendDeveloperLog("overlay", `overlay controls ${nextLocked ? "locked" : "unlocked"}`);
    return nextLocked;
  });
  ipcMain.handle("overlay:set-reminders-paused", (_event, paused) => {
    remindersPaused = Boolean(paused);
    writeOverlayControls({
      ...readOverlayControls(),
      paused: remindersPaused,
    });
    latestState = { ...latestState, remindersPaused };
    appendDeveloperLog("overlay", `reminders ${remindersPaused ? "paused" : "resumed"}`);
    overlayWindow?.webContents.send("overlay:state", latestState);
    overlayWindow?.webContents.send("overlay:paused", remindersPaused);
    return remindersPaused;
  });
  ipcMain.handle("overlay:reset-reminders", () => {
    const clearedDebugEvents = clearDebugEvents();
    remindersPaused = true;
    writeOverlayControls({
      paused: true,
      resetToken: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    });
    latestState = { ...defaultState(), remindersPaused };
    appendDeveloperLog(
      "overlay",
      `reminder session reset requested and paused; debug events cleared=${clearedDebugEvents ?? "failed"}`,
    );
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
  createTray();
  launchMonitor();
  fs.watchFile(runtimeStatePath, { interval: 500 }, sendState);
  globalShortcut.register("CommandOrControl+Alt+O", toggleOverlayVisibility);
  globalShortcut.register("CommandOrControl+Alt+L", () => {
    const nextLocked = setOverlayInteractionLocked(!overlayInteractionLocked);
    appendDeveloperLog("overlay", `overlay controls ${nextLocked ? "locked" : "unlocked"}`);
  });
});

app.on("before-quit", (event) => {
  if (quitCleanupStarted) return;
  event.preventDefault();
  quitCleanupStarted = true;
  let quitFinished = false;

  const finishQuit = () => {
    if (quitFinished) return;
    quitFinished = true;
    fs.unwatchFile(runtimeStatePath);
    globalShortcut.unregisterAll();
    tray?.destroy();
    tray = undefined;
    clearDebugEvents();
    app.quit();
  };

  if (!monitorProcess) {
    finishQuit();
    return;
  }

  const child = monitorProcess;
  child.once("exit", finishQuit);
  child.kill();
  setTimeout(finishQuit, 800);
});
