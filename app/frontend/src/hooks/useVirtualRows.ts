import { useCallback, useEffect, useState } from 'react'

/**
 * Fixed-height row windowing — renders only the rows currently on screen.
 *
 * The topology panels and data tables map straight over topology.buses /
 * topology.lines (or over one row per measurement). On the IEEE test feeders
 * that is fine; on a real distribution case it means thousands of rows, each
 * of which may be a Radix Popover or a row of nine controlled <Input>s. React
 * mounts every one of them, and re-renders every one whenever `topology`
 * changes identity — which is on every keystroke. This keeps the mounted count
 * at roughly what fits in the viewport plus a small overscan.
 *
 * Deliberately hand-rolled rather than pulling in a virtualization library:
 * the app ships as a packaged Electron build, and a fixed-height list is the
 * one case where the whole implementation is this short.
 *
 * Most tables don't use this directly — see <VirtualTableBody>, which wires it
 * to the scroll container TableCard already owns.
 */
export interface VirtualRows {
  /** Index of the first rendered row. */
  start: number
  /** Index just past the last rendered row. */
  end: number
  /** Total scrollable height, so the scrollbar matches the full list. */
  totalHeight: number
  /** Where the rendered slice has to be pushed down to. */
  offsetY: number
  /** Height of the spacer that stands in for the rows below the window. */
  tailHeight: number
}

/** Windowing against a scroll container you already have a handle on. */
export function useVirtualRowsOn(
  element: HTMLElement | null,
  count: number,
  rowHeight: number,
  overscan = 8
): VirtualRows {
  const [range, setRange] = useState({ start: 0, end: Math.min(count, 40) })

  useEffect(() => {
    if (!element) return
    const measure = () => {
      const viewport = element.clientHeight || 400
      const first = Math.floor(element.scrollTop / rowHeight)
      const visible = Math.ceil(viewport / rowHeight)
      const start = Math.max(0, first - overscan)
      const end = Math.min(count, first + visible + overscan)
      setRange((prev) => (prev.start === start && prev.end === end ? prev : { start, end }))
    }
    measure()
    element.addEventListener('scroll', measure, { passive: true })
    // The container can be resized by the Expand button or by the window, and
    // the row count changes under us on a case swap while scrollTop stays put.
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => {
      element.removeEventListener('scroll', measure)
      observer.disconnect()
    }
  }, [element, count, rowHeight, overscan])

  const start = Math.max(0, Math.min(range.start, Math.max(0, count - 1)))
  const end = Math.min(range.end, count)
  return {
    start,
    end,
    totalHeight: count * rowHeight,
    offsetY: start * rowHeight,
    tailHeight: Math.max(0, count - end) * rowHeight,
  }
}

export interface VirtualRowsWithRef extends VirtualRows {
  scrollRef: (node: HTMLElement | null) => void
}

/** Same thing, when the caller owns the scroll container and wants a ref to
 *  hand it. Used by the topology side panels, which are plain divs. */
export function useVirtualRows(count: number, rowHeight: number, overscan = 8): VirtualRowsWithRef {
  const [element, setElement] = useState<HTMLElement | null>(null)
  const scrollRef = useCallback((node: HTMLElement | null) => setElement(node), [])
  return { ...useVirtualRowsOn(element, count, rowHeight, overscan), scrollRef }
}
