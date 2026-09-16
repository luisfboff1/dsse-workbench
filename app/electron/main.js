/**
 * Processo principal do Electron — sobe o backend Python e abre a janela.
 *
 * O backend não é um servidor remoto: é um .exe (PyInstaller) que roda como
 * processo filho deste, escutando só em 127.0.0.1 numa porta efêmera. Ele
 * também serve a SPA, então a janela carrega http://127.0.0.1:<porta>/ em vez
 * de file:// — assim o fetch('/api/...') relativo do frontend continua valendo
 * sem CORS nem reescrita de caminho.
 */

const { app, BrowserWindow, shell, dialog, ipcMain, Menu } = require('electron')
const { spawn } = require('child_process')
const path = require('path')
const readline = require('readline')
const { autoUpdater } = require('electron-updater')

const isDev = !app.isPackaged

let backend = null
let mainWindow = null
let backendPort = null

/** Caminho do executável do backend, empacotado como extraResources. */
function backendExecutable() {
  const exe = process.platform === 'win32' ? 'dsse-backend.exe' : 'dsse-backend'
  return path.join(process.resourcesPath, 'backend', exe)
}

/**
 * Sobe o backend e resolve com a porta que ele escolheu.
 *
 * O contrato é a linha `DSSE_BACKEND_PORT=<porta>` no stdout — ver
 * packaging/backend_entry.py. Só lemos a porta dele; nunca assumimos 8000,
 * porque a porta fixa quebra quando o usuário abre duas cópias do app.
 */
function startBackend() {
  return new Promise((resolve, reject) => {
    const exePath = backendExecutable()

    backend = spawn(exePath, [], {
      // O backend grava cenários aqui. Passar explícito mantém app e
      // desinstalador de acordo sobre onde ficam os dados do usuário.
      env: { ...process.env, DSSE_DATA_DIR: app.getPath('userData') },
      windowsHide: true,
    })

    backend.on('error', (err) =>
      reject(new Error(`Falha ao iniciar o backend (${exePath}): ${err.message}`))
    )

    // Se o backend morrer antes de anunciar a porta, o app trava numa tela
    // branca — então tratamos a saída precoce como erro explícito.
    backend.on('exit', (code) => {
      if (backendPort === null) {
        reject(new Error(`Backend encerrou com código ${code} antes de abrir a porta.`))
      }
    })

    readline.createInterface({ input: backend.stdout }).on('line', (line) => {
      const match = line.match(/^DSSE_BACKEND_PORT=(\d+)$/)
      if (match) {
        backendPort = Number(match[1])
        resolve(backendPort)
      }
    })

    // stderr do uvicorn vai para o console do Electron, para diagnóstico.
    readline.createInterface({ input: backend.stderr }).on('line', (line) =>
      console.error('[backend]', line)
    )
  })
}

function createWindow(port) {
  const iconPath = path.join(__dirname, 'icon.png')
  mainWindow = new BrowserWindow({
    width: 1600,
    height: 1000,
    icon: iconPath,
    show: false,
    webPreferences: { preload: path.join(__dirname, 'preload.js') },
  })

  mainWindow.once('ready-to-show', () => mainWindow.show())
  mainWindow.loadURL(`http://127.0.0.1:${port}/`)

  // Links externos (papers, docs) abrem no browser, não dentro do app.
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })
}

/**
 * Liga o electron-updater à UI e aos comandos manuais.
 */
function setupAutoUpdater() {
  ipcMain.handle('app:version', () => app.getVersion())

  ipcMain.handle('update:check', async () => {
    if (isDev) {
      return { status: 'dev', version: app.getVersion() }
    }
    try {
      const checkResult = await autoUpdater.checkForUpdates()
      return { status: 'checking', updateInfo: checkResult?.updateInfo }
    } catch (err) {
      return { status: 'error', message: err.message || String(err) }
    }
  })

  ipcMain.handle('update:install', () => autoUpdater.quitAndInstall())

  if (isDev) return // em dev não há release para comparar

  const send = (channel, payload) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send(channel, payload)
    }
  }

  autoUpdater.on('update-available', (info) => send('update:available', { version: info.version }))
  autoUpdater.on('update-not-available', (info) => send('update:not-available', { version: info.version }))
  autoUpdater.on('download-progress', (p) => send('update:progress', { percent: p.percent }))
  autoUpdater.on('update-downloaded', (info) => send('update:ready', { version: info.version }))
  autoUpdater.on('error', (err) => {
    console.error('[updater]', err)
    send('update:error', { message: err.message || String(err) })
  })

  // Checagem silenciosa automática no boot
  autoUpdater.checkForUpdatesAndNotify().catch((err) => console.error('[updater]', err))
}

function createMenu() {
  const isMac = process.platform === 'darwin'
  const template = [
    ...(isMac ? [{ role: 'appMenu' }] : []),
    {
      label: 'File',
      submenu: [
        isMac ? { role: 'close' } : { role: 'quit', label: 'Exit' }
      ]
    },
    {
      label: 'Edit',
      submenu: [
        { role: 'undo' },
        { role: 'redo' },
        { type: 'separator' },
        { role: 'cut' },
        { role: 'copy' },
        { role: 'paste' },
        { role: 'selectAll' }
      ]
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload' },
        { role: 'forceReload' },
        { role: 'toggleDevTools' },
        { type: 'separator' },
        { role: 'resetZoom' },
        { role: 'zoomIn' },
        { role: 'zoomOut' },
        { type: 'separator' },
        { role: 'togglefullscreen' }
      ]
    },
    {
      label: 'Help',
      submenu: [
        {
          label: 'Check for Updates...',
          click: async () => {
            if (isDev) {
              dialog.showMessageBox(mainWindow, {
                type: 'info',
                title: 'Check for Updates',
                message: 'Running in development mode.',
                detail: `Version: ${app.getVersion()} (dev)`
              })
              return
            }
            try {
              const res = await autoUpdater.checkForUpdates()
              if (!res || !res.downloadPromise) {
                dialog.showMessageBox(mainWindow, {
                  type: 'info',
                  title: 'Check for Updates',
                  message: 'DSSE Workbench is up to date.',
                  detail: `You are running the latest version (v${app.getVersion()}).`
                })
              }
            } catch (err) {
              dialog.showMessageBox(mainWindow, {
                type: 'error',
                title: 'Update Error',
                message: 'Failed to check for updates.',
                detail: String(err.message || err)
              })
            }
          }
        },
        { type: 'separator' },
        {
          label: 'GitHub Releases & Downloads',
          click: () => shell.openExternal('https://github.com/luisfboff1/dsse-workbench-releases/releases')
        },
        { type: 'separator' },
        {
          label: 'About DSSE Workbench',
          click: () => {
            dialog.showMessageBox(mainWindow, {
              type: 'info',
              title: 'About DSSE Workbench',
              message: `DSSE Simulation Workbench v${app.getVersion()}`,
              detail: 'Distribution System State Estimation & Multi-Agent IA\nAuthor: Luis Fernando Boff (UGA / CNRS G2Elab)\nLicense: MIT'
            })
          }
        }
      ]
    }
  ]

  const menu = Menu.buildFromTemplate(template)
  Menu.setApplicationMenu(menu)
}

// Instância única: duas cópias subiriam dois backends e brigariam pelos dados.
if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.focus()
    }
  })

  app.whenReady().then(async () => {
    try {
      createMenu()
      const port = await startBackend()
      createWindow(port)
      setupAutoUpdater()
    } catch (err) {
      dialog.showErrorBox('DSSE Workbench', String(err.message || err))
      app.quit()
    }
  })
}

// O backend é filho deste processo: se o app fecha, ele tem que morrer junto,
// senão fica um .exe órfão segurando a porta e os dados.
app.on('before-quit', () => {
  if (backend && !backend.killed) backend.kill()
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
