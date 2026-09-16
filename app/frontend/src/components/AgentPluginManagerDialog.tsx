import { useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { Cpu, PlugsConnected, Sliders, ShieldCheck } from '@phosphor-icons/react'
import type { AgentPluginData } from '@/lib/agentTypes'

interface AgentPluginManagerDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  plugins: AgentPluginData[]
  onTogglePlugin: (pluginId: string, enabled: boolean) => void
}

export function AgentPluginManagerDialog({
  open,
  onOpenChange,
  plugins,
  onTogglePlugin,
}: AgentPluginManagerDialogProps) {
  const [selectedPlugin, setSelectedPlugin] = useState<AgentPluginData | null>(null)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl sm:max-w-4xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <PlugsConnected className="h-5 w-5" />
            </div>
            <div>
              <DialogTitle className="text-base font-semibold">Agent Plugin & Extensibility Hub</DialogTitle>
              <DialogDescription className="text-xs">
                Modular AI/ML models, physics-informed line rating, and bad-data detectors seamlessly plugged into distributed agents.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="grid grid-cols-1 md:grid-cols-12 gap-4 mt-2">
          {/* Plugin list */}
          <div className="md:col-span-7 space-y-2">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Installed Plugins ({plugins.length})
            </h4>
            <div className="space-y-2">
              {plugins.map((plugin) => (
                <div
                  key={plugin.plugin_id}
                  onClick={() => setSelectedPlugin(plugin)}
                  className={`flex items-start justify-between p-3 rounded-lg border text-xs cursor-pointer transition-colors ${
                    selectedPlugin?.plugin_id === plugin.plugin_id
                      ? 'border-primary bg-primary/5 shadow-xs'
                      : 'border-border hover:bg-muted/50'
                  }`}
                >
                  <div className="space-y-1 pr-2">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="font-semibold text-foreground">{plugin.name}</span>
                      <Badge variant="outline" className="text-[10px] py-0 px-1.5">
                        v{plugin.version}
                      </Badge>
                      <Badge variant="secondary" className="text-[10px] py-0 px-1.5 capitalize">
                        {plugin.category.replace('_', ' ')}
                      </Badge>
                    </div>
                    <p className="text-muted-foreground line-clamp-2">{plugin.description}</p>
                    <div className="text-[11px] text-muted-foreground/80">
                      Author: <span className="font-medium">{plugin.author}</span>
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-2 shrink-0 pt-0.5" onClick={(e) => e.stopPropagation()}>
                    <Switch
                      checked={plugin.enabled}
                      onCheckedChange={(checked) => onTogglePlugin(plugin.plugin_id, checked)}
                      aria-label={`Toggle ${plugin.name}`}
                    />
                    <span className="text-[10px] font-medium text-muted-foreground">
                      {plugin.enabled ? 'Active' : 'Disabled'}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Plugin Details / Parameters Inspector */}
          <div className="md:col-span-5 rounded-lg border bg-muted/20 p-3 space-y-3">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              <Sliders className="h-3.5 w-3.5" />
              Plugin Inspector
            </h4>

            {selectedPlugin ? (
              <div className="space-y-3 text-xs">
                <div>
                  <div className="font-semibold text-foreground text-sm">{selectedPlugin.name}</div>
                  <div className="text-[11px] text-muted-foreground mt-0.5">{selectedPlugin.description}</div>
                </div>

                <div className="rounded-md border bg-background p-2.5 space-y-1.5">
                  <div className="text-[11px] font-semibold text-muted-foreground">Configuration Parameters:</div>
                  {Object.entries(selectedPlugin.parameters).length > 0 ? (
                    <div className="space-y-1">
                      {Object.entries(selectedPlugin.parameters).map(([key, val]) => (
                        <div key={key} className="flex justify-between items-center py-0.5 border-b border-border/40 text-[11px]">
                          <span className="text-muted-foreground font-mono">{key}</span>
                          <span className="font-medium font-mono">{String(val)}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-[11px] text-muted-foreground italic">No adjustable parameters.</p>
                  )}
                </div>

                <div className="rounded-md bg-muted/50 p-2 text-[11px] space-y-1">
                  <div className="flex items-center gap-1 text-primary font-medium">
                    <ShieldCheck className="h-3.5 w-3.5" />
                    Integration Status
                  </div>
                  <p className="text-muted-foreground">
                    Attached to target agents automatically during DSSE execution. Output data conforms to IEEE physical constraints.
                  </p>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-8 text-center text-muted-foreground space-y-1.5">
                <Cpu className="h-8 w-8 stroke-1 text-muted-foreground/60" />
                <p className="text-xs">Select a plugin on the left to inspect parameters and execution metadata.</p>
              </div>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

