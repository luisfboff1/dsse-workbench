# DSSE Simulation Workbench — Design System

This app is already built on **shadcn/ui + Tailwind CSS v4 + Radix primitives +
Recharts**. There is no decision to make here — `components.json` (shadcn CLI
config), every file under `src/components/ui/`, and the CSS-variable theme in
`src/index.css` are the standard shadcn setup. `src/components/ui/chart.tsx`
is shadcn's own Recharts wrapper.

What follows is the convention for **colors specifically** — the one thing
that had drifted into hardcoded Tailwind palette classes (`text-blue-600`,
`fill="oklch(0.60 0.20 240)"`, raw hex strings) scattered across components.
That drift is fixed as of 2026-07-02; this doc is how it stays fixed.

## The rule

**Never write a raw color in a component file.** Not `oklch(...)`, not a hex
string, not a Tailwind palette class like `text-red-500` or `bg-orange-400`.
If you need a color, it already exists as a token in `src/index.css` — use
that. If it genuinely doesn't exist yet, add it to `index.css` first (one
place), then reference it everywhere (many places).

The payoff: retuning any color — say, making the "DC" identity color a
slightly different blue — is a one-line edit in `index.css`. Today it would
have meant hunting through five component files.

## Language

**Everything user-facing in this app is English** — labels, tooltips, chart
axes, and every error string the backend sends back (`HTTPException.detail`,
`ValueError` messages raised inside `src/tese_dsse/powerflow/`). This is
independent of the fact that Luis and Claude talk to each other in
Portuguese in chat, and that the thesis's research notebooks and docs are
Portuguese by project convention (see `.claude/CLAUDE.md`) — those are two
different audiences. The app's UI is English throughout, so an error raised
by a backend route and surfaced in a frontend `<Alert>` has to be English too,
or it reads as a bug even when it's working as intended.

As of 2026-07-02 this holds for every string in `app/backend/routes/*.py`
and `src/tese_dsse/powerflow/lindistflow.py`. It does **not** yet hold for
the older estimation library (`src/tese_dsse/estimacao_estado/*.py` —
`gauss_newton_wls.py`, `dc_linear.py`, `bad_data.py`, `ac_measurements.py`),
which still raises Portuguese `ValueError`s. That library is shared with the
research notebooks (Portuguese context), so translating it isn't a
find-and-replace — decide case by case whether a given error can actually
surface in the app (via `estimation.py`/`baddata.py`) before translating it.

## How the token system works

Three layers, in `src/index.css`:

```css
:root {
  --status-good: oklch(0.60 0.145 152);   /* 1. raw value, one definition */
}

@theme {
  --color-status-good: var(--status-good); /* 2. exposed to Tailwind's engine */
}
```

```tsx
<span className="text-status-good" />        // 3a. Tailwind utility class
<Bar fill="var(--color-status-good)" />       // 3b. anywhere CSS accepts a string
```

Tailwind v4 turns every `--color-*` entry in `@theme` into utility classes
(`text-status-good`, `bg-status-good`, `border-status-good`, and opacity
modifiers like `bg-status-good/10` all work automatically). The same
`--color-*` variable is also a real CSS custom property at runtime, so it
resolves inside inline `style={{ color: 'var(--color-status-good)' }}`,
Recharts `fill`/`stroke` props, and D3 `.attr('fill', ...)` calls — anywhere
a browser expects a CSS color string.

## The token palette

### Method identity — which solver produced this data

| Token | Hue | Used for |
|---|---|---|
| `method-ac` | emerald | AC / Newton-Raphson (pandapower) — the ground truth |
| `method-dc` | blue | DC linear power flow |
| `method-ldf` | violet | DistFlow / LinDistFlow |

These are defined once in [`src/lib/methodInfo.ts`](src/lib/methodInfo.ts)
alongside the equations/description for each solver (see below), so a chart
series, a table header, and the "how does this work" popover all agree on
which color means which method.

**Reuse rule:** if a chart needs a second neutral data series that has
nothing to do with AC/DC/LinDist (e.g. "clean" vs "flagged" measurements in
the bad-data tab), it's fine to borrow `method-dc` (blue) or `method-ldf`
(violet) for that series rather than inventing a new token — see
`BadDataAnalyticsTab.tsx`'s `fillCME` for an example. Keep the palette small.

### Status — generic state, independent of which method produced it

| Token | Hue | Used for |
|---|---|---|
| `status-good` | green | converged / passed / in range / detected & fixed |
| `status-warn` | amber | flagged / medium risk / attention |
| `status-info` | blue-gray | informational / low risk / under a limit |

Plus the shadcn-standard `destructive` token (red) for failures, out-of-range
values, and high-risk/undetected bad data — already themed, don't reintroduce
a separate "error red."

### Everything else (already themed, pre-existing)

`background`, `foreground`, `card`, `popover`, `primary`, `secondary`,
`muted`, `accent`, `border`, `input`, `ring` — the standard shadcn set. Don't
touch these for feature-specific coloring; they're structural (page
background, card surfaces, focus rings), not semantic to power-flow data.

## Adding a new component with charts/tables

1. Reach for `src/components/ui/table.tsx`, `chart.tsx`, `select.tsx`, etc.
   first — don't hand-roll a table or a Select from scratch.
2. For any color, use a token from the palette above via a Tailwind class
   (`text-status-good`) or `var(--color-*)` inside Recharts/D3 props.
3. If the color is conditional on data (e.g. "red if error > threshold"),
   keep the ternary but make every branch return a token, never a literal:
   ```tsx
   // yes
   className={err > 1 ? 'text-destructive' : 'text-status-good'}
   // no
   className={err > 1 ? 'text-red-500' : 'text-green-600'}
   ```
4. If you're building a small multi-tier risk/severity indicator (like the
   K_ii masking-risk tiers in Bad Data), reuse the
   `status-info → status-warn → destructive` progression rather than
   inventing a fourth color.

## The MethodInfo pattern — reusable "how does this work" content

[`src/lib/methodInfo.ts`](src/lib/methodInfo.ts) holds one `MethodInfo`
record per solver: label, tagline, state vector, equations, algorithm steps,
when to use it, and its limitations. [`src/components/MethodInfo.tsx`](src/components/MethodInfo.tsx)
splits rendering into two pieces on purpose:

- `MethodInfoContent` — the pure content, no popover chrome. This is what a
  future **Help tab** should render directly on a page.
- `MethodInfoBadge` — today's usage: a `Button variant="ghost" size="icon"`
  (shadcn, not a hand-rolled `<button>`) that opens `MethodInfoContent` inside
  a `HoverCard` next to the method Select in Power Flow.

Equations are real LaTeX, rendered with **KaTeX** via the thin wrappers in
[`src/components/Math.tsx`](src/components/Math.tsx) (`InlineMath`,
`BlockMath` — call `katex.renderToString` directly instead of pulling in
`react-katex`, to avoid its inconsistent type declarations). The algorithm
step list renders as an actual flowchart via
[`src/components/StepFlowchart.tsx`](src/components/StepFlowchart.tsx) — a
small hand-drawn SVG (boxes + arrows + an optional dashed loop-back path),
not mermaid.js. Reasoning: every algorithm in this app is a simple linear
step chain with at most one "repeat until converged" loop, so a ~100-line SVG
component stays fully driven by our own theme tokens and avoids a
multi-hundred-KB graph-rendering runtime with its own separate theming system.

When another domain needs the same "hover for an explainer, same content
reusable in a help page" pattern (e.g. explaining the bad-data detection
pipelines), follow this split: one data file with the plain-text content, one
component that renders it either inline or wrapped in a trigger.

## Radial vs. meshed detection — another single-source-of-truth utility

[`src/lib/networkTopology.ts`](src/lib/networkTopology.ts) exports
`checkRadial(topology)`, which classifies a topology as `'radial'`,
`'meshed'`, or `'disconnected'` from a simple edge count (`nLines` vs.
`nBuses - 1`). It mirrors the backend's real structural check in
`lindistflow.py::_build_tree` (which additionally verifies BFS reachability —
the frontend version is a cheap UI hint, not a substitute for the backend's
validation, which is what actually decides whether a DistFlow run
succeeds).

**Gotcha this exists to prevent:** [pandapower](docs/simulacao/pandapower.md) keeps out-of-service elements
(`in_service=False`) in the same DataFrame as active ones — `net.line`,
`net.bus`, `net.gen`, `net.load`, `net.ext_grid`, `net.trafo` all carry the
column. `case33bw` (the classic reconfigurable radial feeder) ships with 5 of
its 37 lines marked out-of-service — those are the tie-switches, meant to
stay open in normal operation. `load_pandapower_case()` in `topology.py`
filters every one of those tables to `in_service == True` before building the
topology; without that filter, `checkRadial()` would see 37 lines for 33
buses and wrongly report a genuinely radial feeder as meshed. `sgen` is
filtered the same way (see "sgen" below) — when adding support for any other
new pandapower table, filter it the same way before iterating.

The filtered-out lines/transformers aren't just dropped, though: they're
returned separately as `Topology.openSwitches` (id/from/to/name, no R/X — not
part of the electrical model) and `TopologyDiagram.tsx` draws them as dashed
gray edges, so the diagram still shows they physically exist without feeding
them into the power flow or the radial check.

**Second gotcha, same root cause:** `in_service=False` isn't the only way
pandapower marks something open. `net.switch` (columns `bus`, `element`,
`et`, `closed`) attaches a switch to *one specific end* of a line or
transformer — `create_cigre_network_mv`, `mv_oberrhein`, and
`simple_mv_open_ring_net` (all real/benchmark **MV** distribution feeders,
not the LV ones below) represent their normally-open tie points this way and
never touch `in_service` at all. `load_pandapower_case()` reads
`net.switch`, builds `line_switch_open`/`trafo_switch_open` index sets from
rows where `closed == False` and `et in ("l", "t")`, and excludes those
branches the same way as `in_service=False` ones (and folds them into the
same `openSwitches` output). `et == "b"` (bus-bus coupler switches) is
**not** handled — those don't map onto a line/trafo at all, they'd require
merging two bus objects into one electrical node when closed, a bigger
structural change. `example_multivoltage` is the only tested network with an
open bus-bus switch, so this is a known, contained gap for now.

**Case census (as of 2026-07-02), `_pp_case_names()` now includes a curated
`_EXTRA_PP_NETWORKS` list** on top of the auto-discovered `case*` functions
(pandapower.networks also exports generic element builders like
`create_bus`/`create_line` that aren't network generators, so this list is
hand-picked, not introspected). Of 60 total cases, **26 are radial**; of
those, only 3 are genuine **MV** distribution networks (`case33bw`,
`create_cigre_network_mv`, `simple_mv_open_ring_net`) — the other 23 radial
ones are all **LV** (mostly the German Kerber/`kb_extrem_*` family). Every
other pandapower.networks case is a transmission benchmark (IEEE 9/14/30/57/
118/300-bus, the RTE/pegase/GB cases), meshed by design for N-1 reliability
— DistFlow correctly rejects all of them. `mv_oberrhein` (a real German MV
network) currently reports "too sparse" (177 lines for 178 expected buses) —
one bus short of connected, root cause not yet found; worth revisiting since
it's the most realistic of the three MV candidates.

Both `TopologyTab` (badge next to the topology name, shown right when a
network loads) and `PowerFlowTab` (the "radial: DistFlow recommended" /
"meshed: DistFlow will fail" badge above the solver) call this same function
— don't recompute `topology.lines.length > topology.buses.length - 1` inline
in a third place. If the classification logic ever needs to change (e.g. to
also flag disconnected islands via a real graph traversal instead of just an
edge count), fixing it once in `networkTopology.ts` fixes it everywhere it's
displayed.

## UI density, table conventions, and diagram stability (2026-07-19)

Luis reported the app reading as oversized/cramped and asked for a "copy
table data" feature and a Network Diagram fix — three related passes landed
the same day:

**Density.** `html { font-size }` in `index.css` was flat 18px (raised
2026-07-02), then briefly made responsive (16/17/18px by breakpoint), then
dropped to a **flat 14px** — matching the density of `financeiro`
(the other dashboard-style app in this workspace, `financeiro/app/globals.css`),
which uses the same Tailwind-v4-rem-off-root-font-size mechanism. Since
Tailwind v4's `text-*`/`spacing-*` scales are both rem-based off this one
value, it scales type AND padding/gaps together — the single highest-leverage
lever for "everything feels big."

Second contributor: the `.mono` (JetBrains Mono) class was applied far more
widely than data actually needed — 302 occurrences across 15 files, most
legitimately on numeric table columns (alignment benefits from a fixed-width
face) but also on `CardTitle`, `TabsTrigger` labels, nav chrome, and button
labels, where it was purely decorative and JetBrains Mono is measurably wider
per character than Inter at the same size. Removed `.mono`/`font-mono` from
every card title, tab label, and toolbar button across all six tab
components; kept it only on table headers/cells, variable identifiers, and
method/algorithm badges — anywhere alignment or a "technical identifier"
reading is the actual reason for a monospace face.

**TableCard — one shared table shell.** All 16 `<Table>` usages across the
app (Topology, Measurements, Power Flow ×3, State Estimation ×2, Bad Data
×5, Workbench ×3) now go through
[`src/components/TableCard.tsx`](src/components/TableCard.tsx) instead of a
bespoke `<div className="border rounded-md overflow-x-auto"><Table>...`
wrapper per table. It gets Copy (Markdown/CSV/JSON, via
[`src/lib/exportData.ts`](src/lib/exportData.ts)) and an Expand/Collapse
toggle (pass `maxHeight`, e.g. `"16rem"`, on any table whose row count grows
with problem size — omit it on small/fixed-row tables like the 8-row
pipeline comparison) for free. Copy reads the **rendered DOM cells** back out
at click time (`<input>` cells read `.value`, everything else reads
`.textContent`) rather than needing a hand-built `headers`/`rows` array per
table — so what's copied always matches what's on screen, and a new table
gets both features just by wrapping in `<TableCard label="...">`. Charts
(recharts, not a `<table>`) can't be DOM-scraped, so they use the smaller
[`src/components/CopyDataButton.tsx`](src/components/CopyDataButton.tsx)
directly with an explicit array — see the two chart copy buttons in
`MeasurementsSummaryCard.tsx` for the pattern. The editable numeric-input
auto-sizing style (`field-sizing: content` + `min-w`/`max-w`, fixes
long values like `-0.00712` getting clipped in a fixed-width box) also moved
out of `TopologyTab.tsx` into `NUM_INPUT_CLASS` in
[`src/lib/utils.ts`](src/lib/utils.ts) so the next editable table reuses it
instead of redefining it.

**TopologyDiagram stability.** Two related fixes in
[`TopologyDiagram.tsx`](src/components/TopologyDiagram.tsx):

- Node radii shrunk (slack 30→22, PV 25→18, PQ 20→15, badges/labels scaled to
  match) and the `fitToView()` auto-zoom cap lowered from 2.5x to 1.5x — a
  small topology (few buses, tight force-simulation cluster) has a small
  bounding box, so the old cap just blew nodes up to fill whatever panel
  width was available.
- **Meter toggles no longer reset pan/zoom or reshuffle node positions.**
  The main draw `useEffect` always fully wipes and rebuilds the SVG
  (`svg.selectAll('*').remove()`), and its dependency array includes the
  whole `topology` object — so assigning/changing a meter (which only
  touches `topology.measurements`/`line_measurements`) used to trigger the
  same full rebuild as adding a bus, including `fitToView()` and a fresh
  (non-geo) force simulation starting nodes from scratch. Fixed with two
  refs: `structureKeyRef` holds a JSON signature of bus/line/switch ids +
  geo coords + panel dimensions + view mode/orientation — `fitToView()` now
  only fires when that signature actually changes, not on every redraw.
  `positionsRef` carries the last-settled `{x, y}` per bus id across
  redraws (updated every simulation tick) and seeds new (non-geo) nodes'
  starting position from it instead of leaving `x`/`y` undefined — so the
  simulation resumes near equilibrium instead of restarting from a fresh
  layout. Geo-coordinate topologies were never affected (their `fx`/`fy` are
  already pinned deterministically from `bus.geoX`/`geoY` every render).
- Also added: a "Meters" toggle button opening a side panel
  (`metersPanelOpen` state) listing every bus/line with its assigned meter
  kind — each row is a `Popover`-wrapped button reusing the same
  `MeterKindMenu` component the diagram's click-to-assign popovers use
  (extracted so both call sites share one implementation), so meters can be
  edited from the list instead of only by clicking the diagram directly.
  Rows render as plain (non-clickable) text when the diagram is read-only
  (no `onMeasurementKindChange`/`onLineMeasurementKindChange` passed, e.g.
  the Power Flow results overlay).

## Known gaps / follow-ups

- **Dark mode is not implemented.** `index.css` only defines `:root` values.
  All tokens are already centralized, so adding a `.dark { --status-good: ...; }`
  block later is the only work required — no component changes.
- **`HatMatrixHeatmap`** (`BadDataAnalyticsTab.tsx`) uses two raw RGB triplet
  constants (`HEATMAP_DIAG_RGB`, `HEATMAP_OFFDIAG_RGB`) instead of
  `var(--color-*)`, because the component blends them into `rgba(r,g,b,a)`
  strings for opacity-by-magnitude cells — `rgba()` needs numeric components,
  and oklch tokens can't be split into r,g,b without a browser-side
  conversion. They're named constants with a comment linking them back to the
  `destructive`/`status-info` hues they mirror, not a compliance gap.
- **`StepFlowchart` only supports a linear chain + one loop-back edge.** It
  has no notion of branches or decision diamonds (the AC solver's Iwamoto
  fallback, for instance, isn't drawn as a branch — it only shows in the
  status badge). If a future algorithm needs real branching, reach for
  mermaid.js at that point rather than extending this component into a
  general graph layout engine.
- **`sgen` (static generators — fixed PQ, does NOT control voltage, unlike
  `gen`) is now converted**, as of 2026-07-03. `load_pandapower_case()`
  aggregates `net.sgen` (filtered by `in_service`, same pattern as `load_df`/
  `gen_df`) per bus into its own `pGenDG`/`qGenDG` bus fields — kept separate
  from `pGen`/`gen_p` (which stays "voltage-controlled generation only") so
  DG shows up as its own legend entry/table column in `TopologyTab` instead
  of disappearing into another number. `build_net_from_frontend()` creates a
  real `pp.create_sgen(...)` element from those fields, and `run_distflow()`
  (LinDistFlow) subtracts `pGenDG`/`qGenDG` from net bus injection the same
  way it already did for `pGen`. Found via a real mismatch: `pn.case5()` has
  a 170 MW `sgen` at bus 0 that was silently vanishing, throwing off both
  that bus's and the slack bus's injection vs. the
  `5_BUS_IEEE_bad_data_analytics.ipynb` notebook (which builds `net` directly
  via `pn.case5()`, sgen included). `mv_oberrhein` — a real MV distribution
  case Luis cares about — has 153 sgen buses out of 179 that were **all**
  silently dropped before this fix.
- **Line (branch-flow) meters, as of 2026-07-03.** Bus meters were the only
  kind for most of this project; `topology.line_measurements` (a
  `LineMeasurement{lineId, kind}` list, same 4 kinds as bus meters) adds a
  second kind attached to a line instead — physically a TC/TP-based
  transducer, reading P_ij (DC) or P_ij+Q_ij (AC), instead of a bus's net
  injection. Opt-in, unlike bus meters: no default fill
  (`ensureMeasurements()` only fills bus gaps with 'scada'), a line only
  gets one when the user clicks it in the Topology diagram (spatial view
  only — see below) and picks a kind.
  - **Both terminals, not just "from" (changed 2026-07-03, same day).**
    Initially only the line's "from" terminal was measured (rationale: in
    lossless DC, `P_j->i = -P_i->j` exactly at the true value, so the "to"
    side looked like duplicate information). Reverted after comparing
    against `notebooks/simulacao/5_BUS_IEEE_bad_data_analytics.ipynb`
    (case5, SCADA everywhere): the notebook's `m` was 17, the app's was 11
    — a real DOF mismatch (13 vs 7), not just noise. Each line terminal has
    its own physical RTU/CT-TP with its own independent measurement error —
    two noisy samples of the same true flow, not the same information
    twice — which is the standard bad-data redundancy convention (Abur &
    Exposito) and exactly what the reference notebook models via
    `dc_linear.build_linear_dc_model_from_rundcpp()`'s unfiltered
    `measurement_table` (which already computed both sides in from/to
    blocks, same branch order both times — the app now includes both
    instead of filtering to "from" only).
  - Backend: `kind_by_pp_line()` + the `line_kind_by_pp`/`pp_line_to_frontend`
    params threaded through `configured_dc_rows()` (DC — reuses the "line"
    rows `build_linear_dc_model_from_rundcpp()` already computed for every
    branch, both sides) and
    `build_configured_ac_measurements()`/`configured_ac_linearized_rows()`
    (AC — adds `p_branch`/`q_branch` `ACMeasurement`s for both sides, which
    `ACYbusMeasurementModel` already supported via `Yf`/`Yt`, unused until
    now). All four consumers (`/estimation/preview`, `/estimation/run`,
    `/baddata/geometry`, `/baddata/detect`) funnel through these two shared
    functions, so wiring line meters into them once covers every route.
  - `line_id_map_from_topology()` (`network_builder.py`) maps frontend line
    id → pandapower line index by position, mirroring how `build_net_from_frontend()`
    inserts lines — added instead of changing that function's return
    signature, which ~12 call sites already destructure as `(net, bus_id_map)`.
  - A meter's `kind` only changes σ (reusing `p_sigma_mult` from
    `MEASUREMENT_KIND_SPECS` — same tiers as bus P/Q) — unlike bus meters,
    there's no `has_voltage`/`has_angle` gating, since a "line PMU" measures
    the same P_ij/Q_ij as any other line-meter kind, just via a synchronized
    current phasor (tighter σ), not an extra state-linear quantity the way a
    bus PMU's θ is (a line has no voltage/angle of its own to measure).
  - Response rows now carry both `busId` and `lineId` (exactly one is
    non-null per row) instead of just `busId` — one configured line meter
    now yields TWO rows (same `lineId`, opposite `label` direction, e.g.
    `"P_0->1"` and `"P_1->0"`), so `MeasurementsSummaryCard`'s "Bus N" /
    "Line N" location cell appends `r.label` for line rows (`"Line 1
    (P_0->1)"`) to keep the two distinguishable — a bare `lineId` alone
    would render two identical-looking rows. `StateEstimationTab`'s and
    `BadDataAnalyticsTab`'s tables never had a separate bus column (they key
    off `label` directly), so those needed no change.
  - **Tree view line-click works too**, via `TopologyTreeNode.parentLine`
    (`networkTopology.ts::buildTopologyTree`) — the BFS already walks real
    `Line` objects per edge, it just wasn't exposed on the tree node before;
    `hierarchyRoot.links()`'s synthesized edge ids (`-(i+1)`) are only a
    fallback now, used if `parentLine` is somehow missing (shouldn't happen).

## 2026-08-18 — `UpdateBanner` e a ponte com o Electron

O app passou a ser distribuível como instalador Windows (ver
[packaging/README.md](../../packaging/README.md)). Duas coisas entraram no
frontend por causa disso.

**`src/lib/electron.ts`** — tipa a ponte que o preload expõe em
`window.dsseUpdater`. Ela é `undefined` no browser (dev com Vite, ou alguém
abrindo o backend direto na porta), então todo consumidor passa por
`getUpdater()` e trata `null`. Nunca acesse `window.dsseUpdater` direto: em dev
isso é `undefined` e quebra a página inteira.

**`src/components/UpdateBanner.tsx`** — faixa no topo do `App`, acima do
header. O `electron-updater` baixa a nova versão sozinho em segundo plano mas
**não mostra nada**; sem este banner a atualização entra calada no próximo
restart e o usuário nunca sabe que ela existiu. O componente só traduz os
eventos (`update:available` → `update:progress` → `update:ready`) em algo
visível, e renderiza `null` fora do app empacotado — ou seja, em dev ele é
invisível por construção, o que é esperado e não é bug.

Segue as duas regras desta página: strings em inglês (é UI de usuário) e zero
cor crua — a faixa usa `bg-accent/10` e `text-accent`, não um amarelo/azul
hardcoded.


---

## 2026-08-21 — Barras de erro por barra no State Estimation tab

A tabela *Bus State Estimates* ganhou duas colunas: `θ ±95% (deg)` e, no modo
AC, `|V| ±95% (pu)`. São `1,96·sqrt(diag((HᵀWH)⁻¹))`, vindas de
`state_uncertainty()` em
[bad_data.py](../../src/tese_dsse/estimacao_estado/bad_data.py).

**Por que a coluna existe.** O app já mostrava `J` e o limiar qui-quadrado no
topo, e `|Error θ|` contra a verdade na tabela. Faltava a peça do meio, e é a
única das três que sobrevive em operação real: o erro contra a verdade só
existe porque estamos em simulação, e o `J` — apesar de parecer um selo de
qualidade — é **estatisticamente independente** do erro do estado
(`Cov(x̂−x, r) = 0` sob ruído gaussiano). Sem a coluna de incerteza, a leitura
natural da tela era "J passou no qui-quadrado, logo a estimativa está boa",
que é uma inferência inválida. Ver a linha correspondente em
[decisoes_tecnicas.md](../../docs/governanca/decisoes_tecnicas.md).

**Detalhes de implementação que não são óbvios.**

- A barra do slack é `0` por construção (referência de ângulo fixa), não
  `null` — `null` fica reservado para "matriz de ganho singular", que
  renderiza `—`. São estados diferentes e a UI os distingue.
- A coluna `|Error θ|` **não** usa mais um limiar absoluto fixo (`> 0.1`) para
  pintar de vermelho. Agora fica vermelha quando o erro real estoura a própria
  banda de 95% daquela barra, com um `⚠`. Isso é o sinal honesto: a estimativa
  saiu pior do que o próprio modelo afirma que ela pode ser, o que aponta bad
  data ou parâmetro errado — e pode acontecer com o `J` passando no
  qui-quadrado. Um limiar absoluto marcava de vermelho pontas de alimentador
  legitimamente incertas e deixava passar erro grande numa barra bem medida.
- No ramo AC o estado é `[ângulos das angle_buses | |V| de bus_order]`, então
  os dois blocos são fatiados separadamente por `angle_state_index` e
  `vm_state_offset`; não dá para assumir ordenação por `busId`.

---

## 2026-08-24 — Meters panel: "Apply to all" + Switches interativos

### Problema

O painel lateral **Meters** (botão `List` no Network Diagram) só listava buses e
linhas individualmente. Não havia forma de instrumentar uma rede inteira de uma
vez, nem de interagir com switches (abrir/fechar) — eles eram somente leitura
(traço tracejado no diagrama, sem controle).

### O que mudou

**Feature 1 — "Apply to all"**
Adicionada uma barra de ação no topo do painel Meters (visível só quando
`onApplyMeterToAll` é passado, i.e., na aba Topology — não no diagrama de
resultados somente leitura). Contém:
- `Select` para o tipo de medidor (PMU / SCADA / AMI / Pseudo)
- `Select` para o alvo (Buses only / Lines only / Buses + Lines)
- Botão `Apply to all`

Sobrescreve todas as medições do alvo em um clique; implementado em
`applyMeterToAll` no [`TopologyTab.tsx`](src/components/TopologyTab.tsx).

**Feature 2 — Switches interativos**
Nova seção **Switches** no painel Meters. Lista todos os switches de
`topology.openSwitches` com estado "open" e switches fechados nesta sessão com
estado "closed". Cada switch tem um shadcn `Switch` toggle:
- **open → close**: remove de `openSwitches`, cria uma `Line` com R=X=0.001 pu
  (impedância de chave ideal) → diagrama redesenha com linha sólida
- **close → open**: remove a `Line` criada, restaura o `OpenSwitch` original

Estado rastreado em `closedSwitchMap: Map<switchId, { lineId, sw }>` no
[`TopologyTab.tsx`](src/components/TopologyTab.tsx).

### Convenções

- Painel Meters alargado de `w-56` → `w-60` para acomodar os novos controles
  sem quebrar a lista de buses/linhas.
- Switches abertos: label "open" em `text-status-info`; fechados: "closed" em
  `text-status-good` — segue o mapa de cores semânticas existente.
- O `closedSwitchMap` é estado **de sessão** — ao recarregar a topologia ou
  mudar de template, os switches fechados voltam à posição original.
- `TopologyDiagram` recebe `closedSwitches` como prop opcional para mostrar
  switches fechados no painel mesmo após serem removidos de `openSwitches`.

### 2026-08-24 — Switches modelados com estado (NF/NA)

- **O que mudou**: A interface `Topology` agora expõe `switches: Switch[]` contendo **todos** os switches do pandapower, com a flag `closed`.
- **Por que**: Redes em anel (como `mv_oberrhein`) usam chaves Normalmente Fechadas (NF) além das Normalmente Abertas (NA). Antes, o backend só enviava as NA em `openSwitches`, tornando impossível saber quais linhas ativas eram chaves que podiam ser abertas. Agora o UI mostra a lista completa, permitindo abrir chaves NF (status verde) e fechar chaves NA (status azul). Para o D3 e retrocompatibilidade, a propriedade `openSwitches` continua sendo populada apenas com as chaves abertas.

### 2026-08-25 — Reconfiguração de alimentadores com lista completa de chaves (37 switches no case33bw)

- **O que mudou**: Em redes onde o pandapower não cria tabela `net.switch` separada (como `case33bw` que usa `in_service=False` nas 5 tie-lines), agora todas as linhas em operação são exportadas como chaves normalmente fechadas (`closed: true`) e as tie-lines como chaves normalmente abertas (`closed: false`). O painel Switches agora exibe contadores (`32 closed · 5 open`) e permite rolar a lista completa.
- **Por que**: Ao fechar uma tie-line (ex: SW-4 18?33), o usuário precisa poder abrir qualquer uma das 32 linhas ativas da rede para desfazer o loop e restaurar a radialidade do alimentador reconfigurado.

### 2026-08-25 — Separação dos painéis de Meters e Switches no diagrama

- **O que mudou**: O painel lateral de Meters agora é exclusivamente dedicado a medidores de barras e linhas. Um botão e painel próprio de Switches foi criado na barra de ferramentas (\Switches (X/Y)\), exibindo lista completa com todos os ramos (fechados e abertos) e controles de abertura/fechamento.
- **Por que**: Evita poluição visual no painel de medidores e garante que mesmo topologias salvas sem o campo \switches\ derivem automaticamente todas as linhas ativas como chaves fechadas via \getTopologySwitches\.

### 2026-08-25 — Símbolos de switches interativos no diagrama e botão de Reset ao padrão

- **O que mudou**: Adicionado renderizador SVG interativo de chaves no diagrama unifilar (símbolo elétrico padrão IEEE com 2 terminais e lâmina articulada: verde/fechada em linhas contínuas e azul/aberta em linhas tracejadas). Clicar diretamente no símbolo da chave no diagrama realiza a manobra. Adicionado botão 'Reset to default topology' no painel de Switches.
- **Por que**: Permite manobras rápidas e visuais na rede diretamente sobre a tela de topologia, além de recuperar instantaneamente o estado original do Pandapower com um clique.

### 2026-08-25 — Limpeza visual do diagrama: remoção de poluição de switches e desacoplamento espacial de medidores

- **O que mudou**: (1) Ramos normalmente fechados não recebem mais glifos de switch sobrepostos, ficando como linhas limpas contínuas. (2) Símbolo de chave aberta padronizado com máscara de fundo nas tie-lines tracejadas com tipografia mono sutil. (3) Medidores de linha (CTs) posicionados a 28% do sending bus e rótulos de linha a 72% do receiving bus, eliminando 100% de sobreposição.
- **Por que**: Evita colisão visual entre medidores, rótulos e símbolos de manobra, seguindo o padrão de diagramas unifilares profissionais de engenharia de potência.

### 2026-08-25 — Símbolo minimalista de dois pontos em todos os switches (IEEE unifilar inline)

- **O que mudou**: Todos os 37 switches são desenhados como dois pontos discretos inline com a própria linha (\•—•\ para fechado e \• / •\ para aberto com lâmina a 35°). Sem cápsulas, sem cores extras nem caixas pesadas. Distribuição ao longo da linha: medidor a 20%, switch a 50%, rótulo a 80%.
- **Por que**: Atende ao padrão minimalista clássico de diagramas unifilares de engenharia elétrica, mantendo legibilidade total e controle interativo por clique.

### 2026-09-07 — Aba Pipeline: a cadeia operacional em tela

- **O que mudou**: nova aba `Pipeline` ([PipelineTab.tsx](src/components/PipelineTab.tsx)),
  entre `Agents` e `Workbench` na navegação. Mostra a cadeia medidor → RTU →
  comunicação → SCADA RTDB → processador de topologia → estimador como uma
  faixa de 8 blocos clicáveis; clicar num bloco troca a tabela de detalhe
  abaixo, e a faixa continua visível, então a cadeia nunca sai da tela.
- **Por que**: o ponto da aba é *propagação*. Injeta-se uma falha numa camada
  e observa-se o que a seguinte faz dela. Uma tela por camada (ou um accordion)
  esconderia exatamente a relação que a aba existe para mostrar.
- **Reúso, não componentes novos**: a faixa reaproveita o padrão de status do
  `BlockCard` do [WorkbenchTab.tsx](src/components/WorkbenchTab.tsx), as tabelas
  usam [TableCard.tsx](src/components/TableCard.tsx) (copy/expand de graça), e o
  painel de trace segue a mesma leitura de `TraceStep` do
  [ExecutionPanel.tsx](src/components/ExecutionPanel.tsx). Os únicos elementos
  novos são o `Stat` (caixinha de métrica) e o `VerdictBanner`, ambos locais ao
  arquivo — não viraram componentes compartilhados porque só existe um
  consumidor; promover cedo demais fixa uma API antes de haver segundo caso.
- **VerdictBanner primeiro, tabelas depois**: as duas perguntas que a cadeia
  existe para responder (a topologia reconstruída bate com a real? o estimador
  sobreviveu?) ficam acima de tudo, em quatro linhas com ícone. Sem isso, a
  resposta ficava enterrada numa tabela de 40 linhas.
- **Cores semânticas dos estados de chave**: `0 → text-status-info`,
  `1 → text-status-good`, `2 → text-status-warn`, `3 → text-destructive`. A
  regra é "confiável × não confiável", não "aberto × fechado": 0 e 1 são os dois
  estados coerentes e ganham cores calmas; 2 e 3 são os ambíguos e ganham
  alerta. A mesma escala está na figura do CSI
  ([diag_cadeia_scada.html](../../docs/CSI/slides_2026/figuras/diag_cadeia_scada.html)),
  de propósito — slide e app precisam ser lidos como a mesma coisa.
- **Qualidade de ponto** segue o mesmo mapa: `good/suspect/bad` →
  `status-good/status-warn/destructive`.
- **Toda string da aba em inglês**, como o resto do app (a convenção já
  registrada em `decisoes_tecnicas.md`), mesmo com os módulos Python por trás
  documentados em português.

### 2026-09-07 (2) — Pipeline: camada de controle, agentes e a numeração da norma

- **Estados de chave realinhados ao padrão.** As cores passaram a seguir o
  DNP3 Double-Bit / IEC 61850 `Dbpos`: `0 Intermediate → status-warn`,
  `1 Determined OFF → status-info`, `2 Determined ON → status-good`,
  `3 Indeterminate → destructive`. A divisão que a cor comunica é **conclusiva
  × não conclusiva**, não aberta × fechada — 1 e 2 são as leituras boas.
  A numeração anterior (0 = aberto, 1 = fechado) era nossa; esta é de norma, e
  a mesma escala vale na figura do CSI de propósito.
- **`AgentVerdict` acima de tudo.** O veredito dos agentes
  (`DISPATCH` / `DERATE` / `BLOCK`) é a primeira coisa da tela, com a **cadeia
  de propagação** logo abaixo: quem avisou quem, e por quê. É o produto da
  camada — o alarme isolado de cada agente é trivial; a cadeia causal não.
- **Dois blocos novos na faixa**, `OPF / Control` e `Agents`, fechando os 9.
  O bloco de OPF mostra `Δ MW · N hidden` como métrica de relance, porque
  "violação oculta" é o número que interessa a um operador.
- **`FindingCard`** — componente local, um por achado de agente, com a borda
  colorida por severidade e o `caused_by` alinhado à direita em mono. Local ao
  arquivo, não compartilhado: só existe um consumidor, e promover cedo demais
  fixa uma API antes de haver segundo caso (mesma regra do `Stat`).
- **OPF ligado por padrão na UI, desligado por padrão na API.** A UI liga
  porque é a razão de a aba existir; a API deixa desligado porque `runopp` é
  bem mais lento e nem todo consumidor quer pagar isso.
- **Limites do OPF na barra de configuração** (V min e Load max %) em vez de
  escondidos: sem restrição que morda, o OPF vira despacho puramente econômico
  e o erro de topologia quase não muda a resposta — o usuário precisa poder
  apertar para ver o efeito.

### 2026-09-07 (3) — Console de operação: a tela para uma concessionária

- **Nova aba `Console`, e ela é a inicial.** Mesma corrida da cadeia que a aba
  Pipeline mostra, vista como uma sala de controle vê. Pipeline continua sendo
  a tela de engenharia; as duas coexistem de propósito (ver
  `decisoes_tecnicas.md`).
- **Por quê**: quem decide se a pesquisa vira financiamento — uma RTE, uma
  Enedis — lê HMI, não depurador. Uma tela só para os dois públicos não serviria
  a nenhum.
- **Copiado de um ADMS/SCADA real**: banda de status com número-herói e
  *alarm summary* por prioridade; lista de alarmes (hora, prioridade, fonte,
  descrição) como painel de primeira classe; unifilar como âncora espacial
  (`TopologyDiagram` em modo somente-leitura, sem handlers); lista de pontos no
  vocabulário deles (point / equipment / quality / age); posições de disjuntor
  com o código do protocolo visível.
- **Não copiado**: a densidade de um HMI real, que pressupõe treinamento. O
  default erra para o lado de ser entendível; se a validação disser "esparso
  demais", aumenta-se.
- **O elemento que um console real não tem** é o mímico do caminho do dado — a
  faixa de 9 estágios, colocada onde ficaria um mímico de processo. É a
  contribuição da pesquisa, e é a frase do pitch.
- **Estado nunca só por cor.** Os quatro níveis (`ok`/`info`/`warn`/`alarm`)
  carregam ícone + palavra, e cada estágio tem um `sr-only` com o nível. Um
  print em escala de cinza continua legível.
- **`stamp()` converte segundo de simulação em hora de relógio** (âncora
  arbitrária às 06:00). Operador lê hora, não offset; a cadeia não tem relógio
  real, então é só apresentação — nunca entra em cálculo.
- **Presets de cenário** em vez de montagem manual de ataque: seis situações
  nomeadas. A montagem manual continua na aba Pipeline.
- **Roda sozinho ao montar.** Um console que mostra tela vazia até alguém
  apertar um botão lê como quebrado.

## 2026-09-08 — Estágios do Console clicáveis, e o veredito que contradizia o alarme

Três correções na aba Console, todas vindas de rodar o `case33bw` na tela e
olhar o resultado.

- **Os blocos da faixa "Data path" agora abrem.** Eram `<div>` puros, sem
  handler: tinham borda, cor de estado e cara de card, e não respondiam ao
  clique. A expectativa de clicar é criada pelo próprio desenho, então não
  atendê-la lê como bug. Cada bloco virou `<button>` com `aria-expanded` e um
  painel `#stage-detail` logo abaixo da faixa.
- **O que o painel mostra** é a evidência da etapa no vocabulário do operador
  (RTU: pontos e período de varredura; Telecom: pacotes, perda, atraso por RTU;
  SCADA: usable/stale/bad, dispersão, idade do ponto mais velho…), com uma
  frase curta dizendo o que aquela camada fez. **Não** é um dump do artefato:
  a tabela completa por camada continua na aba Pipeline, que é a tela de
  engenharia. Mandar um visitante para lá só para descobrir por que Telecom
  está âmbar derrota o motivo de existir um console.
- **`openStage` não é resetado quando uma corrida nova termina.** Quem compara
  cenários quer continuar olhando o mesmo estágio entre as corridas — mesma
  razão pela qual o diagrama preserva pan e zoom ao alternar medidores.
- **O veredito não pode contradizer o alarme.** Com o OPF falhando, a faixa de
  cima dizia **CONTROL RELEASED** enquanto o bloco Dispatch estava vermelho e
  havia um alarme HIGH avisando que a camada de controle não respondeu. A
  correção é no backend (`control_agent` passou a bloquear quando o OPF do
  operador não converge), mas a regra é de tela: **numa UI cujo propósito é
  responder "posso atuar?", nenhum estado agregado pode ser mais otimista que o
  pior alarme que a própria tela está exibindo.** Vale para qualquer resumo
  novo que venha a ser colocado acima de uma lista de alarmes.
- **Texto que chega à tela por dado também é UI.** As mensagens de `trace.log`
  e os `title`/`detail` dos achados de agente aparecem no painel de alarmes e
  estavam em português — um deles bilíngue na mesma linha. Traduzidos. A regra
  da seção *Language* vale para eles, não só para o que está escrito no JSX.

## 2026-09-10 — Aba Topology: o diagrama deixa de travar em redes grandes

Motivo: carregar um caso pandapower de milhares de barras (`case2869pegase`:
2869 barras, 4582 linhas) deixava a aba praticamente inutilizável. A suspeita
inicial era "as animações"; elas eram parte, mas não a maior.

### O que estava caro

- **O SVG por si só.** Uma barra vira 6–10 elementos (`<g>`, círculo, id,
  nome, badge de medidor, indicadores G/L/DG) e uma linha até 3 (traço,
  rótulo, área de clique transparente). Some a isso um glifo de chave por
  ramo — `getTopologySwitches` reporta *todo* ramo fechado como uma chave — e
  o documento passava de 70 mil elementos SVG vivos. O navegador paga por
  todos em cada paint, hit-test e recálculo de estilo, mexa-se algo ou não.
- **A simulação de força animada.** ~300 quadros reescrevendo a posição de
  cada nó, linha, área de clique, badge e glifo. Pior: com coordenadas
  geográficas os nós já vêm fixados em `fx`/`fy`, ou seja, a simulação rodava
  sem resolver nada.
- **Varreduras O(n²).** `getMeasurement`/`getLineMeasurement` são `.find()` no
  array de medidas, chamadas uma vez por barra e por linha. E a normalização
  das coordenadas geográficas refazia o `filter` + dois `Math.max(...)` *dentro*
  do laço por barra.
- **Os painéis e tabelas.** O painel de Meters montava um `<Popover>` do Radix
  por barra e por linha; as tabelas Bus/Line Data, ~9 `<Input>` controlados por
  linha — dezenas de milhares de componentes que o React re-renderiza sempre
  que `topology` troca de identidade (isto é, a cada tecla).

### O que mudou

- **Dois renderizadores.** SVG continua para redes pequenas; acima de
  `LARGE_NETWORK_BUSES = 300` entra o [TopologyCanvasView](src/components/TopologyCanvasView.tsx).
  O layout puro (sem DOM) foi extraído para
  [topologyLayout.ts](src/lib/topologyLayout.ts), então os dois desenham
  exatamente a mesma geometria. Resultado medido no `case2869pegase`: de
  ~70 mil elementos para **1015 nós de DOM na página inteira**.
- **Botão segmentado Fast / Detailed**, no mesmo padrão de Spatial/Tree. Um
  botão único que alterna não serve aqui: escrito "Fast", ele é ambíguo entre
  o estado atual e o destino. Estado ativo tem que ser legível de relance.
- **Simulação headless.** `stop()` + `tick(n)` num laço, desenha uma vez. O
  handler de `tick` fica só para o *drag*. O "Fit" aplica o transform direto,
  sem transição — animar um transform repinta o canvas inteiro por quadro sem
  ganho de informação.
- **Piso de espessura em pixels de tela.** No canvas tudo é desenhado em
  coordenadas de layout com o contexto escalado por `t.k`. No zoom em que uma
  rede grande cabe na tela (k ≈ 0,03), um traço de 2px vira 0,05px e o desenho
  some. Todo traço tem piso `0.9/k` e todo raio de nó `1.8/k`. O contorno do
  nó passou a ser sempre desenhado — é ele que separa uma barra PQ
  (preenchimento quase branco) do fundo quase branco.
- **Virtualização** via [useVirtualRows](src/hooks/useVirtualRows.ts) nos dois
  painéis e nas duas tabelas. As linhas do painel de Meters compartilham o
  popover único que o diagrama já usa, em vez de cada uma montar o seu.

### Regras que ficam

- **Em qualquer laço sobre barras ou linhas, use `buildMeasurementIndex`**, não
  `getMeasurement`/`getLineMeasurement` — essas são `.find()` linear e servem
  só para consulta avulsa.
- **Tabela virtualizada precisa passar `exportData` ao `TableCard`.** O Copy
  dele lê as células renderizadas do DOM, o que normalmente é a virtude (o
  export bate com o que está na tela); com janela de linhas, o DOM só tem uma
  fatia. `expandedMaxHeight` existe pelo mesmo motivo: o Expand solta o teto de
  altura, e sem teto não há container rolando contra o qual janelar.
- **Cleanup de `requestAnimationFrame` guardado em ref tem que zerar a ref.**
  Cancelar sem zerar fez `scheduleDraw` acreditar para sempre que havia um
  desenho agendado; com o mount/unmount/mount do StrictMode em dev, o canvas
  ficava **em branco, sem um único erro no console**. Foi o bug que passou pelo
  typecheck, pelo build e pela primeira rodada de testes.
- **Cores no canvas.** Ele não lê `var(--color-…)`; a paleta é resolvida uma
  vez por tema com `getComputedStyle` (que força recálculo de estilo, então
  nunca dentro do laço de desenho). `oklch` é aceito como `fillStyle` — foi
  verificado no navegador, não assumido.

### Como foi verificado

Playwright contra `localhost:5173`, carregando `case2869pegase` (2869 barras,
4582 linhas, sem coordenadas geográficas, portanto o pior caso: força bruta de
layout). Não foi verificação por leitura de código.

| | antes | depois |
|---|---|---|
| nós de DOM na página | ~70 mil só no diagrama | 1015 |
| botões montados no painel Meters | ~7.451 | 36 |
| `<input>` nas tabelas | ~57 mil | 252 |
| 20 movimentos de mouse + zoom | travava | 0,65 s |

Também conferido que rede pequena não regrediu: `case33bw` continua no SVG com
664 elementos, o clique numa barra abre o popover, o clique numa linha abre o
popover de medidor de ramo, e alternar Fast e voltar para Detailed restaura os
mesmos 664 elementos. Zero erro de console.

### O que ficou pendente

> **Resolvido em 11/09/2026** — ver a entrada seguinte. O diagnóstico fica
> registrado porque é a parte que custou a achar.

Descobertas da mesma sessão, todas **fora** da aba Topology, e o motivo de o
app ainda abrir travado com uma rede grande salva.

1. **A Console dispara o pipeline sozinha ao montar.**
   [ConsoleTab.tsx](src/components/ConsoleTab.tsx) tem `useEffect(() => { run() }, [])`
   para a tela nunca aparecer vazia. Com o `case6495rte` isso manda ~3,4 MB de
   topologia e pede power flow, medições, DSSE, OPF e agentes de uma vez, sem
   ninguém ter pedido. Como Console é a aba inicial, é o que se vê no boot:
   botão Run em spinner e nada mais na tela. Acima de um limiar de barras
   deveria mostrar o botão, não disparar.
2. **A topologia inteira vai para o `localStorage` a cada mudança.**
   [App.tsx](src/App.tsx) faz `JSON.stringify(topology)` num `useEffect` com
   dependência `[topology]`. Medido: 1,46 MB no `case2869pegase`, ~3,4 MB no
   `case6495rte`. Bloqueia a thread principal, estoura a cota (perto de 5 MB) e
   o `catch {}` vazio engole o erro. É também o que faz o app **reabrir**
   travado. Deveria guardar só o identificador do caso pandapower e recarregar
   do backend. Saída de emergência: `localStorage.removeItem('dsse-topology')`.
3. **As demais abas não foram varridas.** Pipeline, Power Flow, State Est.,
   Bad Data e Console. Os padrões que custaram caro aqui são genéricos: tabela
   mapeando `topology.buses`/`lines` inteiros sem virtualização, `.find()` de
   medida dentro de laço, componente Radix por linha.
4. **Modo Tree numa rede grande radial não foi testado** (`lv_schutterwald`,
   2940 barras). O que se testou foi malhado (`case2869pegase`, 1714 loops), em
   que a árvore vira um pente muito alto e estreito. Renderiza e não trava, mas
   a legibilidade nesse caso não foi avaliada.
5. **Nada foi commitado, e nenhuma release foi feita.** Lembrando o ciclo:
   subir `version` em `app/electron/package.json`, commitar, `git tag app-vX.Y.Z`
   com o mesmo número, `git push origin app-vX.Y.Z`. Sem subir a `version`, quem
   já instalou nunca enxerga a atualização.


## 2026-09-11 — O resto do app: o boot travado, e as outras abas

Fecha os pendentes da entrada anterior. O relato que abriu isto foi o app
abrindo direto no `case6495rte` com a Console em spinner e a janela inteira
sem responder.

### Por que abria travado

Duas causas somadas, nenhuma delas na aba Topology.

1. **A Console disparava o pipeline sozinha ao montar.** Um
   `useEffect(() => { run() }, [])`, posto lá para a tela nunca aparecer
   vazia, o que é uma boa razão numa rede de teste. Com 6495 barras vira
   ~3,4 MB de topologia enviados e um pedido de power flow, medições, DSSE,
   OPF e agentes de uma vez. Console é a aba inicial, então isso acontecia no
   boot, sem ninguém pedir.
2. **A topologia inteira ia para o `localStorage` a cada mudança.**
   `JSON.stringify` de megabytes, num efeito que depende de `[topology]` —
   ou seja, a cada tecla no editor. Estourava a cota (~5 MB) e o `catch {}`
   vazio escondia. E o que era gravado voltava no boot seguinte, refazendo o
   travamento antes que desse para reagir.

### O que mudou

- **O storage guarda um ponteiro, não a rede.** Acima de
  `MAX_PERSISTED_BYTES` (1 MB), `App.tsx` grava
  `{ kind: 'pandapower-ref', caseName }` — 50 bytes medidos, contra ~3,4 MB —
  e recarrega o caso do backend no boot. O trade-off é explícito: edições de
  medidor e de chave numa rede muito grande não sobrevivem ao reload. São um
  clique para refazer; a alternativa era um app que não abria. Falha de
  persistência agora vai para `console.warn` em vez de sumir.
- **Restauração é visível e segura trabalho automático.** O badge da rede no
  cabeçalho vira "Restoring `<caso>`…" enquanto o fetch corre (dezenas de
  segundos para um caso grande) — sem isso parece que o caso salvo se perdeu.
  E a Console recebe `restoring`: rodar sobre a rede placeholder resolveria o
  alimentador errado e mostraria um resultado com o nome de outra rede.
- **A Console só auto-roda até 300 barras.** Acima disso mostra o botão e diz
  por quê. Um "aperte Run" lê como deliberado; dez segundos de tela congelada
  lê como quebrado.
- **Tabelas janeladas viraram um componente.** Só o Pipeline tinha onze
  tabelas com o mesmo padrão. [TableCard](src/components/TableCard.tsx) passou
  a publicar seu container de scroll por contexto e
  [VirtualTableBody](src/components/VirtualTableBody.tsx) se liga nele
  sozinho. Convertidas: Bus Results e Branch Flows (Power Flow); True state,
  Field measurements, Packets, RTDB, Switch telemetry e Estimated vs true
  (Pipeline); Result Measurements (Bad Data); AC vs DC e Bad Data Pipeline
  (Workbench). A aba Topology e o Power Flow foram migrados junto, para não
  ficarem dois padrões para a mesma coisa.
- **Gráficos têm teto de pontos.** Recharts é um elemento SVG por barra mais
  um `<Cell>` por cor. `capByRelevance` mantém tudo que é injetado, flagado ou
  selecionado, completa com os de maior magnitude até 400, e **devolve na
  ordem original das medidas** para o eixo x continuar sendo "por medida". A
  tela diz quantas ficaram de fora e onde achá-las.
- **O heat-map de incidência é limitado a 120×60.** É um `<div>` por célula,
  e a matriz é medidas × linhas: dezenas de milhões numa rede real. Mostra o
  canto superior esquerdo e avisa. (De passagem: ele usava `<>` com a `key` no
  filho em vez de `<Fragment key>`, que é um aviso do React.)

### Regras que ficam

- **Nunca `Math.max(...array)` em nada que escale com a rede.** O spread passa
  um argumento por elemento e estoura a pilha passando de ~65 mil, com um erro
  que não parece ter relação com a causa. Use laço ou `reduce`. Corrigido em
  Power Flow, Bad Data e no layout da topologia.
- **Tabela janelada precisa de altura fixa na linha e de `exportData` no
  `TableCard`.** A janela sai só do `scrollTop`, e o Copy lê o DOM — que com
  janela tem uma fatia.
- **`VirtualTableBody` usa `renderRow` como prop, não children-as-function.**
  Como children, o TypeScript inferia `T` como `unknown` em todo call site.
  (O mesmo tipo de armadilha apareceu no `activeResult` do Power Flow: inferido,
  virava união de dois tipos de objeto estruturalmente idênticos que o TS não
  colapsa, e a inferência genérica sobre `.buses` morria. Anotado
  explicitamente.)
- **Nenhuma tela deve disparar trabalho pesado sozinha sem olhar o tamanho da
  rede.** Vale para qualquer aba nova que queira "não aparecer vazia".

### Dois achados que só apareceram na tela

Nenhum dos dois aparece no typecheck nem no build; ambos vieram de olhar o
resultado com uma rede grande carregada.

- **O cabeçalho fixo nunca funcionou.** `overflow-x: auto` com `overflow-y`
  não declarado computa para `overflow-y: auto`, então o wrapper do `<Table>`
  do shadcn já era um container de rolagem, e o `sticky` do `<th>` se ancorava
  nele — uma caixa que nunca rola. Capar a altura por fora dava cabeçalho
  subindo junto com as linhas. Agora o teto vai em `containerStyle` do próprio
  `Table`, e o `TableCard` liga cabeçalho fixo por padrão em toda tabela com
  `maxHeight`. Regra: **se a tabela rola, o cabeçalho fica.**
- **Barras órfãs do modo Tree em fileira única.** `lv_schutterwald` tem 2824
  de 2940 barras inalcançáveis a partir do slack (são muitos alimentadores
  atrás dos próprios trafos). Em uma linha isso são ~130 000 px, e o fit
  espremia o diagrama inteiro num traço vertical. Agora vão em bloco quase
  quadrado: 6 800 → 97 485 pixels pintados na mesma viewport.

### Como foi verificado (2ª rodada)

Playwright de novo, reproduzindo o relato original: carregar `case6495rte`,
recarregar a página e ver com o que o app abre.

| | antes | depois |
|---|---|---|
| entrada no `localStorage` | ~3,4 MB (e estourando a cota) | 50 bytes |
| Console no boot | disparava o pipeline sozinha | espera, com o motivo na tela |
| trocar de aba com a rede restaurada | travado | 0,85 a 1,06 s |
| Power Flow, 1354 barras, Bus Results | ~3 345 linhas montadas | 44, e a janela acompanha o scroll |
| `<input>` na aba Topology, 1354 barras | ~12 mil | 252 |

Rede pequena conferida sem regressão: `case33bw` segue no SVG com 664
elementos, popover de barra e de linha funcionando, Fast/Detailed indo e
voltando. Zero erro de console em todas as rodadas.


## 2026-09-11 (2) — A simulação de força era o travamento

O relato foi "ainda está travado quando abro o front", no Firefox, com o aviso
nativo *"Cette page ralentit Firefox"*. As correções anteriores (canvas,
virtualização, ponteiro no storage) estavam certas e não eram o suficiente.

### O que estava acontecendo

Instrumentando o layout no navegador:

```
force sim 6495n/9019L: 14584 ms
force sim 6495n/9019L: 15671 ms
force sim 6495n/9019L: 14127 ms
force sim 6495n/9019L: 14282 ms
```

Cada simulação bloqueava a thread principal por ~14,5 s, e rodava **quatro
vezes** ao abrir a aba: duas medições de `dimensions` (o default 800×600 e
depois o valor real do `ResizeObserver`) multiplicadas pela dupla execução de
`useMemo` que o StrictMode faz em dev. ~58 s parado.

Ter deixado a simulação *headless* na rodada anterior resolveu a animação, não
o custo de CPU. Foi uma correção incompleta.

### O que mudou

O modo Spatial passou a usar **`computeRadialLayout`**: profundidade BFS a
partir do slack vira o raio, e cada subárvore recebe um setor angular
proporcional ao número de folhas que carrega. O setor proporcional é o ponto:
espalhar cada camada BFS uniformemente em 2π colapsa um alimentador radial numa
reta, porque suas camadas têm uma ou duas barras e `2πi/k` é então sempre 0 ou
π — foi a primeira versão, e ficou uma cruz.

A simulação virou o botão **Force**, desligado por padrão. Em rede pequena ela
rende um desenho agradável, e ligá-la no `case2869pegase` leva ~1,9 s: aceitável
para algo que a pessoa pediu.

| | antes | depois |
|---|---|---|
| abrir a aba Topology com 6495 barras | ~58 s de thread bloqueada | 1,9 s (Chromium) / 1,7 s (Firefox) |
| carregar o `case6495rte` | 40,6 s | 9,1 s |

De quebra o desenho ficou melhor: o `case33bw` mostra os três ramos do
alimentador abrindo da subestação em vez de um círculo arbitrário, e o
`case2869pegase` mostra agrupamentos em vez de bola de pelos.

### Regras que ficam

- **Um `useMemo` caro roda duas vezes em dev** (StrictMode), e mais vezes ainda
  se depender de algo medido do DOM. Se o custo importa, meça na tela.
- **Migração de formato persistido é checada por tamanho, antes do parse.** O
  guard de gravação não ajuda quem já tem o formato antigo guardado: dar
  `JSON.parse` em megabytes dentro do inicializador do `useState` bloqueia o
  primeiro render, e o app sobe travado sem os guards novos chegarem a valer.
- **Teste no Firefox também.** Aqui os dois motores deram o mesmo tempo, mas
  isso só se soube medindo.
- **Para medir travamento com Playwright, use `page.mouse.click(x, y)`.**
  `elemento.click()` via `evaluate` não ativa o Radix Tabs (a aba nem trocava, e
  eu li isso como "travado"), e `locator.click()` não retorna enquanto a thread
  principal estiver bloqueada. Meus dois primeiros diagnósticos foram artefato
  de ter errado isso — e o número "Topology: 1,06 s" que reportei na rodada
  anterior media uma re-renderização, não o primeiro layout.


## 2026-09-11 (3) — "os outros casos sumiram"

Relato: o seletor de topologia passando a mostrar só `Stagg & El-Abiad 5-Bus` e
`IEEE 14-Bus`, e os botões de classe sem as contagens (`Transmission` em vez de
`Transmission (30)`).

Nada tinha sumido. `getPandapowerCases()` terminava em `.catch(() => {})`, então
uma única falha de rede deixava a lista vazia **para sempre**, sem mensagem e
sem retry além de recarregar a página. E o caminho é comum: o `uvicorn` leva um
tempo para importar o pandapower, então quem abre o front logo depois de subir o
backend pega o erro.

Reproduzido bloqueando a chamada no Playwright: os botões saem exatamente como
no print, `['Distribution (MV)', 'Transmission', 'LV (BT)']`.

Agora: uma tentativa automática 2,5 s depois (cobre o backend ainda subindo) e,
persistindo, a linha "pandapower case list unavailable" com botão **Retry**, que
recupera em 0,3 s sem reload. `loadPandapowerCase` também ganhou `catch` com
toast — antes era rejeição não tratada.

**Regra:** `catch(() => {})` é proibido em qualquer coisa que alimente a tela.
Foi o terceiro desta série — os outros dois foram o `localStorage` do `App` e o
próprio guard de persistência. Se a chamada falha, a interface tem que dizer, e
dar um caminho de volta.

---

## 2026-09-16 — Identidade visual: logo oficial e ícone do app (squircle com transparência)

### O que mudou

1. **Logo e Ícone Oficial (`docs/assets/logo/dsse_mark_ieee_light.png`):**
   - Criação da identidade visual oficial do app combinando o rigor acadêmico com a simbologia unifilar padronizada (IEEE/IEC): barra principal, gerador com senóide AC, chave seccionadora articulada, pontos de medição em ciano e alimentadores radiais com cargas a 90° exatos.
   - **Transparência nos cantos externos:** Remoção do fundo quadrado externo ao redor do squircle via máscara com anti-aliasing (canal Alfa = 0 fora da moldura arredondada), permitindo que o ícone se integre naturalmente à barra de tarefas do Windows, docks e abas do navegador sem cantoneiras brancas.
2. **Frontend (`app/frontend/`):**
   - `index.html` atualizado com links para `favicon.ico`, `favicon.png` e `apple-touch-icon`.
   - `public/favicon.ico` gerado como arquivo ICO multi-resolução (16x16 até 256x256 com transparência).
   - `public/app-logo.png` e `public/favicon.png` adicionados.
   - `App.tsx`: o placeholder genérico `<Lightning>` no header foi substituído pela imagem oficial do logo (`/app-logo.png`) com borda suave e cantos arredondados.
3. **Electron (`app/electron/`):**
   - `app/electron/build/icon.ico` (multi-tamanhos: 16, 24, 32, 48, 64, 128, 256) e `icon.png` (512x512) criados para empacotamento do instalador Windows.
   - `createWindow` em `app/electron/main.js` configurado com a opção `icon` explícita para a janela em tempo de execução.
4. **Atualizações e Versão na aba Help (`HelpSidebar.tsx`):**
   - Rodapé da barra lateral de Help agora exibe a versão atual instalada (`vX.Y.Z`) com badge mono e botão manual **'Check for updates'**.
   - Integração com `sonner` (`toast.loading`, `toast.success`, `toast.info`, `toast.error`) dando feedback imediato.
   - Preload e `electron.ts` expõem `getVersion()` e `checkForUpdates()`.
   - As releases são publicadas e consultadas em `luisfboff1/dsse-workbench-releases`, viabilizando downloads públicos para todos os usuários sem exigir token.


## 2026-09-21 — Seletor de rede ficava em branco depois de carregar um caso pandapower

### O que estava acontecendo

Na aba Topology, depois de escolher qualquer caso do catálogo pandapower
(`case33bw`, `mv_oberrhein`...), o seletor "Load template..." voltava **vazio**,
como se nenhuma rede estivesse carregada. Visto ao tirar o print da lista de
redes para o slide 1 do pitch RTE.

Causa: dois formatos de id para a mesma coisa. O backend devolve a topologia
com `id = "pp_<caso>"` (`app/backend/routes/topology.py`), e `App.tsx` e o
próprio `TopologyTab.tsx` (recarga de caso) já usavam `pp_`. Só os itens da
lista usavam `value={`pp:${c.name}`}`. O `<Select value={topology.id}>` nunca
achava um item com `pp_case33bw`, e o Radix mostra o gatilho vazio quando o
valor não bate com nenhum item.

### O que mudou

- `TopologyTab.tsx`: os itens do catálogo usam `pp_${c.name}` e o
  `loadTemplate` testa `pp_`. Um formato só, o do backend.

### Regra que fica

- **Id de caso pandapower é sempre `pp_<caso>`**, no backend, no estado e no
  `value` de qualquer lista. Nada de um segundo separador na UI.


## 2026-09-23 — Importação e exportação de topologias (ImportTopologyDialog e ExportTopologyDropdown)

### O que mudou

1. **Toolbar da aba Topology (`TopologyTab.tsx`):**
   - Inseridos botões dedicados de **Import** (`<Upload>`) e **Export** (`<ExportTopologyDropdown>`) diretamente ao lado do seletor de casos/templates, mantendo a densidade e o padrão visual dos botões compactos do app (`h-10 px-3`).
2. **Modal de Importação (`ImportTopologyDialog.tsx`):**
   - Suporte a drag-and-drop de arquivos ou seleção manual via explorador do sistema operacional.
   - Suporte a múltiplos arquivos para formatos desacoplados (CSV com `buses.csv` e `lines.csv`, ou OpenDSS com scripts auxiliares), além de aceitar pacotes `.zip`.
   - Ação direta para download do modelo padronizado CSV (`downloadCsvTemplate`).
   - Notificações não-bloqueantes (`toast.warning`, `toast.info`) para alertas de divergência inicial de fluxo de carga ou redes extensas (> 500 barras).
3. **Dropdown de Exportação (`ExportTopologyDropdown.tsx`):**
   - Menu suspenso com download de um clique gerando downloads dinâmicos de Blob para Workbench JSON, pandapower JSON, Excel (.xlsx), CSV (.zip) e GraphML.

