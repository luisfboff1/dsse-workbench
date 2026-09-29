/**
 * Small, safe expression language for filtering table rows — the equivalent
 * of QGIS's "Select by Expression". Parsed and evaluated by hand (no `eval`,
 * no `new Function`), so a typed filter can never execute arbitrary code.
 *
 * Examples:
 *   type = 'pq' AND pLoad > 0.5
 *   "name" LIKE 'Bus 1%' OR id IN (3, 5, 7)
 *   abs(pLoad - pGen) >= 0.2 AND NOT (meter IS NULL)
 *
 * Rules worth knowing:
 *  - Field names are case-insensitive and may be double-quoted.
 *  - String comparison (=, LIKE, IN) is case-insensitive: users type 'PQ' as
 *    often as 'pq'.
 *  - A comparison involving NULL is false (SQL-like), except IS [NOT] NULL.
 */

export type ExprValue = number | string | boolean | null
export type ExprRow = Record<string, ExprValue | undefined>

export type CompileResult =
  | { ok: true; test: (row: ExprRow) => boolean }
  | { ok: false; error: string }

type Token =
  | { t: 'num'; v: number }
  | { t: 'str'; v: string }
  | { t: 'id'; v: string; quoted: boolean }
  | { t: 'op'; v: string }
  | { t: 'eof' }

const KEYWORDS = new Set(['and', 'or', 'not', 'in', 'like', 'is', 'null', 'true', 'false'])

class ExprError extends Error {}

function tokenize(src: string): Token[] {
  const out: Token[] = []
  let i = 0
  while (i < src.length) {
    const ch = src[i]
    if (/\s/.test(ch)) {
      i++
      continue
    }
    if (/[0-9.]/.test(ch)) {
      const m = /^(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?/.exec(src.slice(i))
      if (!m) throw new ExprError(`Unexpected "${ch}" at position ${i + 1}`)
      out.push({ t: 'num', v: Number(m[0]) })
      i += m[0].length
      continue
    }
    if (ch === "'" || ch === '"') {
      let j = i + 1
      let buf = ''
      while (j < src.length) {
        if (src[j] === ch) {
          // doubled quote = escaped quote, as in SQL
          if (src[j + 1] === ch) {
            buf += ch
            j += 2
            continue
          }
          break
        }
        buf += src[j++]
      }
      if (j >= src.length) throw new ExprError(`Unterminated ${ch === "'" ? 'string' : 'field name'}`)
      out.push(ch === "'" ? { t: 'str', v: buf } : { t: 'id', v: buf, quoted: true })
      i = j + 1
      continue
    }
    if (/[A-Za-z_]/.test(ch)) {
      const m = /^[A-Za-z_][A-Za-z0-9_]*/.exec(src.slice(i))!
      out.push({ t: 'id', v: m[0], quoted: false })
      i += m[0].length
      continue
    }
    const two = src.slice(i, i + 2)
    if (['<=', '>=', '!=', '<>', '=='].includes(two)) {
      out.push({ t: 'op', v: two })
      i += 2
      continue
    }
    if ('=<>+-*/%(),'.includes(ch)) {
      out.push({ t: 'op', v: ch })
      i++
      continue
    }
    throw new ExprError(`Unexpected "${ch}" at position ${i + 1}`)
  }
  out.push({ t: 'eof' })
  return out
}

type Node = (row: ExprRow) => ExprValue

const FUNCTIONS: Record<string, (args: ExprValue[]) => ExprValue> = {
  abs: ([a]) => (typeof a === 'number' ? Math.abs(a) : null),
  sqrt: ([a]) => (typeof a === 'number' && a >= 0 ? Math.sqrt(a) : null),
  round: ([a, d]) => {
    if (typeof a !== 'number') return null
    const f = 10 ** (typeof d === 'number' ? d : 0)
    return Math.round(a * f) / f
  },
  min: (args) => {
    const n = args.filter((a): a is number => typeof a === 'number')
    return n.length ? Math.min(...n) : null
  },
  max: (args) => {
    const n = args.filter((a): a is number => typeof a === 'number')
    return n.length ? Math.max(...n) : null
  },
  lower: ([a]) => (a == null ? null : String(a).toLowerCase()),
  upper: ([a]) => (a == null ? null : String(a).toUpperCase()),
}

function likeToRegExp(pattern: string): RegExp {
  const esc = pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/%/g, '.*').replace(/_/g, '.')
  return new RegExp(`^${esc}$`, 'is')
}

function looseEquals(a: ExprValue, b: ExprValue): boolean {
  if (a == null || b == null) return false
  if (typeof a === 'string' || typeof b === 'string') return String(a).toLowerCase() === String(b).toLowerCase()
  return a === b
}

function compareValues(a: ExprValue, b: ExprValue): number | null {
  if (a == null || b == null) return null
  if (typeof a === 'number' && typeof b === 'number') return a - b
  const sa = String(a).toLowerCase()
  const sb = String(b).toLowerCase()
  return sa < sb ? -1 : sa > sb ? 1 : 0
}

class Parser {
  private pos = 0
  private readonly tokens: Token[]
  private readonly fields: Map<string, string>
  constructor(tokens: Token[], fields: Map<string, string>) {
    this.tokens = tokens
    this.fields = fields
  }

  private peek(): Token {
    return this.tokens[this.pos]
  }
  private next(): Token {
    return this.tokens[this.pos++]
  }
  private isKeyword(word: string): boolean {
    const tok = this.peek()
    return tok.t === 'id' && !tok.quoted && tok.v.toLowerCase() === word
  }
  private isOp(op: string): boolean {
    const tok = this.peek()
    return tok.t === 'op' && tok.v === op
  }
  private expectOp(op: string) {
    if (!this.isOp(op)) throw new ExprError(`Expected "${op}"`)
    this.pos++
  }

  parse(): Node {
    const node = this.parseOr()
    if (this.peek().t !== 'eof') throw new ExprError(`Unexpected "${describe(this.peek())}"`)
    return node
  }

  private parseOr(): Node {
    let left = this.parseAnd()
    while (this.isKeyword('or')) {
      this.pos++
      const l = left
      const r = this.parseAnd()
      left = (row) => truthy(l(row)) || truthy(r(row))
    }
    return left
  }

  private parseAnd(): Node {
    let left = this.parseNot()
    while (this.isKeyword('and')) {
      this.pos++
      const l = left
      const r = this.parseNot()
      left = (row) => truthy(l(row)) && truthy(r(row))
    }
    return left
  }

  private parseNot(): Node {
    if (this.isKeyword('not')) {
      this.pos++
      const inner = this.parseNot()
      return (row) => !truthy(inner(row))
    }
    return this.parseComparison()
  }

  private parseComparison(): Node {
    const left = this.parseAdd()
    const tok = this.peek()

    if (tok.t === 'op' && ['=', '==', '!=', '<>', '<', '<=', '>', '>='].includes(tok.v)) {
      this.pos++
      const right = this.parseAdd()
      const op = tok.v
      return (row) => {
        const a = left(row)
        const b = right(row)
        if (op === '=' || op === '==') return looseEquals(a, b)
        if (op === '!=' || op === '<>') return a != null && b != null && !looseEquals(a, b)
        const c = compareValues(a, b)
        if (c == null) return false
        return op === '<' ? c < 0 : op === '<=' ? c <= 0 : op === '>' ? c > 0 : c >= 0
      }
    }

    if (this.isKeyword('is')) {
      this.pos++
      const negate = this.isKeyword('not')
      if (negate) this.pos++
      if (!this.isKeyword('null')) throw new ExprError('Expected NULL after IS')
      this.pos++
      return (row) => (left(row) == null) !== negate
    }

    const negate = this.isKeyword('not') && this.tokens[this.pos + 1]?.t === 'id'
    const savePos = this.pos
    if (negate) this.pos++
    if (this.isKeyword('in')) {
      this.pos++
      this.expectOp('(')
      const items: Node[] = [this.parseAdd()]
      while (this.isOp(',')) {
        this.pos++
        items.push(this.parseAdd())
      }
      this.expectOp(')')
      return (row) => {
        const v = left(row)
        if (v == null) return false
        const hit = items.some((item) => looseEquals(v, item(row)))
        return negate ? !hit : hit
      }
    }
    if (this.isKeyword('like')) {
      this.pos++
      const right = this.parseAdd()
      return (row) => {
        const v = left(row)
        const p = right(row)
        if (v == null || p == null) return false
        const hit = likeToRegExp(String(p)).test(String(v))
        return negate ? !hit : hit
      }
    }
    this.pos = savePos
    return left
  }

  private parseAdd(): Node {
    let left = this.parseMul()
    while (this.isOp('+') || this.isOp('-')) {
      const op = (this.next() as { v: string }).v
      const l = left
      const r = this.parseMul()
      left = (row) => {
        const a = l(row)
        const b = r(row)
        if (op === '+' && (typeof a === 'string' || typeof b === 'string') && a != null && b != null) return `${a}${b}`
        if (typeof a !== 'number' || typeof b !== 'number') return null
        return op === '+' ? a + b : a - b
      }
    }
    return left
  }

  private parseMul(): Node {
    let left = this.parseUnary()
    while (this.isOp('*') || this.isOp('/') || this.isOp('%')) {
      const op = (this.next() as { v: string }).v
      const l = left
      const r = this.parseUnary()
      left = (row) => {
        const a = l(row)
        const b = r(row)
        if (typeof a !== 'number' || typeof b !== 'number') return null
        if (op === '*') return a * b
        if (b === 0) return null
        return op === '/' ? a / b : a % b
      }
    }
    return left
  }

  private parseUnary(): Node {
    if (this.isOp('-')) {
      this.pos++
      const inner = this.parseUnary()
      return (row) => {
        const v = inner(row)
        return typeof v === 'number' ? -v : null
      }
    }
    return this.parsePrimary()
  }

  private parsePrimary(): Node {
    const tok = this.next()
    if (tok.t === 'num') return () => tok.v
    if (tok.t === 'str') return () => tok.v
    if (tok.t === 'op' && tok.v === '(') {
      const inner = this.parseOr()
      this.expectOp(')')
      return inner
    }
    if (tok.t === 'id') {
      const lower = tok.v.toLowerCase()
      if (!tok.quoted) {
        if (lower === 'true') return () => true
        if (lower === 'false') return () => false
        if (lower === 'null') return () => null
        if (this.isOp('(')) {
          const fn = FUNCTIONS[lower]
          if (!fn) throw new ExprError(`Unknown function "${tok.v}"`)
          this.pos++
          const args: Node[] = []
          if (!this.isOp(')')) {
            args.push(this.parseOr())
            while (this.isOp(',')) {
              this.pos++
              args.push(this.parseOr())
            }
          }
          this.expectOp(')')
          return (row) => fn(args.map((a) => a(row)))
        }
        if (KEYWORDS.has(lower)) throw new ExprError(`Unexpected keyword "${tok.v.toUpperCase()}"`)
      }
      const key = this.fields.get(lower)
      if (!key) throw new ExprError(`Unknown field "${tok.v}"`)
      return (row) => row[key] ?? null
    }
    throw new ExprError(tok.t === 'eof' ? 'Expression ended unexpectedly' : `Unexpected "${describe(tok)}"`)
  }
}

function describe(tok: Token): string {
  return tok.t === 'eof' ? 'end' : String(tok.v)
}

function truthy(v: ExprValue): boolean {
  return v === true || (typeof v === 'number' && v !== 0)
}

/**
 * Compile `source` against a known field list. Returns a row predicate, or a
 * human-readable error (shown inline under the filter box). An empty source
 * matches every row.
 */
export function compileExpression(source: string, fields: readonly string[]): CompileResult {
  if (!source.trim()) return { ok: true, test: () => true }
  try {
    const fieldMap = new Map(fields.map((f) => [f.toLowerCase(), f]))
    const node = new Parser(tokenize(source), fieldMap).parse()
    return { ok: true, test: (row) => truthy(node(row)) }
  } catch (err) {
    if (err instanceof ExprError) return { ok: false, error: err.message }
    throw err
  }
}
