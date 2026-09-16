import { useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ListBullets, Warning, Info, Bug, ShieldWarning, Funnel } from '@phosphor-icons/react'
import type { AgentEventLogItem } from '@/lib/agentTypes'

interface AgentEventLogCardProps {
  events: AgentEventLogItem[]
}

export function AgentEventLogCard({ events }: AgentEventLogCardProps) {
  const [filterLevel, setFilterLevel] = useState<string>('all')

  const filteredEvents = events.filter((ev) => {
    if (filterLevel === 'all') return true
    return ev.level.toLowerCase() === filterLevel.toLowerCase()
  })

  return (
    <Card className="border-border shadow-xs">
      <CardHeader className="py-3 px-4 border-b">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <ListBullets className="h-4 w-4 text-primary" />
            Agent Interaction Timeline & Event Log
            <Badge variant="secondary" className="text-[10px] py-0 px-1.5 ml-1">
              {events.length} events
            </Badge>
          </CardTitle>

          <div className="flex items-center gap-1">
            <Funnel className="h-3 w-3 text-muted-foreground" />
            <Button
              variant={filterLevel === 'all' ? 'secondary' : 'ghost'}
              size="sm"
              className="h-6 text-[11px] px-2"
              onClick={() => setFilterLevel('all')}
            >
              All
            </Button>
            <Button
              variant={filterLevel === 'warning' ? 'secondary' : 'ghost'}
              size="sm"
              className="h-6 text-[11px] px-2 text-amber-600 dark:text-amber-400"
              onClick={() => setFilterLevel('warning')}
            >
              Warnings / Cries
            </Button>
            <Button
              variant={filterLevel === 'info' ? 'secondary' : 'ghost'}
              size="sm"
              className="h-6 text-[11px] px-2"
              onClick={() => setFilterLevel('info')}
            >
              Info
            </Button>
          </div>
        </div>
      </CardHeader>

      <CardContent className="p-0 max-h-72 overflow-y-auto divide-y divide-border/60">
        {filteredEvents.length === 0 ? (
          <div className="py-8 text-center text-xs text-muted-foreground">
            No agent events to display for the selected filter.
          </div>
        ) : (
          filteredEvents.map((ev, idx) => {
            const isCry = ev.message.includes('Engineer Cry') || ev.message.includes('RANK-DEFICIENT')
            const isBadData = ev.kind === 'bad_data' || ev.message.includes('FLAGGED')
            const isWarn = ev.level === 'WARNING' || isCry

            return (
              <div
                key={idx}
                className={`p-3 flex items-start gap-2.5 text-xs transition-colors ${
                  isCry ? 'bg-amber-500/10' : isBadData && isWarn ? 'bg-destructive/10' : 'hover:bg-muted/30'
                }`}
              >
                <div className="mt-0.5 shrink-0">
                  {isCry ? (
                    <ShieldWarning className="h-4 w-4 text-amber-600 dark:text-amber-400" />
                  ) : isWarn ? (
                    <Warning className="h-4 w-4 text-amber-500" />
                  ) : isBadData ? (
                    <Bug className="h-4 w-4 text-primary" />
                  ) : (
                    <Info className="h-4 w-4 text-muted-foreground" />
                  )}
                </div>

                <div className="flex-1 min-w-0 space-y-0.5">
                  <div className="flex items-center gap-1.5 flex-wrap">
                    <Badge variant="outline" className="text-[10px] py-0 px-1 font-mono">
                      {ev.agent_id}
                    </Badge>
                    <span className="text-[10px] text-muted-foreground uppercase font-medium">
                      Cluster {ev.cluster_id >= 0 ? ev.cluster_id : 'Global'}
                    </span>
                    {isCry && (
                      <Badge className="bg-amber-500 hover:bg-amber-600 text-white text-[10px] py-0 px-1 font-bold">
                        ENGINEER CRY
                      </Badge>
                    )}
                  </div>
                  <p className="text-foreground leading-relaxed">{ev.message}</p>
                </div>
              </div>
            )
          })
        )}
      </CardContent>
    </Card>
  )
}

