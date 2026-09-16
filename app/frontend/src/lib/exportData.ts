// Shared table/chart → clipboard export — one place formatting Markdown/CSV/
// JSON so every table and chart in the app copies with the same conventions.

export interface TableData {
  headers: string[]
  rows: (string | number)[][]
}

/** Array-of-objects (e.g. a recharts `data` prop) → TableData, headers taken
 *  from the first row's key order. */
export function tableFromObjects(data: Record<string, string | number>[]): TableData {
  const headers = data.length > 0 ? Object.keys(data[0]) : []
  return { headers, rows: data.map((row) => headers.map((h) => row[h] ?? '')) }
}

function csvEscape(value: string | number): string {
  const s = String(value)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

export function toCSV({ headers, rows }: TableData): string {
  return [headers, ...rows].map((r) => r.map(csvEscape).join(',')).join('\n')
}

function mdEscape(value: string | number): string {
  return String(value).replace(/\|/g, '\\|')
}

export function toMarkdownTable({ headers, rows }: TableData): string {
  const headerRow = `| ${headers.map(mdEscape).join(' | ')} |`
  const sepRow = `| ${headers.map(() => '---').join(' | ')} |`
  const bodyRows = rows.map((r) => `| ${r.map(mdEscape).join(' | ')} |`)
  return [headerRow, sepRow, ...bodyRows].join('\n')
}

export function toJSON({ headers, rows }: TableData): string {
  return JSON.stringify(
    rows.map((r) => Object.fromEntries(headers.map((h, i) => [h, r[i]]))),
    null,
    2
  )
}
