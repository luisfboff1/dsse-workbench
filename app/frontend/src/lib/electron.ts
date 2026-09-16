/**
 * Ponte com o Electron, exposta pelo preload (app/electron/preload.js).
 *
 * Fica `undefined` quando o app roda no browser (dev com Vite, ou alguém
 * abrindo o backend direto na porta) — todo consumidor precisa checar antes
 * de usar, porque o browser não tem atualizador nenhum.
 */

export type UpdateInfo = { version: string }
export type UpdateProgress = { percent: number }
export type UpdateError = { message: string }
export type CheckResult = { status: 'dev' | 'checking' | 'error'; version?: string; updateInfo?: unknown; message?: string }

export interface DsseUpdater {
  getVersion?: () => Promise<string>
  checkForUpdates?: () => Promise<CheckResult>
  onAvailable: (cb: (info: UpdateInfo) => void) => void
  onNotAvailable?: (cb: (info: UpdateInfo) => void) => void
  onProgress: (cb: (info: UpdateProgress) => void) => void
  onReady: (cb: (info: UpdateInfo) => void) => void
  onError?: (cb: (err: UpdateError) => void) => void
  install: () => Promise<void>
}

declare global {
  interface Window {
    dsseUpdater?: DsseUpdater
  }
}

/** O atualizador, ou `null` fora do app empacotado. */
export function getUpdater(): DsseUpdater | null {
  return window.dsseUpdater ?? null
}
