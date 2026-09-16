/**
 * HelpTab — full Help page with:
 *   - Desktop: ResizablePanels layout (sidebar left, content right)
 *   - Mobile: Sheet drawer for sidebar triggered by a menu button
 *
 * Navigation state (selected category + topic) is managed here so that the
 * HelpSearchCommand in App.tsx can push a navigation via the onSelectTopic prop.
 */
import { useState } from 'react'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from '@/components/ui/resizable'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { List } from '@phosphor-icons/react'
import { HelpSidebar } from '@/components/HelpSidebar'
import { HelpContent } from '@/components/HelpContent'
import { useIsMobile } from '@/hooks/use-mobile'
import { HELP_CATEGORIES } from '@/lib/helpContent'

interface HelpTabProps {
  /** Called from App.tsx when search palette selects a topic. */
  selectedCategoryId?: string | null
  selectedTopicId?: string | null
  onSelectTopic?: (categoryId: string, topicId: string) => void
}

export function HelpTab({
  selectedCategoryId: externalCategoryId,
  selectedTopicId: externalTopicId,
  onSelectTopic: externalOnSelect,
}: HelpTabProps) {
  const isMobile = useIsMobile()
  const [sheetOpen, setSheetOpen] = useState(false)

  // Internal nav state — overridden by external (search palette) when provided
  const [internalCategoryId, setInternalCategoryId] = useState<string | null>(
    HELP_CATEGORIES[0]?.id ?? null
  )
  const [internalTopicId, setInternalTopicId] = useState<string | null>(
    HELP_CATEGORIES[0]?.topics[0]?.id ?? null
  )

  const activeCategoryId = externalCategoryId !== undefined ? externalCategoryId : internalCategoryId
  const activeTopicId = externalTopicId !== undefined ? externalTopicId : internalTopicId

  function handleSelectTopic(categoryId: string, topicId: string) {
    setInternalCategoryId(categoryId)
    setInternalTopicId(topicId)
    externalOnSelect?.(categoryId, topicId)
    setSheetOpen(false)
  }

  const sidebar = (
    <HelpSidebar
      selectedTopicId={activeTopicId}
      onSelectTopic={handleSelectTopic}
    />
  )

  if (isMobile) {
    return (
      <div className="flex h-[calc(100vh-104px)] flex-col">
        <div className="flex items-center gap-2 border-b px-3 py-2">
          <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" size="icon" className="h-8 w-8">
                <List className="h-4 w-4" />
                <span className="sr-only">Open topics</span>
              </Button>
            </SheetTrigger>
            <SheetContent side="left" className="w-72 p-0">
              <SheetHeader className="border-b px-4 py-3">
                <SheetTitle className="text-sm">Help Topics</SheetTitle>
              </SheetHeader>
              <div className="h-[calc(100%-52px)]">{sidebar}</div>
            </SheetContent>
          </Sheet>
          <span className="text-sm font-medium text-muted-foreground">
            {activeTopicId
              ? HELP_CATEGORIES.flatMap((c) => c.topics).find((t) => t.id === activeTopicId)?.title ?? 'Help'
              : 'Help'}
          </span>
        </div>
        <div className="flex-1 overflow-hidden">
          <HelpContent categoryId={activeCategoryId} topicId={activeTopicId} />
        </div>
      </div>
    )
  }

  return (
    <ResizablePanelGroup direction="horizontal" className="h-[calc(100vh-120px)] rounded-lg border">
      <ResizablePanel defaultSize={22} minSize={16} maxSize={35} className="bg-muted/10">
        <div className="border-b px-3 py-2.5">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Topics
          </p>
        </div>
        <div className="h-[calc(100%-41px)]">{sidebar}</div>
      </ResizablePanel>

      <ResizableHandle withHandle />

      <ResizablePanel defaultSize={78} className="bg-background">
        <HelpContent categoryId={activeCategoryId} topicId={activeTopicId} />
      </ResizablePanel>
    </ResizablePanelGroup>
  )
}
