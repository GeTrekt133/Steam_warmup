import { app, BrowserWindow, ipcMain, dialog } from 'electron'
import { spawn, type ChildProcess } from 'child_process'
import path from 'path'
import fs from 'fs'
import { fileURLToPath } from 'url'

// ESM не имеет __dirname — создаём вручную
const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

let pythonProcess: ChildProcess | null = null
let mainWindow: BrowserWindow | null = null

function findPython(): string {
  // Ищем Python в venv backend-а, потом системный
  const venvPaths = [
    path.join(__dirname, '../../backend/venv/Scripts/python.exe'),
    path.join(__dirname, '../../backend/venv/bin/python'),
  ]
  for (const p of venvPaths) {
    if (fs.existsSync(p)) return p
  }
  return 'python'
}

function startPythonBackend() {
  const pythonPath = findPython()
  const backendDir = path.join(__dirname, '../../backend')

  try {
    pythonProcess = spawn(pythonPath, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8420'], {
      cwd: backendDir,
      stdio: 'pipe',
    })

    pythonProcess.on('error', (err: Error) => {
      console.error(`[backend] Failed to start Python: ${err.message}`)
      pythonProcess = null
    })

    pythonProcess.stdout?.on('data', (data: Buffer) => {
      console.log(`[backend] ${data.toString().trim()}`)
    })
    pythonProcess.stderr?.on('data', (data: Buffer) => {
      console.error(`[backend] ${data.toString().trim()}`)
    })
    pythonProcess.on('close', (code: number | null) => {
      console.log(`[backend] Process exited with code ${code}`)
    })
  } catch (err) {
    console.error(`[backend] Failed to spawn Python process: ${err}`)
    pythonProcess = null
  }
}

async function waitForBackend(url: string, retries = 30, delay = 500): Promise<boolean> {
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(url)
      if (res.ok) return true
    } catch {
      // Backend not ready yet
    }
    await new Promise(r => setTimeout(r, delay))
  }
  return false
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    backgroundColor: '#09090b',
    show: false, // Показываем после загрузки
    webPreferences: {
      preload: path.join(__dirname, 'preload.mjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  // В dev — загружаем Vite dev server, в prod — собранный файл
  if (process.env.VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(process.env.VITE_DEV_SERVER_URL)
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'))
  }

  mainWindow.once('ready-to-show', () => {
    mainWindow?.show()
  })
}

// IPC: выбор файла (для импорта аккаунтов, прокси и т.д.)
ipcMain.handle('dialog:openFile', async (_event, options) => {
  if (!mainWindow) return null
  return dialog.showOpenDialog(mainWindow, options)
})

// IPC: выбор папки
ipcMain.handle('dialog:openDirectory', async (_event, options) => {
  if (!mainWindow) return null
  return dialog.showOpenDialog(mainWindow, {
    ...options,
    properties: ['openDirectory'],
  })
})

// IPC: прочитать текстовый файл
ipcMain.handle('fs:readTextFile', async (_event, filePath: string) => {
  return fs.readFileSync(filePath, 'utf-8')
})

// IPC: прочитать список файлов в папке
ipcMain.handle('fs:readDirectory', async (_event, dirPath: string) => {
  const entries = fs.readdirSync(dirPath)
  return entries.map((name) => ({
    name,
    path: path.join(dirPath, name),
    isFile: fs.statSync(path.join(dirPath, name)).isFile(),
  }))
})

// IPC: прочитать файл (для maFile — JSON)
ipcMain.handle('fs:readFile', async (_event, filePath: string) => {
  return fs.readFileSync(filePath, 'utf-8')
})

// IPC: переименовать файл
ipcMain.handle('fs:renameFile', async (_event, oldPath: string, newPath: string) => {
  fs.renameSync(oldPath, newPath)
  return true
})

app.whenReady().then(async () => {
  startPythonBackend()

  const backendReady = await waitForBackend('http://127.0.0.1:8420/api/health')
  if (!backendReady) {
    console.error('[main] Backend failed to start within 15 seconds')
  }

  createWindow()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  if (pythonProcess && !pythonProcess.killed) {
    pythonProcess.kill()
  }
})
