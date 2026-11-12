// Folds the gallery build (`vite build --mode galeria`) into one self-contained
// dist-galeria/galeria.html: Chrome refuses <script type="module" src> from
// file://, but runs an inline module script fine. Fonts/images are already
// data: URIs (assetsInlineLimit in vite.config.ts), so only JS and CSS remain.
import { readFileSync, writeFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'

const dir = 'dist-galeria'
const html = join(dir, 'galeria.html')
const embutidos = []
const ler = (href) => { embutidos.push(href); return readFileSync(join(dir, href), 'utf8') }

// Replacement *functions*, not strings: the bundle is full of `$&`/`$1`-like
// sequences that String.replace would otherwise expand.
const saida = readFileSync(html, 'utf8')
  .replace(/<script type="module" crossorigin src="([^"]+)"><\/script>/g,
    (_, src) => `<script type="module">${ler(src).replaceAll('</script', '<\\/script')}</script>`)
  .replace(/<link rel="stylesheet" crossorigin href="([^"]+)">/g,
    (_, href) => `<style>${ler(href)}</style>`)

if (/src="\.\/assets|href="\.\/assets/.test(saida)) {
  throw new Error('galeria.html still references ./assets: Vite changed its tag format, update the regexes')
}
writeFileSync(html, saida)
// Only what was folded in: the maplibre worker stays in assets/ (map view only;
// Chrome won't start a worker from file:// anyway, and the map needs internet tiles).
for (const f of embutidos) rmSync(join(dir, f))
console.log(`${html}: ${(saida.length / 1e6).toFixed(1)} MB, standalone`)
