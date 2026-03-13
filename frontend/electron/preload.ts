import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  getBackendUrl: () => 'http://127.0.0.1:8420',
  platform: process.platform,

  // Диалоги
  openFile: (options: object) => ipcRenderer.invoke('dialog:openFile', options),
  openDirectory: (options?: object) => ipcRenderer.invoke('dialog:openDirectory', options),

  // Файловая система
  readTextFile: (filePath: string) => ipcRenderer.invoke('fs:readTextFile', filePath),
  readDirectory: (dirPath: string) => ipcRenderer.invoke('fs:readDirectory', dirPath),
  readFile: (filePath: string) => ipcRenderer.invoke('fs:readFile', filePath),
  renameFile: (oldPath: string, newPath: string) => ipcRenderer.invoke('fs:renameFile', oldPath, newPath),
})
