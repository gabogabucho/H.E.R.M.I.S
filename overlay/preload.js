const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('hermis', {
  onMessage: (cb) => ipcRenderer.on('hermis:message', (_e, msg) => cb(msg)),
  onStatus: (cb) => ipcRenderer.on('hermis:status', (_e, status) => cb(status)),
  setInteractive: (interactive) => ipcRenderer.send('hermis:interactive', !!interactive),
  openExternal: (url) => ipcRenderer.invoke('hermis:open-external', url),
  copyText: (text) => ipcRenderer.invoke('hermis:copy-text', text),
  refreshSetup: () => ipcRenderer.invoke('hermis:setup-refresh'),
  gesturesStart: () => ipcRenderer.invoke('hermis:gestures-start'),
  gestureClose: (id) => ipcRenderer.send('hermis:gesture-close', id),
  gestureWindow: (action) => ipcRenderer.send('hermis:gesture-window', action),
});
