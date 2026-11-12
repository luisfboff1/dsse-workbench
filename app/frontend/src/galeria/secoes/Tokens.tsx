import { useState } from 'react'

type Token = { nome: string; valor: string }

/** Reads the custom properties declared on plain `:root` rules of index.css,
 *  straight from the loaded stylesheets, so the gallery can never drift from
 *  the CSS. Tailwind's own theme block is emitted as `:root, :host` and is
 *  skipped on purpose (it only re-maps these same tokens). */
function lerTokensRoot(): Token[] {
  const tokens: Token[] = []
  const visitar = (regras: CSSRuleList) => {
    for (const regra of Array.from(regras)) {
      if (regra instanceof CSSStyleRule && regra.selectorText === ':root') {
        for (const prop of Array.from(regra.style)) {
          if (prop.startsWith('--')) {
            tokens.push({ nome: prop, valor: regra.style.getPropertyValue(prop).trim() })
          }
        }
      } else if ('cssRules' in regra) {
        visitar((regra as CSSGroupingRule).cssRules)
      }
    }
  }
  for (const folha of Array.from(document.styleSheets)) {
    try {
      visitar(folha.cssRules)
    } catch {
      // Cross-origin sheet (Google Fonts): its rules are not readable.
    }
  }
  return tokens
}

const ehCor = (v: string) => /^(oklch|rgb|hsl|#)/.test(v)

const TEXTOS = ['text-xs', 'text-sm', 'text-base', 'text-lg', 'text-xl', 'text-2xl', 'text-3xl']
const ESPACOS = [1, 2, 3, 4, 6, 8, 12, 16]

export function Tokens() {
  // index.css is imported in main.tsx before render, so the sheets are ready here.
  const [tokens] = useState(lerTokensRoot)

  const cores = tokens.filter(t => ehCor(t.valor))
  const outros = tokens.filter(t => !ehCor(t.valor))

  return (
    <div className="space-y-10">
      <div>
        <h3 className="mb-3 text-sm font-semibold text-muted-foreground">Cores ({cores.length})</h3>
        <div className="grid grid-cols-[repeat(auto-fill,minmax(13rem,1fr))] gap-3">
          {cores.map(t => (
            <div key={t.nome} className="overflow-hidden rounded-md border bg-card">
              <div className="h-14 border-b" style={{ background: `var(${t.nome})` }} />
              <div className="p-2">
                <div className="mono text-xs font-medium">{t.nome}</div>
                <div className="mono text-xs text-muted-foreground">{t.valor}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {outros.length > 0 && (
        <div>
          <h3 className="mb-3 text-sm font-semibold text-muted-foreground">Outros tokens</h3>
          <div className="flex flex-wrap gap-3">
            {outros.map(t => (
              <div key={t.nome} className="rounded-md border bg-card p-3">
                <div className="mono text-xs font-medium">{t.nome}</div>
                <div className="mono text-xs text-muted-foreground">{t.valor}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div>
        <h3 className="mb-3 text-sm font-semibold text-muted-foreground">Raios</h3>
        <div className="flex flex-wrap gap-4">
          {['rounded-sm', 'rounded-md', 'rounded-lg', 'rounded-xl', 'rounded-2xl'].map(r => (
            <div key={r} className="text-center">
              <div className={`size-16 border-2 border-primary bg-muted ${r}`} />
              <div className="mono mt-1 text-xs">{r}</div>
            </div>
          ))}
        </div>
      </div>

      <div>
        <h3 className="mb-3 text-sm font-semibold text-muted-foreground">
          Tipografia (base 14px, Inter no corpo, JetBrains Mono em títulos e .mono)
        </h3>
        <div className="space-y-2">
          {TEXTOS.map(t => (
            <div key={t} className="flex items-baseline gap-4">
              <span className="mono w-20 shrink-0 text-xs text-muted-foreground">{t}</span>
              <span className={t}>Estimação de estado em redes de distribuição</span>
            </div>
          ))}
          <div className="flex items-baseline gap-4">
            <span className="mono w-20 shrink-0 text-xs text-muted-foreground">.mono</span>
            <span className="mono">V = 1.0234 pu ∠ -2.15°</span>
          </div>
        </div>
      </div>

      <div>
        <h3 className="mb-3 text-sm font-semibold text-muted-foreground">Espaçamento (1 unidade = 0.25rem = 3.5px)</h3>
        <div className="space-y-1">
          {ESPACOS.map(n => (
            <div key={n} className="flex items-center gap-4">
              <span className="mono w-20 shrink-0 text-xs text-muted-foreground">{n}</span>
              <div className="h-3 rounded-sm bg-accent" style={{ width: `calc(var(--spacing) * ${n})` }} />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
