import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react'
import * as maplibregl from 'maplibre-gl'
// `?worker&url` makes Vite bundle the worker with its imports into one
// standalone file; MapLibre 6's default worker lookup fails under Vite.
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import 'maplibre-gl/dist/maplibre-gl.css'
maplibregl.setWorkerUrl(maplibreWorkerUrl)
import type { Topology } from '@/lib/types'
import type { TopologySelection } from '@/lib/selection'
import { placeBuses } from '@/lib/geo'
import { Button } from '@/components/ui/button'
import { MapPin, MapTrifold } from '@phosphor-icons/react'

export interface MapHit {
  x: number
  y: number
  additive: boolean
}

export interface TopologyMapHandle {
  fit: () => void
}

interface TopologyMapViewProps {
  topology: Topology
  selection?: TopologySelection
  width: number
  height: number
  onBusClick?: (busId: number, hit: MapHit) => void
  onLineClick?: (lineId: number, hit: MapHit) => void
}

/** MapLibre can't parse the oklch() the theme tokens are written in, so
 *  round-trip each one through a 1×1 canvas to get plain rgba(). */
function resolveColor(token: string): string {
  const style = getComputedStyle(document.documentElement)
  const raw = style.getPropertyValue(`--color-${token}`).trim() || style.getPropertyValue(`--${token}`).trim() || '#888'
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = 1
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  if (!ctx) return raw
  ctx.fillStyle = raw
  ctx.fillRect(0, 0, 1, 1)
  const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data
  return `rgba(${r},${g},${b},${(a / 255).toFixed(3)})`
}

const EMPTY: GeoJSON.FeatureCollection = { type: 'FeatureCollection', features: [] }

/**
 * Geographic view of the network: buses as points, lines as segments, over an
 * OpenStreetMap basemap that can be switched off (the app has to stay useful
 * offline — the geometry never depends on the tiles).
 *
 * Loaded lazily by TopologyDiagram: MapLibre is the heaviest dependency in
 * the app and nobody who never opens the Map view should pay for it.
 */
export const TopologyMapView = forwardRef<TopologyMapHandle, TopologyMapViewProps>(function TopologyMapView(
  { topology, selection, width, height, onBusClick, onLineClick },
  ref
) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<maplibregl.Map | null>(null)
  const [ready, setReady] = useState(false)
  const [basemap, setBasemap] = useState(true)
  const [approximate, setApproximate] = useState(false)
  const busClickRef = useRef(onBusClick)
  const lineClickRef = useRef(onLineClick)
  busClickRef.current = onBusClick
  lineClickRef.current = onLineClick

  const placement = useMemo(() => placeBuses(topology.buses, approximate), [topology.buses, approximate])
  const hasAnyCoords = useMemo(() => topology.buses.some((b) => Number.isFinite(b.geoX) && Number.isFinite(b.geoY)), [topology.buses])

  const { buses, lines } = useMemo(() => {
    const busFeatures: GeoJSON.Feature[] = []
    for (const b of topology.buses) {
      const c = placement.coords.get(b.id)
      if (!c) continue
      busFeatures.push({ type: 'Feature', geometry: { type: 'Point', coordinates: c }, properties: { id: b.id, name: b.name, type: b.type } })
    }
    const lineFeatures: GeoJSON.Feature[] = []
    for (const l of topology.lines) {
      const a = placement.coords.get(l.from)
      const z = placement.coords.get(l.to)
      if (!a || !z) continue
      lineFeatures.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: [a, z] }, properties: { id: l.id, from: l.from, to: l.to } })
    }
    return {
      buses: { type: 'FeatureCollection', features: busFeatures } as GeoJSON.FeatureCollection,
      lines: { type: 'FeatureCollection', features: lineFeatures } as GeoJSON.FeatureCollection,
    }
  }, [topology.buses, topology.lines, placement])

  const fit = useCallback(() => {
    const map = mapRef.current
    if (!map || placement.coords.size === 0) return
    const bounds = new maplibregl.LngLatBounds()
    for (const c of placement.coords.values()) bounds.extend(c)
    map.fitBounds(bounds, { padding: 60, maxZoom: 17, duration: 400 })
  }, [placement])
  useImperativeHandle(ref, () => ({ fit }), [fit])

  // ── Create the map once ────────────────────────────────────────────────
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const c = {
      line: resolveColor('foreground'),
      slack: resolveColor('primary'),
      pv: resolveColor('accent'),
      pq: resolveColor('muted'),
      outline: resolveColor('foreground'),
      selection: resolveColor('selection'),
      bg: resolveColor('muted'),
    }
    const map = new maplibregl.Map({
      container,
      style: {
        version: 8,
        sources: {
          osm: {
            type: 'raster',
            tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
            tileSize: 256,
            maxzoom: 19,
            attribution: '© OpenStreetMap contributors',
          },
        },
        layers: [
          { id: 'bg', type: 'background', paint: { 'background-color': c.bg } },
          { id: 'osm', type: 'raster', source: 'osm' },
        ],
      },
      center: [5.7245, 45.1885],
      zoom: 11,
      dragRotate: false,
      attributionControl: { compact: true },
    })
    map.touchZoomRotate.disableRotation()
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')

    map.on('load', () => {
      map.addSource('lines', { type: 'geojson', data: EMPTY })
      map.addSource('buses', { type: 'geojson', data: EMPTY })
      map.addLayer({
        id: 'lines',
        type: 'line',
        source: 'lines',
        layout: { 'line-cap': 'round' },
        paint: { 'line-color': c.line, 'line-width': ['interpolate', ['linear'], ['zoom'], 8, 1.2, 16, 3.5], 'line-opacity': 0.75 },
      })
      map.addLayer({
        id: 'lines-sel',
        type: 'line',
        source: 'lines',
        filter: ['in', ['get', 'id'], ['literal', []]],
        layout: { 'line-cap': 'round' },
        paint: { 'line-color': c.selection, 'line-width': ['interpolate', ['linear'], ['zoom'], 8, 3, 16, 7] },
      })
      map.addLayer({
        id: 'lines-hit',
        type: 'line',
        source: 'lines',
        paint: { 'line-color': '#000', 'line-opacity': 0, 'line-width': 14 },
      })
      map.addLayer({
        id: 'buses-sel',
        type: 'circle',
        source: 'buses',
        filter: ['in', ['get', 'id'], ['literal', []]],
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 8, 8, 16, 15],
          'circle-color': c.selection,
          'circle-opacity': 0.35,
          'circle-stroke-color': c.selection,
          'circle-stroke-width': 2.5,
        },
      })
      map.addLayer({
        id: 'buses',
        type: 'circle',
        source: 'buses',
        paint: {
          'circle-radius': [
            'interpolate', ['linear'], ['zoom'],
            8, ['match', ['get', 'type'], 'slack', 5, 3],
            16, ['match', ['get', 'type'], 'slack', 10, 7],
          ],
          'circle-color': ['match', ['get', 'type'], 'slack', c.slack, 'pv', c.pv, c.pq],
          'circle-stroke-color': c.outline,
          'circle-stroke-width': 1.5,
        },
      })

      const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12 })
      const pick = (point: maplibregl.Point) =>
        map.queryRenderedFeatures(
          [
            [point.x - 6, point.y - 6],
            [point.x + 6, point.y + 6],
          ],
          { layers: ['buses', 'lines-hit'] }
        )

      map.on('click', (e) => {
        const hits = pick(e.point)
        const hit: MapHit = {
          x: e.point.x,
          y: e.point.y,
          additive: e.originalEvent.ctrlKey || e.originalEvent.metaKey || e.originalEvent.shiftKey,
        }
        const bus = hits.find((f) => f.layer.id === 'buses')
        if (bus) {
          busClickRef.current?.(Number(bus.properties.id), hit)
          return
        }
        const line = hits.find((f) => f.layer.id === 'lines-hit')
        if (line) lineClickRef.current?.(Number(line.properties.id), hit)
      })
      map.on('mousemove', (e) => {
        const hits = pick(e.point)
        map.getCanvas().style.cursor = hits.length ? 'pointer' : ''
        const bus = hits.find((f) => f.layer.id === 'buses')
        if (bus) {
          const coords = (bus.geometry as GeoJSON.Point).coordinates as [number, number]
          popup
            .setLngLat(coords)
            .setText(`Bus ${bus.properties.id} · ${bus.properties.name} · ${String(bus.properties.type).toUpperCase()}`)
            .addTo(map)
        } else {
          popup.remove()
        }
      })
      map.on('mouseout', () => popup.remove())
      setReady(true)
    })

    mapRef.current = map
    return () => {
      map.remove()
      mapRef.current = null
      setReady(false)
    }
  }, [])

  // ── Data ────────────────────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    ;(map.getSource('buses') as maplibregl.GeoJSONSource).setData(buses)
    ;(map.getSource('lines') as maplibregl.GeoJSONSource).setData(lines)
  }, [ready, buses, lines])

  // Re-fit only when the network (or how it is placed) changes — not on every
  // edit, which would yank the view away from where the user is looking.
  const fitKey = `${topology.id}|${placement.mode}`
  useEffect(() => {
    if (ready) fit()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, fitKey])

  // ── Selection ───────────────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    map.setFilter('buses-sel', ['in', ['get', 'id'], ['literal', [...(selection?.buses ?? [])]]])
    map.setFilter('lines-sel', ['in', ['get', 'id'], ['literal', [...(selection?.lines ?? [])]]])
  }, [ready, selection])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    map.setLayoutProperty('osm', 'visibility', basemap ? 'visible' : 'none')
  }, [ready, basemap])

  useEffect(() => {
    mapRef.current?.resize()
  }, [width, height])

  return (
    <div className="relative" style={{ width, height }}>
      <div ref={containerRef} style={{ position: 'absolute', inset: 0 }} />
      <div className="absolute left-2 top-2 z-10 flex flex-col items-start gap-1.5">
        <Button
          type="button"
          size="sm"
          variant={basemap ? 'default' : 'outline'}
          className="h-7 text-xs shadow"
          onClick={() => setBasemap((v) => !v)}
          title="Show or hide the OpenStreetMap basemap (the network is drawn either way)"
        >
          <MapTrifold className="w-3.5 h-3.5" /> Basemap
        </Button>
        {placement.mode === 'approximate' && (
          <div className="rounded-md border bg-card/95 px-2 py-1 text-xs shadow">
            Approximate placement (Grenoble) — this network has no real coordinates.
          </div>
        )}
      </div>
      {placement.mode === 'none' && (
        <div className="absolute inset-x-0 bottom-6 z-10 mx-auto w-fit max-w-md rounded-lg border bg-card/95 p-3 text-center text-xs shadow">
          {hasAnyCoords ? (
            <>
              <p className="mb-2">
                This network's coordinates are drawing coordinates, not lon/lat, so it can't be placed on the real map.
              </p>
              <Button type="button" size="sm" className="h-7 text-xs" onClick={() => setApproximate(true)}>
                <MapPin className="w-3.5 h-3.5" /> Place it approximately (Grenoble)
              </Button>
            </>
          ) : (
            <p>This network has no coordinates. Load a case with geodata (e.g. mv_oberrhein) or import GeoJSON / CSV with lon/lat.</p>
          )}
        </div>
      )}
    </div>
  )
})
