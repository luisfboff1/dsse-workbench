/**
 * Global help search palette — triggered by Ctrl/Cmd+K from the header.
 * Uses the cmdk Command primitive (already installed via shadcn/ui).
 */
import { useEffect, useState } from 'react'
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Badge } from '@/components/ui/badge'
import { HELP_CATEGORIES, searchHelp, buildHelpIndex } from '@/lib/helpContent'
import type { HelpTopicFlat } from '@/lib/helpContent'

interface HelpSearchCommandProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Called when the user selects a result — navigate to that topic. */
  onSelectTopic: (categoryId: string, topicId: string) => void
}

export function HelpSearchCommand({ open, onOpenChange, onSelectTopic }: HelpSearchCommandProps) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<HelpTopicFlat[]>([])

  // Reset query when closed
  useEffect(() => {
    if (!open) setQuery('')
  }, [open])

  // Update results on query change
  useEffect(() => {
    if (query.trim()) {
      setResults(searchHelp(query))
    } else {
      // Show first topic from each category when no query
      setResults(buildHelpIndex().slice(0, 10))
    }
  }, [query])

  // Group results by category for display
  const grouped = HELP_CATEGORIES.map((cat) => ({
    category: cat,
    items: results.filter((r) => r.categoryId === cat.id),
  })).filter((g) => g.items.length > 0)

  function handleSelect(item: HelpTopicFlat) {
    onOpenChange(false)
    onSelectTopic(item.categoryId, item.topic.id)
  }

  return (
    <CommandDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Help Search"
      description="Search documentation topics, equations, and glossary entries"
    >
      <CommandInput
        placeholder="Search help topics, equations, glossary…"
        value={query}
        onValueChange={setQuery}
      />
      <CommandList className="max-h-[400px]">
        {grouped.length === 0 && (
          <CommandEmpty>No results for "{query}"</CommandEmpty>
        )}
        {grouped.map(({ category, items }) => (
          <CommandGroup key={category.id} heading={category.label}>
            {items.map(({ topic }) => (
              <CommandItem
                key={topic.id}
                value={`${category.label} ${topic.title} ${topic.tagline}`}
                onSelect={() => handleSelect({ categoryId: category.id, categoryLabel: category.label, topic })}
                className="flex items-start gap-2 py-2"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{topic.title}</p>
                  <p className="truncate text-xs text-muted-foreground">{topic.tagline}</p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <Badge variant="outline" className="text-[10px]">
                    {category.label}
                  </Badge>
                  {topic.paradigm && topic.paradigm !== 'both' && (
                    <Badge
                      variant="secondary"
                      className={`text-[9px] ${topic.paradigm === 'dynamic' ? 'border-amber-400/40 bg-amber-400/10 text-amber-700 dark:text-amber-400' : 'border-blue-400/40 bg-blue-400/10 text-blue-700 dark:text-blue-400'}`}
                    >
                      {topic.paradigm}
                    </Badge>
                  )}
                </div>
              </CommandItem>
            ))}
          </CommandGroup>
        ))}
      </CommandList>
    </CommandDialog>
  )
}
