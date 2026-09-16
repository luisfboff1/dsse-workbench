/**
 * Aviso de atualização do app empacotado.
 *
 * O electron-updater baixa a nova versão sozinho em segundo plano, mas não
 * mostra nada — sem este banner a atualização entra calada no próximo restart
 * e o usuário nunca sabe que ela existiu. Aqui só traduzimos os eventos do
 * processo principal em algo visível, com um botão para reiniciar na hora.
 *
 * Renderiza `null` no browser (dev), onde `window.dsseUpdater` não existe.
 */

import { useEffect, useState } from 'react'
import { ArrowClockwise, DownloadSimple } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { getUpdater } from '@/lib/electron'

type Status = 'idle' | 'downloading' | 'ready'

export function UpdateBanner() {
  const [status, setStatus] = useState<Status>('idle')
  const [version, setVersion] = useState<string | null>(null)
  const [percent, setPercent] = useState(0)

  useEffect(() => {
    const updater = getUpdater()
    if (!updater) return

    updater.onAvailable((info) => {
      setVersion(info.version)
      setStatus('downloading')
    })
    updater.onProgress((info) => setPercent(info.percent))
    updater.onReady((info) => {
      setVersion(info.version)
      setStatus('ready')
    })
  }, [])

  if (status === 'idle') return null

  return (
    <div className="flex items-center gap-2 border-b bg-accent/10 px-3 py-1.5 text-xs sm:px-4">
      {status === 'downloading' ? (
        <>
          <DownloadSimple className="h-3.5 w-3.5 shrink-0 text-accent" />
          <span className="text-muted-foreground">
            Downloading version {version}… {Math.round(percent)}%
          </span>
        </>
      ) : (
        <>
          <ArrowClockwise className="h-3.5 w-3.5 shrink-0 text-accent" />
          <span>
            Version {version} is ready to install.
          </span>
          <Button
            size="sm"
            variant="outline"
            className="ml-auto h-6 gap-1.5 text-xs"
            onClick={() => void getUpdater()?.install()}
          >
            Restart now
          </Button>
        </>
      )}
    </div>
  )
}
