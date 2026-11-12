import { Toaster } from '@/components/ui/sonner'
import { Tokens } from './secoes/Tokens'
import { Primitivos } from './secoes/Primitivos'
import { Componentes } from './secoes/Componentes'
import { Diagrama } from './secoes/Diagrama'
import { Temporal } from './secoes/Temporal'

/** Sections in menu order. Add new ones here (see docs/galeria/plano_galeria.md). */
const SECOES = [
  { id: 'tokens', titulo: 'Tokens', Componente: Tokens },
  { id: 'primitivos', titulo: 'Primitivos (ui/)', Componente: Primitivos },
  { id: 'componentes', titulo: 'Componentes do app', Componente: Componentes },
  { id: 'diagrama', titulo: 'Diagrama de rede', Componente: Diagrama },
  { id: 'temporal', titulo: 'Replay temporal', Componente: Temporal },
]

export function Galeria() {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <nav className="sticky top-0 h-screen w-48 shrink-0 border-r bg-card p-4">
        <h1 className="mb-4 text-sm font-semibold">Galeria</h1>
        <ul className="space-y-1 text-sm">
          {SECOES.map(s => (
            <li key={s.id}>
              <a href={`#${s.id}`} className="block rounded-md px-2 py-1 hover:bg-muted">
                {s.titulo}
              </a>
            </li>
          ))}
        </ul>
      </nav>
      <main className="min-w-0 flex-1 space-y-12 p-8">
        {SECOES.map(({ id, titulo, Componente }) => (
          <section key={id} id={id} className="scroll-mt-8">
            <h2 className="mb-6 border-b pb-2 text-xl font-semibold">{titulo}</h2>
            <Componente />
          </section>
        ))}
      </main>
      <Toaster />
    </div>
  )
}
