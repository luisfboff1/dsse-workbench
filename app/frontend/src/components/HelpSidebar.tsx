/**
 * Help sidebar — accordion-based tree of categories and topics.
 * Used inside HelpTab on desktop; also rendered inside a Sheet on mobile.
 */
import { useState, useEffect } from 'react'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { getUpdater } from '@/lib/electron'
import { toast } from 'sonner'
import { HELP_CATEGORIES } from '@/lib/helpContent'
import type { Paradigm } from '@/lib/helpContent'
import {
  Function,
  Equals,
  Bug,
  Gauge,
  BookOpen,
  Atom,
  Database,
  Cpu,
  Path,
  ArrowClockwise,
  CircleNotch,
} from '@phosphor-icons/react'

// ─── Icon lookup ─────────────────────────────────────────────────────────────

const CATEGORY_ICONS: Record<string, React.ElementType> = {
  Function,
  Equation: Equals,
  Bug,
  Gauge,
  BookOpen,
  Atom,
  Database,
  Cpu,
  Path,
}

// ─── Paradigm filter ─────────────────────────────────────────────────────────

type FilterValue = 'all' | Paradigm

const FILTER_OPTIONS: { value: FilterValue; label: string; color: string }[] = [
  { value: 'all',     label: 'All',     color: '' },
  { value: 'static',  label: 'Static',  color: 'text-blue-600 dark:text-blue-400' },
  { value: 'dynamic', label: 'Dynamic', color: 'text-amber-600 dark:text-amber-400' },
]

/** Dot badge shown next to topic names to indicate paradigm. */
const PARADIGM_DOT: Record<Paradigm, string> = {
  static:  'bg-blue-400',
  dynamic: 'bg-amber-400',
  both:    'bg-muted-foreground/40',
}

function topicMatchesFilter(paradigm: Paradigm | undefined, filter: FilterValue): boolean {
  if (filter === 'all') return true
  const p = paradigm ?? 'both'
  return p === filter || p === 'both'
}

// ─── Component ───────────────────────────────────────────────────────────────

interface HelpSidebarProps {
  selectedTopicId: string | null
  onSelectTopic: (categoryId: string, topicId: string) => void
  /** Default-open category ids. Pass [] to close all. */
  defaultOpen?: string[]
  className?: string
}

export function HelpSidebar({
  selectedTopicId,
  onSelectTopic,
  defaultOpen,
  className,
}: HelpSidebarProps) {
  const [filter, setFilter] = useState<FilterValue>('all')
  const [appVersion, setAppVersion] = useState<string>('0.6.1')
  const [checkingUpdate, setCheckingUpdate] = useState(false)
  const openCategories = defaultOpen ?? HELP_CATEGORIES.map((c) => c.id)

  useEffect(() => {
    const updater = getUpdater()
    if (updater?.getVersion) {
      updater.getVersion().then((v) => {
        if (v) setAppVersion(v)
      }).catch(() => {})
    }

    if (updater) {
      updater.onNotAvailable?.((info) => {
        setCheckingUpdate(false)
        toast.success('You are on the latest version!', {
          description: `DSSE Workbench v${info.version || appVersion} is up to date.`
        })
      })

      updater.onAvailable?.((info) => {
        setCheckingUpdate(false)
        toast.info(`Version ${info.version} is available!`, {
          description: 'Downloading update in the background…'
        })
      })

      updater.onError?.((err) => {
        setCheckingUpdate(false)
        toast.error('Update check failed', {
          description: err.message || 'Could not verify updates.'
        })
      })
    }
  }, [appVersion])

  async function handleCheckForUpdates() {
    const updater = getUpdater()
    if (!updater?.checkForUpdates) {
      toast.info(`Version v${appVersion}`, {
        description: 'Automatic updates are managed in the packaged desktop app.'
      })
      return
    }

    setCheckingUpdate(true)
    const toastId = toast.loading('Checking for updates…')
    try {
      const res = await updater.checkForUpdates()
      if (res.status === 'dev') {
        toast.info('Development mode', {
          id: toastId,
          description: `Running v${res.version || appVersion} in dev.`
        })
        setCheckingUpdate(false)
      } else if (res.status === 'error') {
        toast.error('Update check failed', {
          id: toastId,
          description: res.message || 'Error checking for updates.'
        })
        setCheckingUpdate(false)
      } else {
        toast.dismiss(toastId)
      }
    } catch (err) {
      setCheckingUpdate(false)
      toast.error('Failed to check for updates', {
        id: toastId,
        description: String(err)
      })
    }
  }

  return (
    <div className={cn('flex h-full flex-col', className)}>
      {/* ── Paradigm filter ── */}
      <div className="shrink-0 border-b px-2 py-2">
        <div className="flex gap-1 rounded-md bg-muted/50 p-0.5">
          {FILTER_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => setFilter(opt.value)}
              className={cn(
                'flex-1 rounded px-1.5 py-1 text-[11px] font-medium transition-colors',
                filter === opt.value
                  ? 'bg-background shadow-sm ' + opt.color
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Topic tree ── */}
      <ScrollArea className="flex-1">
        <div className="p-2">
          <Accordion type="multiple" defaultValue={openCategories} className="w-full space-y-1">
            {HELP_CATEGORIES.map((category) => {
              const visibleTopics = category.topics.filter((t) =>
                topicMatchesFilter(t.paradigm, filter)
              )
              if (visibleTopics.length === 0) return null

              const Icon = CATEGORY_ICONS[category.icon] ?? BookOpen
              return (
                <AccordionItem key={category.id} value={category.id} className="border-0">
                  <AccordionTrigger className="rounded-md px-2 py-2 text-sm font-medium hover:bg-muted/60 hover:no-underline [&[data-state=open]]:text-primary">
                    <span className="flex items-center gap-2">
                      <Icon weight="duotone" className="h-4 w-4 shrink-0 text-muted-foreground" />
                      {category.label}
                      <Badge variant="secondary" className="ml-auto text-[10px] font-normal">
                        {visibleTopics.length}
                      </Badge>
                    </span>
                  </AccordionTrigger>
                  <AccordionContent className="pb-1 pt-0">
                    <ul className="ml-2 space-y-0.5 border-l pl-3">
                      {visibleTopics.map((topic) => {
                        const isActive = selectedTopicId === topic.id
                        const dot = PARADIGM_DOT[topic.paradigm ?? 'both']
                        return (
                          <li key={topic.id}>
                            <button
                              onClick={() => onSelectTopic(category.id, topic.id)}
                              className={cn(
                                'flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-xs transition-colors',
                                isActive
                                  ? 'bg-primary text-primary-foreground'
                                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
                              )}
                            >
                              <span
                                className={cn('h-1.5 w-1.5 shrink-0 rounded-full', dot)}
                                title={topic.paradigm ?? 'both'}
                              />
                              <span className="flex-1">{topic.title}</span>
                            </button>
                          </li>
                        )
                      })}
                    </ul>
                  </AccordionContent>
                </AccordionItem>
              )
            })}
          </Accordion>
        </div>
      </ScrollArea>
      {/* ── App Version & Update button ── */}
      <div className="shrink-0 border-t bg-muted/15 p-2.5">
        <div className="mb-2 flex items-center justify-between gap-1 px-0.5">
          <span className="text-[11px] font-medium text-muted-foreground truncate">DSSE Workbench</span>
          <Badge variant="outline" className="h-4 px-1.5 py-0 text-[10px] font-mono">
            v{appVersion}
          </Badge>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={checkingUpdate}
          onClick={handleCheckForUpdates}
          className="h-7 w-full justify-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          {checkingUpdate ? (
            <>
              <CircleNotch className="h-3.5 w-3.5 animate-spin text-primary" />
              <span>Checking…</span>
            </>
          ) : (
            <>
              <ArrowClockwise className="h-3.5 w-3.5" />
              <span>Check for updates</span>
            </>
          )}
        </Button>
      </div>
    </div>
  )
}
