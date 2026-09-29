import type { Bus } from './types'

export type GeoMode = 'geographic' | 'approximate' | 'none'

export interface GeoPlacement {
  mode: GeoMode
  /** bus id → [lon, lat] */
  coords: Map<number, [number, number]>
}

/** Where "approximate" placement drops a network that has no real
 *  coordinates: Grenoble, so a demo topology lands somewhere recognisable. */
const APPROX_CENTER: [number, number] = [5.7245, 45.1885]
const APPROX_BOX_KM = { w: 6, h: 4 }
const KM_PER_DEG_LON = 78
const KM_PER_DEG_LAT = 111

function hasCoords(b: Bus): b is Bus & { geoX: number; geoY: number } {
  return Number.isFinite(b.geoX) && Number.isFinite(b.geoY)
}

/**
 * Decide whether the buses' geoX/geoY are real lon/lat. Many of the built-in
 * and pandapower cases carry planar drawing coordinates (100…800), which
 * would land in the ocean — those are reported as not geographic.
 */
export function isGeographic(buses: readonly Bus[]): boolean {
  const geo = buses.filter(hasCoords)
  if (geo.length === 0) return false
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  for (const b of geo) {
    if (Math.abs(b.geoX) > 180 || Math.abs(b.geoY) > 90) return false
    minX = Math.min(minX, b.geoX)
    maxX = Math.max(maxX, b.geoX)
    minY = Math.min(minY, b.geoY)
    maxY = Math.max(maxY, b.geoY)
  }
  // A real feeder spans a few degrees at most; a planar layout that happens
  // to fit in ±180 is far more spread out than that or sits at the origin.
  if (maxX - minX > 20 || maxY - minY > 20) return false
  if (Math.abs(minX) < 1 && Math.abs(maxX) < 1 && Math.abs(minY) < 1 && Math.abs(maxY) < 1) return false
  return true
}

export function placeBuses(buses: readonly Bus[], allowApproximate: boolean): GeoPlacement {
  const coords = new Map<number, [number, number]>()
  const geo = buses.filter(hasCoords)
  if (geo.length === 0) return { mode: 'none', coords }

  if (isGeographic(buses)) {
    for (const b of geo) coords.set(b.id, [b.geoX, b.geoY])
    return { mode: 'geographic', coords }
  }
  if (!allowApproximate) return { mode: 'none', coords }

  const xs = geo.map((b) => b.geoX)
  const ys = geo.map((b) => b.geoY)
  const minX = Math.min(...xs), maxX = Math.max(...xs)
  const minY = Math.min(...ys), maxY = Math.max(...ys)
  const spanX = Math.max(maxX - minX, 1e-9)
  const spanY = Math.max(maxY - minY, 1e-9)
  const kmPerUnit = Math.min(APPROX_BOX_KM.w / spanX, APPROX_BOX_KM.h / spanY)
  const midX = (minX + maxX) / 2
  const midY = (minY + maxY) / 2
  for (const b of geo) {
    // Drawing coordinates grow downward; north is up on the map.
    const eastKm = (b.geoX - midX) * kmPerUnit
    const northKm = -(b.geoY - midY) * kmPerUnit
    coords.set(b.id, [APPROX_CENTER[0] + eastKm / KM_PER_DEG_LON, APPROX_CENTER[1] + northKm / KM_PER_DEG_LAT])
  }
  return { mode: 'approximate', coords }
}
