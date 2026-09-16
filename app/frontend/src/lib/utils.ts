import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

// Editable numeric table-cell inputs: monospace + tabular digits, native
// spinner hidden, and field-sizing:content so the box grows/shrinks with the
// actual value instead of a fixed width — a short "0" doesn't waste column
// space, and a long "-0.00712" doesn't get clipped. Pair with a per-usage
// min-w-*/max-w-* (a short int column and a long decimal column need
// different bounds) — see TopologyTab.tsx for the reference usage.
export const NUM_INPUT_CLASS = 'mono text-xs tabular-nums [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none [field-sizing:content]'
