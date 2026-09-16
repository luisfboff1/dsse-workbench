import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Copy } from '@phosphor-icons/react'
import { toCSV, toMarkdownTable, toJSON, type TableData } from '@/lib/exportData'

interface CopyDataButtonProps extends TableData {
  /** Shown in the success toast, e.g. "Bus Data" — helps tell copies apart
   *  when several tables/charts are on screen at once. */
  label: string
  className?: string
}

/** Small "Copy" dropdown for tables and charts — copies the same values
 *  shown on screen as Markdown, CSV, or JSON, so they can be pasted into a
 *  paper draft, a spreadsheet, or a script without retyping anything. */
export function CopyDataButton({ headers, rows, label, className }: CopyDataButtonProps) {
  const data: TableData = { headers, rows }

  const copy = async (format: 'markdown' | 'csv' | 'json') => {
    const text = format === 'markdown' ? toMarkdownTable(data) : format === 'csv' ? toCSV(data) : toJSON(data)
    try {
      await navigator.clipboard.writeText(text)
      toast.success(`Copied ${label} (${rows.length} row${rows.length === 1 ? '' : 's'}, ${format.toUpperCase()})`)
    } catch {
      toast.error('Copy failed — clipboard permission blocked?')
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={rows.length === 0}
          className={`h-6 gap-1 text-xs text-muted-foreground ${className ?? ''}`}
          title={`Copy ${label}`}
        >
          <Copy className="w-3.5 h-3.5" /> Copy
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        <DropdownMenuItem onClick={() => copy('markdown')}>Copy as Markdown</DropdownMenuItem>
        <DropdownMenuItem onClick={() => copy('csv')}>Copy as CSV</DropdownMenuItem>
        <DropdownMenuItem onClick={() => copy('json')}>Copy as JSON</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
