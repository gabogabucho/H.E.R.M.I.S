const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('hermis', {
  onMessage: (cb) => ipcRenderer.on('hermis:message', (_e, msg) => cb(msg)),
  onStatus: (cb) => ipcRenderer.on('hermis:status', (_e, status) => cb(status)),
  setInteractive: (interactive) => ipcRenderer.send('hermis:interactive', !!interactive),
});
