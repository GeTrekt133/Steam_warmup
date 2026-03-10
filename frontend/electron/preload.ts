import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  getBackendUrl: () => 'http://127.0.0.1:8420',
  platform: process.platform,
  openFile: (options: object) => ipcRenderer.invoke('dialog:openFile', options),
})
