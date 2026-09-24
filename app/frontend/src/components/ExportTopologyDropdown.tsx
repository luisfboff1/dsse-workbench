import { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Export, FileCsv, FileJs, Table, CircleNotch } from '@phosphor-icons/react'
import { toast } from 'sonner'
import { type ExportFormat, getExportFormats, exportTopology } from '@/lib/api'
import type { Topology } from '@/lib/types'

interface ExportTopologyDropdownProps {
  topology: Topology
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export function ExportTopologyDropdown({ topology }: ExportTopologyDropdownProps) {
  const [formats, setFormats] = useState<ExportFormat[]>([])
  const [exportingFormatId, setExportingFormatId] = useState<string | null>(null)

  useEffect(() => {
    getExportFormats().then(setFormats).catch(e => console.error("Failed to fetch export formats", e))
  }, [])

  const handleExport = async (format: ExportFormat) => {
    setExportingFormatId(format.id)
    try {
      const blob = await exportTopology(topology, format.id)
      downloadBlob(blob, `${topology.name || 'topology'}${format.extension}`)
      toast.success(`Exported as ${format.name}`)
    } catch (err: any) {
      toast.error(`Export failed: ${err.message}`)
    } finally {
      setExportingFormatId(null)
    }
  }

  const getFormatIcon = (formatId: string) => {
    if (formatId.includes('json')) return <FileJs className="mr-2" />
    if (formatId.includes('csv')) return <FileCsv className="mr-2" />
    if (formatId.includes('xlsx')) return <Table className="mr-2" />
    return <Export className="mr-2" />
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline" size="icon" title="Export Topology">
          <Export size={16} />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {formats.length === 0 ? (
          <DropdownMenuItem disabled>Loading formats...</DropdownMenuItem>
        ) : (
          formats.map(format => (
            <DropdownMenuItem 
              key={format.id} 
              onClick={() => handleExport(format)}
              disabled={exportingFormatId !== null}
            >
              {exportingFormatId === format.id ? (
                <CircleNotch className="mr-2 animate-spin" />
              ) : (
                getFormatIcon(format.id)
              )}
              {format.name}
            </DropdownMenuItem>
          ))
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
