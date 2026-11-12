import { useState } from 'react'
import { CircleNotch, Fingerprint } from '@phosphor-icons/react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { fetchOfflineFigure } from '@/lib/api'
import { computeOneLineLayout } from '@/lib/oneLineLayout'
import { getElk } from '@/lib/elk'
import type { Topology } from '@/lib/types'

interface OfflineStageCardProps {
  topology: Topology
  noiseLevel: number
  sigmaMin: number
}

/**
 * The GLRT's offline stage on the one-line diagram: each line's fingerprint
 * S_ℓ, what survives in the residual M = (I−K)S_ℓ, and δ_ℓ (1 MW between the
 * line's ends). Same figure as the loop notebook and the methods guide §7.1 —
 * the backend renders it (src/tese_dsse/estimacao_estado/figura_offline.py),
 * this card only supplies the layout the Topology tab already uses, so the
 * drawing matches the app's one-line view.
 */
export function OfflineStageCard({ topology, noiseLevel, sigmaMin }: OfflineStageCardProps) {
  const [html, setHtml] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const show = async () => {
    setLoading(true)
    setError(null)
    try {
      const lay = await computeOneLineLayout(getElk(), topology)
      const nodes: Record<number, [number, number, number]> = {}
      for (const n of lay.nodes) nodes[n.id] = [n.x, n.y, n.w]
      const edges: Record<number, [number, number][]> = {}
      for (const e of lay.edges) if (e.lineId !== undefined) edges[e.lineId] = e.points
      const r = await fetchOfflineFigure({ topology, noise_level: noiseLevel, sigma_min: sigmaMin, layout: { nodes, edges } })
      setHtml(r.html)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Card>
      <CardHeader className="p-4 pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <Fingerprint weight="fill" className="text-status-warn" />
          Offline stage of the GLRT — line fingerprints S_ℓ and δ_ℓ
        </CardTitle>
        <CardDescription className="text-xs">
          Computed once per topology and meter plan, before any measurement arrives. S_ℓ: how every meter would move
          if line ℓ's parameters were 10% off (in σ). M = (I−K)S_ℓ: what of that survives in the residual. δ_ℓ: share of
          1 MW injected between the line's ends that flows through the line itself — it undoes the network's
          distortion of the error size (t̂ = c/(1 − cδ)).
        </CardDescription>
      </CardHeader>
      <CardContent className="p-4 space-y-3">
        {!html && (
          <Button size="sm" variant="outline" onClick={show} disabled={loading}>
            {loading ? <CircleNotch className="w-4 h-4 mr-2 animate-spin" /> : <Fingerprint className="w-4 h-4 mr-2" />}
            {loading ? 'Building the library…' : 'Show offline stage'}
          </Button>
        )}
        {error && (
          <Alert variant="destructive"><AlertDescription className="text-xs">{error}</AlertDescription></Alert>
        )}
        {html && (
          <iframe
            title="Offline stage of the GLRT"
            srcDoc={html}
            className="w-full rounded-md border border-border bg-white"
            style={{ height: 760 }}
            sandbox="allow-scripts"
          />
        )}
      </CardContent>
    </Card>
  )
}
