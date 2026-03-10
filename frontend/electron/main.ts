import { app, BrowserWindow, ipcMain, dialog } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import path from 'path'
import fs from 'fs'

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

  pythonProcess = spawn(pythonPath, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8420'], {
    cwd: backendDir,
    stdio: 'pipe',
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
