import { useEffect, useState, useCallback } from 'react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Bug, ChartLine, Lightning, Network, Wrench, Question, MagnifyingGlass, Cpu, Path, Monitor, CircleNotch } from '@phosphor-icons/react'
import { BadDataAnalyticsTab } from '@/components/BadDataAnalyticsTab'
import { PowerFlowTab } from '@/components/PowerFlowTab'
import { StateEstimationTab } from '@/components/StateEstimationTab'
import { TopologyTab } from '@/components/TopologyTab'
import { WorkbenchTab } from '@/components/WorkbenchTab'
import { AgentFrameworkTab } from '@/components/AgentFrameworkTab'
import { PipelineTab } from '@/components/PipelineTab'
import { ConsoleTab } from '@/components/ConsoleTab'
import { HelpTab } from '@/components/HelpTab'
import { HelpSearchCommand } from '@/components/HelpSearchCommand'
import { Button } from '@/components/ui/button'
import { DEFAULT_TOPOLOGIES } from '@/lib/topologies'
import type { Topology } from '@/lib/types'
import { ensureMeasurements } from '@/lib/measurements'
import { loadPandapowerCase } from '@/lib/api'
import { toast } from 'sonner'
import { Toaster } from '@/components/ui/sonner'
import { UpdateBanner } from '@/components/UpdateBanner'

const STORAGE_KEY = 'dsse-topology'

/** Above this serialized size the full topology is not written to
 *  localStorage. A pandapower case of a few thousand buses runs into
 *  megabytes (measured: 1.46 MB for case2869pegase, ~3.4 MB for case6495rte),
 *  and writing it had three costs, all of which showed up as "the app opens
 *  frozen":
 *
 *   - `JSON.stringify` of that much data blocks the main thread, and the
 *     effect below runs on *every* topology change, i.e. on every keystroke in
 *     the topology editor;
 *   - it runs into the ~5 MB localStorage quota, whose exception used to be
 *     swallowed by a bare `catch {}`, so the write silently did nothing;
 *   - whatever did get stored came back on the next boot, re-freezing the app
 *     before the user could do anything about it.
 *
 *  Past the limit we store a pointer to the pandapower case instead and reload
 *  it from the backend on boot. The trade-off is deliberate: meter and switch
 *  edits on a very large network do not survive a reload. They are a click to
 *  redo ("Apply to all"), whereas the alternative was an app that would not
 *  open. */
const MAX_PERSISTED_BYTES = 1_000_000

/** What gets stored in place of a large topology. `caseName` is what
 *  loadPandapowerCase() takes; topology.id for these is `pp_<caseName>`. */
interface StoredCaseRef {
  kind: 'pandapower-ref'
  caseName: string
}

/** Pulls the pandapower case name out of an oversized legacy entry by reading
 *  its `"id":"pp_<case>"` field directly, without parsing the whole document.
 *  Returns null for a hand-built topology, which has no case to reload. */
function legacyCaseName(raw: string): string | null {
  const match = /"id"\s*:\s*"pp_([^"]+)"/.exec(raw.slice(0, 4096))
  return match ? match[1] : null
}

function isCaseRef(value: unknown): value is StoredCaseRef {
  return (
    typeof value === 'object' &&
    value !== null &&
    (value as StoredCaseRef).kind === 'pandapower-ref' &&
    typeof (value as StoredCaseRef).caseName === 'string'
  )
}

const NAV_ITEMS = [
  { value: 'console', label: 'Console', icon: Monitor },
  { value: 'baddata', label: 'Bad Data', icon: Bug },
  { value: 'agents', label: 'Agents', icon: Cpu },
  { value: 'pipeline', label: 'Pipeline', icon: Path },
  { value: 'workbench', label: 'Workbench', icon: Wrench },
  { value: 'powerflow', label: 'Power Flow', icon: Lightning },
  { value: 'estimation', label: 'State Est.', icon: ChartLine },
  { value: 'topology', label: 'Topology', icon: Network },
  { value: 'help', label: 'Help', icon: Question },
] as const

function App() {
  // A stored case pointer can't be resolved synchronously, so the first render
  // always gets the small default topology and the case arrives right after.
  // Starting on the default rather than on a spinner keeps every tab
  // interactive while a multi-thousand-bus case is on its way.
  const [pendingCase, setPendingCase] = useState<string | null>(null)
  const [topology, setTopology] = useState<Topology>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      if (saved) {
        // Size is checked before parsing, not after. An entry written by an
        // older build (which stored the whole topology, however big) is still
        // sitting in the browsers of anyone who ran one, and parsing megabytes
        // of it here blocks the very first render — the app would come up
        // frozen exactly as before, with the new guards never getting a turn.
        // Oversized legacy entries are downgraded to a case pointer where the
        // id allows it, and dropped otherwise.
        if (saved.length > MAX_PERSISTED_BYTES) {
          const caseName = legacyCaseName(saved)
          if (caseName) setPendingCase(caseName)
          else localStorage.removeItem(STORAGE_KEY)
        } else {
          const parsed = JSON.parse(saved) as Topology | StoredCaseRef
          if (isCaseRef(parsed)) setPendingCase(parsed.caseName)
          else return ensureMeasurements(parsed)
        }
      }
    } catch {}
    return ensureMeasurements(DEFAULT_TOPOLOGIES[0])
  })

  useEffect(() => {
    if (!pendingCase) return
    let cancelled = false
    loadPandapowerCase(pendingCase)
      .then((loaded) => {
        if (!cancelled) setTopology(ensureMeasurements(loaded))
      })
      .catch(() => {
        if (!cancelled) toast.error(`Could not reload ${pendingCase} — showing the default network`)
      })
      .finally(() => {
        if (!cancelled) setPendingCase(null)
      })
    return () => {
      cancelled = true
    }
  }, [pendingCase])

  useEffect(() => {
    // Don't overwrite the stored pointer with the placeholder default while
    // the real case is still being fetched.
    if (pendingCase) return
    try {
      const serialized = JSON.stringify(topology)
      if (serialized.length <= MAX_PERSISTED_BYTES) {
        localStorage.setItem(STORAGE_KEY, serialized)
        return
      }
      const caseName = topology.id?.startsWith('pp_') ? topology.id.slice(3) : null
      if (caseName) {
        const ref: StoredCaseRef = { kind: 'pandapower-ref', caseName }
        localStorage.setItem(STORAGE_KEY, JSON.stringify(ref))
      } else {
        // A hand-built topology too large to store: drop the stale entry
        // rather than leave an older, wrong network to come back on boot.
        localStorage.removeItem(STORAGE_KEY)
      }
    } catch (err) {
      // Previously a bare `catch {}`. A quota failure here means the next boot
      // silently restores something other than what's on screen, which is
      // exactly the kind of thing that should not be invisible.
      console.warn('Could not persist the topology:', err)
    }
  }, [topology, pendingCase])

  // ── Help / search palette state ──────────────────────────────────────────
  const [activeTab, setActiveTab] = useState('console')
  const [searchOpen, setSearchOpen] = useState(false)
  const [helpCategoryId, setHelpCategoryId] = useState<string | null>(null)
  const [helpTopicId, setHelpTopicId] = useState<string | null>(null)

  // Ctrl/Cmd + K → open search palette from any tab
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setSearchOpen((v) => !v)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  const handleSelectTopic = useCallback((categoryId: string, topicId: string) => {
    setHelpCategoryId(categoryId)
    setHelpTopicId(topicId)
    setActiveTab('help')
  }, [])

  return (
    <div className="min-h-screen bg-muted/25">
      <UpdateBanner />
      <HelpSearchCommand
        open={searchOpen}
        onOpenChange={setSearchOpen}
        onSelectTopic={handleSelectTopic}
      />
      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full gap-0">
        {/* The active TabsTrigger's own highlighted state already tells you
            which page you're on — no separate page title needed. */}
        <header className="sticky top-0 z-20 flex flex-wrap items-center gap-2 border-b bg-background/95 px-3 py-2 backdrop-blur-sm sm:gap-3 sm:px-4">
          <div className="flex shrink-0 items-center gap-2">
            <img
              src="/app-logo.png"
              alt="DSSE Workbench Logo"
              className="h-8 w-8 shrink-0 rounded-md object-contain border border-border/40 shadow-xs"
            />
            <span className="hidden text-sm font-bold text-primary md:inline">DSSE Workbench</span>
          </div>

          <TabsList className="h-auto gap-1 bg-transparent p-0">
            {NAV_ITEMS.map((item) => (
              <TabsTrigger
                key={item.value}
                value={item.value}
                className="gap-1.5 rounded-md border border-transparent px-2.5 py-1.5 text-xs data-[state=active]:border-transparent data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=active]:shadow-none sm:text-sm"
              >
                <item.icon weight="fill" className="h-4 w-4" />
                <span className="hidden xs:inline">{item.label}</span>
              </TabsTrigger>
            ))}
          </TabsList>

          <div className="ml-auto flex flex-wrap items-center gap-1.5">
            <Button
              variant="outline"
              size="sm"
              className="hidden h-7 gap-1.5 text-xs text-muted-foreground sm:flex"
              onClick={() => setSearchOpen(true)}
            >
              <MagnifyingGlass className="h-3 w-3" />
              Search docs
              <kbd className="pointer-events-none ml-1 rounded border bg-muted px-1 text-[10px] font-medium">
                ⌘K
              </kbd>
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 sm:hidden"
              onClick={() => setSearchOpen(true)}
              aria-label="Search help"
            >
              <MagnifyingGlass className="h-4 w-4" />
            </Button>
            {/* While a stored case pointer is being resolved the app is
                showing the default network, which otherwise looks like the
                saved one was silently lost. A big case takes tens of seconds
                to come back from the backend, so say what is happening. */}
            {pendingCase ? (
              <span
                className="flex max-w-50 items-center gap-1 truncate rounded-full border border-status-warn/50 bg-status-warn/10 px-2 py-1 text-xs text-status-warn sm:max-w-none"
                title={`Reloading ${pendingCase} from the backend`}
              >
                <CircleNotch className="h-3 w-3 shrink-0 animate-spin" />
                <span className="truncate">Restoring {pendingCase}…</span>
              </span>
            ) : (
              <span
                className="flex max-w-50 items-center gap-1 truncate rounded-full border bg-muted/80 px-2 py-1 text-xs sm:max-w-none"
                title={topology.name}
              >
                <Network className="h-3 w-3 shrink-0 text-accent" />
                <span className="truncate">{topology.name}</span>
              </span>
            )}
            <img src="/cnrs-logo.png" alt="CNRS" className="h-6 w-auto object-contain" />
            <img src="/g2elab-logo.png" alt="G2Elab" className="h-6 w-auto object-contain" />
          </div>
        </header>

        <div className="px-3 py-4 sm:px-6 sm:py-6">
          <TabsContent value="console" className="mt-0">
            <ConsoleTab topology={topology} restoring={!!pendingCase} />
          </TabsContent>

          <TabsContent value="baddata" className="mt-0">
            <BadDataAnalyticsTab topology={topology} />
          </TabsContent>

          <TabsContent value="agents" className="mt-0">
            <AgentFrameworkTab topology={topology} />
          </TabsContent>

          <TabsContent value="pipeline" className="mt-0">
            <PipelineTab topology={topology} />
          </TabsContent>

          <TabsContent value="workbench" className="mt-0">
            <WorkbenchTab topology={topology} />
          </TabsContent>

          <TabsContent value="powerflow" className="mt-0">
            <PowerFlowTab topology={topology} />
          </TabsContent>

          <TabsContent value="estimation" className="mt-0">
            <StateEstimationTab topology={topology} />
          </TabsContent>

          <TabsContent value="topology" className="mt-0">
            <TopologyTab topology={topology} onTopologyChange={setTopology} />
          </TabsContent>

          <TabsContent value="help" className="mt-0">
            <HelpTab
              selectedCategoryId={helpCategoryId}
              selectedTopicId={helpTopicId}
              onSelectTopic={handleSelectTopic}
            />
          </TabsContent>
        </div>
      </Tabs>
      <Toaster />
    </div>
  )
}

export default App
