/**
 * Ponte entre o processo principal e o React.
 *
 * O renderer roda sem acesso a Node (contextIsolation padrão do Electron), então
 * o frontend não consegue falar com o electron-updater direto. Aqui expomos só
 * o mínimo: assinar os eventos de atualização e pedir a instalação.
 */

const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('dsseUpdater', {
  /** Obtém a versão do app empacotado. */
  getVersion: () => ipcRenderer.invoke('app:version'),
  /** Dispara verificação manual de atualizações. */
  checkForUpdates: () => ipcRenderer.invoke('update:check'),
  /** Nova versão detectada (download começa sozinho, em segundo plano). */
  onAvailable: (cb) => ipcRenderer.on('update:available', (_e, info) => cb(info)),
  /** Já está na versão mais recente. */
  onNotAvailable: (cb) => ipcRenderer.on('update:not-available', (_e, info) => cb(info)),
  /** Progresso do download, para uma barra opcional. */
  onProgress: (cb) => ipcRenderer.on('update:progress', (_e, info) => cb(info)),
  /** Download concluído — a partir daqui `install()` reinicia já atualizado. */
  onReady: (cb) => ipcRenderer.on('update:ready', (_e, info) => cb(info)),
  /** Erro no atualizador. */
  onError: (cb) => ipcRenderer.on('update:error', (_e, err) => cb(err)),
  /** Fecha o app, aplica a atualização e reabre. */
  install: () => ipcRenderer.invoke('update:install'),
})
