import { useState, useEffect } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { FloppyDisk } from '@phosphor-icons/react'
import { toast } from 'sonner'
import type { Topology } from '@/lib/types'

interface SaveTopologyDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  topology: Topology
  onSave: (savedTopology: Topology) => void
}

export function SaveTopologyDialog({ open, onOpenChange, topology, onSave }: SaveTopologyDialogProps) {
  const [name, setName] = useState('')

  useEffect(() => {
    if (open) {
      const defaultName = topology.name?.includes('(Custom)') || topology.name?.includes('(Modified)')
        ? topology.name
        : `${topology.name || 'Network'} (Custom)`
      setName(defaultName)
    }
  }, [open, topology.name])

  const handleSave = () => {
    const trimmed = name.trim()
    if (!trimmed) {
      toast.error('Please enter a name for the topology.')
      return
    }

    const customId = `custom_${Date.now()}`
    const savedTopology: Topology = {
      ...topology,
      id: customId,
      name: trimmed,
      meta: {
        ...(topology.meta ?? {}),
        source: 'custom_saved',
        savedAt: new Date().toISOString(),
      },
    }

    try {
      const raw = localStorage.getItem('dsse_saved_topologies')
      const existing: Topology[] = raw ? JSON.parse(raw) : []
      // Replace if same ID exists, or prepend new
      const filtered = existing.filter((t) => t.id !== customId)
      localStorage.setItem('dsse_saved_topologies', JSON.stringify([savedTopology, ...filtered]))
      
      onSave(savedTopology)
      toast.success(`Topology "${trimmed}" saved to custom library!`)
      onOpenChange(false)
    } catch (err: any) {
      toast.error(`Failed to save topology: ${err.message}`)
    }
  }

  const busCount = topology.buses?.length ?? 0
  const lineCount = topology.lines?.length ?? 0
  const switchCount = topology.switches?.length ?? 0
  const meterCount = (topology.measurements?.length ?? 0) + (topology.line_measurements?.length ?? 0)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FloppyDisk size={20} className="text-primary" />
            Save Topology
          </DialogTitle>
          <DialogDescription>
            Save your modified network configuration, switches, and meter assignments to your local library.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <div className="space-y-2">
            <Label htmlFor="topo-name">Topology Name</Label>
            <Input
              id="topo-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. IEEE 70-Bus Reconfigured"
              autoFocus
            />
          </div>

          <div className="rounded-lg border bg-muted/30 p-3 space-y-2 text-xs">
            <div className="font-medium text-foreground">Summary of active network:</div>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">{busCount} buses</Badge>
              <Badge variant="outline">{lineCount} lines</Badge>
              {switchCount > 0 && <Badge variant="outline">{switchCount} switches</Badge>}
              <Badge variant="secondary">{meterCount} meters configured</Badge>
            </div>
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} className="gap-2">
            <FloppyDisk size={16} />
            Save Topology
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

