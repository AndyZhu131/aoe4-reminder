const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("aoeOverlay", {
  bootstrap: () => ipcRenderer.invoke("overlay:bootstrap"),
  hide: () => ipcRenderer.invoke("overlay:hide"),
  close: () => ipcRenderer.invoke("overlay:close"),
  setCaptureSettings: (settings) => ipcRenderer.invoke("overlay:set-capture-settings", settings),
  setVillagerSoundEnabled: (enabled) => ipcRenderer.invoke("overlay:set-villager-sound-enabled", enabled),
  setInteractionLocked: (locked) => ipcRenderer.invoke("overlay:set-interaction-locked", locked),
  setRemindersPaused: (paused) => ipcRenderer.invoke("overlay:set-reminders-paused", paused),
  resetReminders: () => ipcRenderer.invoke("overlay:reset-reminders"),
  openDeveloperConsole: () => ipcRenderer.invoke("developer-console:open"),
  developerConsoleBootstrap: () => ipcRenderer.invoke("developer-console:bootstrap"),
  resetPosition: () => ipcRenderer.invoke("overlay:reset-position"),
  calibrate: () => ipcRenderer.invoke("overlay:calibrate"),
  resize: (height) => ipcRenderer.send("overlay:resize", height),
  setLockControlBounds: (bounds) => ipcRenderer.send("overlay:lock-control-bounds", bounds),
  onState: (callback) => ipcRenderer.on("overlay:state", (_event, state) => callback(state)),
  onPaused: (callback) =>
    ipcRenderer.on("overlay:paused", (_event, paused) => callback(paused)),
  onInteractionLocked: (callback) =>
    ipcRenderer.on("overlay:interaction-locked", (_event, locked) => callback(locked)),
  onMonitorHealth: (callback) =>
    ipcRenderer.on("overlay:monitor-health", (_event, health) => callback(health)),
  onDeveloperConsoleLog: (callback) =>
    ipcRenderer.on("developer-console:log", (_event, entry) => callback(entry)),
});
