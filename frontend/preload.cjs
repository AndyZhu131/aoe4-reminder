const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("aoeOverlay", {
  bootstrap: () => ipcRenderer.invoke("overlay:bootstrap"),
  hide: () => ipcRenderer.invoke("overlay:hide"),
  close: () => ipcRenderer.invoke("overlay:close"),
  setFlashing: (enabled) => ipcRenderer.invoke("overlay:set-flashing", enabled),
  resetPosition: () => ipcRenderer.invoke("overlay:reset-position"),
  calibrate: () => ipcRenderer.invoke("overlay:calibrate"),
  resize: (height) => ipcRenderer.send("overlay:resize", height),
  onState: (callback) => ipcRenderer.on("overlay:state", (_event, state) => callback(state)),
  onFlashing: (callback) =>
    ipcRenderer.on("overlay:flashing", (_event, enabled) => callback(enabled)),
});
