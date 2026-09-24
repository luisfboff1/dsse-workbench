import { useState, useCallback, useRef, useEffect } from 'react'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Upload, FileArrowUp, DownloadSimple, Warning, CheckCircle, Info } from '@phosphor-icons/react'
import { toast } from 'sonner'
import { type ImportFormat, getImportFormats, importTopology, downloadCsvTemplate } from '@/lib/api'
import type { Topology } from '@/lib/types'

interface ImportTopologyDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onImport: (topology: Topology) => void
}

export function ImportTopologyDialog({ open, onOpenChange, onImport }: ImportTopologyDialogProps) {
  const [formats, setFormats] = useState<ImportFormat[]>([])
  const [file, setFile] = useState<File | null>(null)
  const [extraFiles, setExtraFiles] = useState<File[]>([])
  const [loading, setLoading] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  
  const fileInputRef = useRef<HTMLInputElement>(null)
  
  useEffect(() => {
    if (open && formats.length === 0) {
      getImportFormats().then(setFormats).catch(e => console.error("Failed to fetch formats", e))
    }
  }, [open, formats.length])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(Array.from(e.dataTransfer.files))
    }
  }, [])

  const handleFileChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFiles(Array.from(e.target.files))
    }
  }, [])

  const handleFiles = (files: File[]) => {
    // If multiple files, consider the first as main and rest as extra
    if (files.length > 0) {
      setFile(files[0])
      setExtraFiles(files.slice(1))
    }
  }

  const handleImport = async () => {
    if (!file) return
    setLoading(true)
    try {
      const topo = await importTopology(file, extraFiles.length > 0 ? extraFiles : undefined)
      
      if (topo.meta?.warnings && topo.meta.warnings.length > 0) {
        topo.meta.warnings.forEach(w => toast.warning(`Warning: ${w}`))
      }
      if (topo.meta?.size_warning === 'large') {
        toast.info("Large network imported — UI may be slower")
      } else if (topo.meta?.size_warning === 'very_large') {
        toast.warning("Very large network — diagram disabled by default")
      }
      
      onImport(topo)
      onOpenChange(false)
      setFile(null)
      setExtraFiles([])
    } catch (err: any) {
      toast.error(`Import failed: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }

  const handleDownloadTemplate = async () => {
    try {
      const blob = await downloadCsvTemplate()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'workbench_template.zip'
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err: any) {
      toast.error(`Failed to download template: ${err.message}`)
    }
  }

  const clearSelection = () => {
    setFile(null)
    setExtraFiles([])
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[500px]">
        <DialogHeader>
          <DialogTitle>Import Topology</DialogTitle>
          <DialogDescription>
            Upload a topology file to load it into the Workbench.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-4">
          {!file ? (
            <div 
              className={`border-2 border-dashed rounded-lg p-8 flex flex-col items-center justify-center gap-2 cursor-pointer transition-colors ${isDragging ? 'border-primary bg-primary/10' : 'border-muted-foreground/25 hover:bg-muted/50'}`}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload size={32} className="text-muted-foreground mb-2" />
              <p className="text-sm font-medium text-center">Click or drag and drop files here</p>
              <p className="text-xs text-muted-foreground text-center">
                Supports {formats.flatMap(f => f.extensions).join(', ') || 'various formats'}
              </p>
              <p className="text-xs text-muted-foreground text-center mt-2">
                For multiple files (e.g. OpenDSS or CSV), drag all files together or use a .zip
              </p>
            </div>
          ) : (
            <div className="bg-muted p-4 rounded-lg flex items-center justify-between">
              <div className="flex items-center gap-3">
                <FileArrowUp size={24} className="text-primary" />
                <div>
                  <p className="text-sm font-medium">{file.name}</p>
                  {extraFiles.length > 0 && (
                    <p className="text-xs text-muted-foreground">
                      + {extraFiles.length} additional file(s)
                    </p>
                  )}
                </div>
              </div>
              <Button variant="ghost" size="sm" onClick={clearSelection}>Clear</Button>
            </div>
          )}

          <input 
            type="file" 
            className="hidden" 
            ref={fileInputRef} 
            onChange={handleFileChange}
            multiple 
          />

          <div className="flex justify-between items-center mt-2">
            <Button variant="outline" size="sm" onClick={handleDownloadTemplate}>
              <DownloadSimple className="mr-2" /> CSV Template
            </Button>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={loading}>
            Cancel
          </Button>
          <Button onClick={handleImport} disabled={!file || loading}>
            {loading ? "Importing..." : "Import"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
