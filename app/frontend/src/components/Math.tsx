/**
 * Wrappers finos sobre KaTeX — sem depender do pacote react-katex (tipos
 * inconsistentes entre versões). katex.renderToString roda de forma síncrona
 * e retorna HTML/MathML que injetamos direto; é o mesmo que o wrapper faria.
 */
import { useMemo } from 'react'
import katex from 'katex'

export function InlineMath({ math }: { math: string }) {
  const html = useMemo(
    () => katex.renderToString(math, { throwOnError: false, displayMode: false }),
    [math]
  )
  return <span dangerouslySetInnerHTML={{ __html: html }} />
}

export function BlockMath({ math }: { math: string }) {
  const html = useMemo(
    () => katex.renderToString(math, { throwOnError: false, displayMode: true }),
    [math]
  )
  return <div dangerouslySetInnerHTML={{ __html: html }} />
}
