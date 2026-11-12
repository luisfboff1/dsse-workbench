import type { ReactNode } from 'react'
import { Lightning, Trash } from '@phosphor-icons/react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog'

const VARIANTES = ['default', 'secondary', 'outline', 'ghost', 'destructive', 'link'] as const
const TAMANHOS = ['sm', 'default', 'lg'] as const

export function Grupo({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <div>
      <h3 className="mb-3 text-sm font-semibold text-muted-foreground">{titulo}</h3>
      {children}
    </div>
  )
}

export function Primitivos() {
  return (
    <TooltipProvider>
      <div className="space-y-10">
        <Grupo titulo="Button: variantes × tamanhos">
          <div className="space-y-3">
            {TAMANHOS.map(size => (
              <div key={size} className="flex flex-wrap items-center gap-3">
                <span className="mono w-16 text-xs text-muted-foreground">{size}</span>
                {VARIANTES.map(variant => (
                  <Button key={variant} variant={variant} size={size}>{variant}</Button>
                ))}
              </div>
            ))}
            <div className="flex flex-wrap items-center gap-3">
              <span className="mono w-16 text-xs text-muted-foreground">estados</span>
              <Button disabled>disabled</Button>
              <Button><Lightning /> com ícone</Button>
              <Button size="icon" variant="outline" aria-label="apagar"><Trash /></Button>
            </div>
          </div>
        </Grupo>

        <Grupo titulo="Badge">
          <div className="flex flex-wrap gap-2">
            <Badge>default</Badge>
            <Badge variant="secondary">secondary</Badge>
            <Badge variant="outline">outline</Badge>
            <Badge variant="destructive">destructive</Badge>
            <Badge className="bg-method-ac text-white">AC</Badge>
            <Badge className="bg-method-dc text-white">DC</Badge>
            <Badge className="bg-method-ldf text-white">LinDistFlow</Badge>
          </div>
        </Grupo>

        <Grupo titulo="Formulário">
          <div className="grid max-w-md gap-4">
            <div className="grid gap-1.5">
              <Label htmlFor="g-tol">Tolerância</Label>
              <Input id="g-tol" defaultValue="1e-6" className="mono" />
            </div>
            <Input placeholder="placeholder" />
            <Input disabled value="disabled" readOnly />
            <Input aria-invalid defaultValue="valor inválido" />
            <div className="flex items-center gap-2">
              <Checkbox id="g-chk" defaultChecked />
              <Label htmlFor="g-chk">Checkbox</Label>
            </div>
            <div className="flex items-center gap-2">
              <Switch id="g-sw" defaultChecked />
              <Label htmlFor="g-sw">Switch</Label>
            </div>
          </div>
        </Grupo>

        <Grupo titulo="Tabs">
          <Tabs defaultValue="ac" className="max-w-md">
            <TabsList>
              <TabsTrigger value="ac">AC</TabsTrigger>
              <TabsTrigger value="dc">DC</TabsTrigger>
              <TabsTrigger value="ldf">LinDistFlow</TabsTrigger>
            </TabsList>
            <TabsContent value="ac" className="text-sm">Conteúdo da aba AC.</TabsContent>
            <TabsContent value="dc" className="text-sm">Conteúdo da aba DC.</TabsContent>
            <TabsContent value="ldf" className="text-sm">Conteúdo da aba LinDistFlow.</TabsContent>
          </Tabs>
        </Grupo>

        <Grupo titulo="Tooltip e Dialog">
          <div className="flex gap-3">
            <Tooltip>
              <TooltipTrigger asChild><Button variant="outline">Passe o mouse</Button></TooltipTrigger>
              <TooltipContent>Texto do tooltip</TooltipContent>
            </Tooltip>
            <Dialog>
              <DialogTrigger asChild><Button variant="outline">Abrir dialog</Button></DialogTrigger>
              <DialogContent>
                <DialogHeader>
                  <DialogTitle>Título do dialog</DialogTitle>
                  <DialogDescription>Descrição curta do que o dialog faz.</DialogDescription>
                </DialogHeader>
                <DialogFooter>
                  <Button variant="outline">Cancelar</Button>
                  <Button>Confirmar</Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        </Grupo>
      </div>
    </TooltipProvider>
  )
}
