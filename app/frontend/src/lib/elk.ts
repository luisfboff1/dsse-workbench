import ELK from 'elkjs/lib/elk-api'
import elkWorkerUrl from 'elkjs/lib/elk-worker.min.js?url'

let elkInstance: InstanceType<typeof ELK> | null = null

/** One ELK per app, backed by a Web Worker so a big layout never blocks the UI
 *  thread. Shared by the one-line view and the offline-stage figure. */
export function getElk(): InstanceType<typeof ELK> {
  if (!elkInstance) elkInstance = new ELK({ workerUrl: elkWorkerUrl })
  return elkInstance
}
