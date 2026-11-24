/**
 * The discovery map, shared by Find Blood and Donation Camps.
 *
 * Markers used to be anonymous dots that each had to be clicked to identify.
 * They now carry their names, cluster when they crowd each other, and stay in
 * step with the result list in both directions.
 *
 * ## How clustering works here
 *
 * The data goes into a MapLibre GeoJSON source with `cluster: true`, so the
 * grouping is done by the library at every zoom level — including the case
 * this was most needed for: several facilities at nearly the same coordinate,
 * where individual markers sit on top of one another and the ones underneath
 * become unreachable.
 *
 * The drawing is then done with DOM markers built from whatever the source
 * reports as visible. That is MapLibre's own "cluster HTML markers" pattern,
 * and it is a deliberate choice over symbol layers: text in a symbol layer
 * needs a glyph (font) endpoint, and our raster basemap has none. This keeps
 * marker captions without adding a font service dependency.
 *
 * It also bounds the DOM in the way that matters: a cluster is one element
 * standing in for many points, and only what is on screen is built. The
 * previous version created an element per record regardless of visibility.
 *
 * ## What it refuses to do
 *
 * - It never moves a marker to make it easier to see. Crowding is solved by
 *   clustering, because a shifted marker is a lie about where something is.
 * - It never plots a record whose coordinates are unusable; those are counted
 *   and reported, so "7 shown" against a list of 9 is explained.
 * - It never reports a road distance or ETA. Distances are straight-line and
 *   labelled so; Directions hands the destination's real coordinates to an
 *   external navigator rather than claiming a computed route.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

// MapLibre's stylesheet. Required for the canvas, controls and popups;
// omitting it was a real defect once already.
import 'maplibre-gl/dist/maplibre-gl.css'

// MapLibre's web worker, emitted as a real asset with its hashed URL handed
// to the library. v6 otherwise derives the URL from `import.meta.url` and
// looks for a sibling file the bundler never emits; the SPA fallback then
// answers that 404 with index.html and HTTP 200, so the worker receives HTML
// and fails to start.
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'

import {
  KIND_CAMP,
  boundsOf,
  directionsUrl,
  shortLabel,
  toFeatureCollection,
} from './mapData.js'
import './FacilityMap.css'

const MAP_STYLE_URL = import.meta.env.VITE_MAP_STYLE_URL ?? ''

const SOURCE_ID = 'lifelink-points'
const PROBE_LAYER_ID = 'lifelink-points-probe'

/**
 * Basemap tiles, and why they come from OpenStreetMap.
 *
 * Amazon Location was intended, but it needs a credential this account's
 * service control policy will not permit (`AWS::Location::APIKey` is denied).
 * OpenStreetMap's standard raster tiles need none.
 *
 * The obligations that choice carries are met: attribution is displayed and
 * MapLibre's attribution control left on; zoom is capped and nothing
 * prefetches, so tiles are fetched only as a user pans. It is a demonstration
 * basemap, not a production tile service.
 */
const OSM_RASTER_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 17,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors',
    },
  },
  layers: [{ id: 'osm-tiles', type: 'raster', source: 'osm', minzoom: 0, maxzoom: 19 }],
}

function basemapStyle() {
  return MAP_STYLE_URL || OSM_RASTER_STYLE
}

/** Escape anything bound for innerHTML. */
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c])
}

function popupHtml(properties, origin) {
  const isCamp = properties.kind === KIND_CAMP
  const distance = properties.km === null || properties.km === undefined
    ? ''
    : `<div class="map-popup__row">${Number(properties.km).toFixed(1)} km straight-line</div>`
  const href = directionsUrl({
    destination: { latitude: properties.lat, longitude: properties.lon },
    origin,
  })
  return [
    '<div class="map-popup">',
    `<div class="map-popup__kind">${isCamp ? 'Donation camp' : 'Blood bank'}</div>`,
    `<strong class="map-popup__name">${escapeHtml(properties.name)}</strong>`,
    properties.city ? `<div class="map-popup__row">${escapeHtml(properties.city)}</div>` : '',
    properties.summary ? `<div class="map-popup__row">${escapeHtml(properties.summary)}</div>` : '',
    distance,
    href
      ? `<a class="map-popup__link" href="${href}" target="_blank" rel="noreferrer noopener">Directions</a>`
      : '',
    '</div>',
  ].join('')
}

/** The list shown when the map cannot be drawn, or on request. */
function ResultList({ facilities = [], camps = [], onSelect, onSelectCamp, selectedId }) {
  const entries = [
    ...facilities.map((f) => ({
      key: `f-${f.facilityId}`, id: f.facilityId, kind: 'Blood bank',
      name: f.name, city: f.city, km: f.straightLineKm, onPick: () => onSelect?.(f),
    })),
    ...camps.map((c) => ({
      key: `c-${c.campId}`, id: c.campId, kind: 'Donation camp',
      name: c.name, city: c.city, km: c.straightLineKm, onPick: () => onSelectCamp?.(c),
    })),
  ].sort((a, b) => (a.km ?? Infinity) - (b.km ?? Infinity))

  if (entries.length === 0) {
    return <p className="map-fallback__empty muted">Nothing to plot for this search.</p>
  }

  return (
    <ol className="map-fallback__list">
      {entries.map((entry) => (
        <li key={entry.key}>
          <button
            type="button"
            className={`map-fallback__item ${
              selectedId === entry.id ? 'map-fallback__item--selected' : ''
            }`}
            onClick={entry.onPick}
          >
            <span className="map-fallback__name">{entry.name}</span>
            <span className="map-fallback__meta">
              {entry.kind}
              {entry.city ? ` · ${entry.city}` : ''}
              {typeof entry.km === 'number' && <> · {entry.km.toFixed(1)} km</>}
            </span>
          </button>
        </li>
      ))}
    </ol>
  )
}

export function FacilityMap({
  facilities = [],
  camps = [],
  origin,
  onSelect,
  onSelectCamp,
  selectedId,
  height = 420,
}) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const markersRef = useRef(new Map())
  const originMarkerRef = useRef(null)
  const popupRef = useRef(null)
  // Held in refs as well as state: the draw callback runs inside MapLibre
  // event handlers, which close over whatever was current when registered.
  const selectedRef = useRef(selectedId)
  const originRef = useRef(origin)
  const collectionRef = useRef({ type: 'FeatureCollection', features: [] })

  const [renderFailed, setRenderFailed] = useState(false)
  const [tilesLoaded, setTilesLoaded] = useState(false)
  const [mapError, setMapError] = useState(null)
  const [showList, setShowList] = useState(false)
  const [showFacilities, setShowFacilities] = useState(true)
  const [showCamps, setShowCamps] = useState(true)
  const [showOrigin, setShowOrigin] = useState(true)

  selectedRef.current = selectedId
  originRef.current = origin

  const { collection, skipped } = useMemo(
    () => toFeatureCollection({
      facilities: showFacilities ? facilities : [],
      camps: showCamps ? camps : [],
    }),
    [facilities, camps, showFacilities, showCamps],
  )
  collectionRef.current = collection

  const showMap = !renderFailed && !showList

  /** Tell the parent which record was picked, so the list can highlight it. */
  const choose = useCallback((properties) => {
    if (properties.kind === KIND_CAMP) {
      onSelectCamp?.({ campId: properties.id, name: properties.name })
    } else {
      onSelect?.({ facilityId: properties.id, name: properties.name })
    }
  }, [onSelect, onSelectCamp])

  const openPopup = useCallback((properties, coordinates) => {
    const instance = mapRef.current
    if (!instance) return
    const { map, maplibregl } = instance
    // One popup at a time: selecting another location clears the last.
    popupRef.current?.remove()
    popupRef.current = new maplibregl.Popup({
      offset: 30, closeButton: true, maxWidth: '260px',
    })
      .setLngLat(coordinates)
      .setHTML(popupHtml(properties, originRef.current))
      .addTo(map)
  }, [])

  /** Draw markers for whatever the clustering source currently reports. */
  const renderMarkers = useCallback(() => {
    const instance = mapRef.current
    if (!instance?.map?.getSource?.(SOURCE_ID)) return
    const { map, maplibregl } = instance

    let features = []
    try {
      features = map.querySourceFeatures(SOURCE_ID)
    } catch {
      return
    }

    const wanted = new Map()
    for (const feature of features) {
      const properties = feature.properties ?? {}
      const coordinates = feature.geometry?.coordinates
      if (!coordinates) continue
      if (properties.cluster) {
        wanted.set(`cluster-${properties.cluster_id}`, {
          type: 'cluster',
          clusterId: properties.cluster_id,
          count: properties.point_count,
          coordinates,
        })
      } else {
        // Keyed by record id, so a record spanning two tiles is drawn once.
        wanted.set(`point-${properties.id}`, { type: 'point', properties, coordinates })
      }
    }

    for (const [key, marker] of markersRef.current) {
      if (!wanted.has(key)) {
        marker.remove()
        markersRef.current.delete(key)
      }
    }

    for (const [key, item] of wanted) {
      const existing = markersRef.current.get(key)
      if (existing) {
        if (item.type === 'point') {
          existing.getElement().classList.toggle(
            'map-pin--selected', selectedRef.current === item.properties.id,
          )
        }
        continue
      }

      const element = document.createElement('button')
      element.type = 'button'

      if (item.type === 'cluster') {
        element.className = 'map-cluster'
        element.textContent = String(item.count)
        element.setAttribute('aria-label', `${item.count} locations — zoom in`)
        element.title = `${item.count} locations here — click to zoom in`
        element.addEventListener('click', () => {
          const source = map.getSource(SOURCE_ID)
          Promise.resolve(source.getClusterExpansionZoom(item.clusterId))
            .then((zoom) => map.easeTo({ center: item.coordinates, zoom, duration: 400 }))
            .catch(() => map.easeTo({
              center: item.coordinates, zoom: map.getZoom() + 2, duration: 400,
            }))
        })
      } else {
        const { properties } = item
        const isCamp = properties.kind === KIND_CAMP
        element.className = `map-pin ${isCamp ? 'map-pin--camp' : 'map-pin--facility'}`
        if (selectedRef.current === properties.id) element.classList.add('map-pin--selected')
        // The name travels with the marker, so nothing must be clicked to
        // discover what it is.
        element.innerHTML =
          `<span class="map-pin__glyph" aria-hidden="true">${isCamp ? '▲' : '◆'}</span>`
          + `<span class="map-pin__label">${escapeHtml(shortLabel(properties.name))}</span>`
        element.setAttribute(
          'aria-label',
          `${isCamp ? 'Donation camp' : 'Blood bank'}: ${properties.name}`,
        )
        element.title = `${properties.name}${properties.city ? ` · ${properties.city}` : ''}`
        element.addEventListener('click', () => {
          choose(properties)
          openPopup(properties, item.coordinates)
        })
      }

      markersRef.current.set(
        key,
        new maplibregl.Marker({ element, anchor: 'bottom' })
          .setLngLat(item.coordinates)
          .addTo(map),
      )
    }
  }, [choose, openPopup])

  // --- map creation, once --------------------------------------------------

  useEffect(() => {
    if (!showMap || !containerRef.current || mapRef.current) return undefined
    let cancelled = false

    import('maplibre-gl')
      .then((module) => {
        // v6 exposes named exports only; v4 had a default. Handle both.
        const maplibregl = module.default ?? module
        if (typeof maplibregl.setWorkerUrl === 'function') {
          maplibregl.setWorkerUrl(maplibreWorkerUrl)
        }
        if (typeof maplibregl?.Map !== 'function') {
          throw new TypeError(
            `maplibre-gl exposed no Map constructor (keys: ${Object.keys(module).slice(0, 8).join(', ')})`,
          )
        }
        if (cancelled || !containerRef.current) return

        try {
          const map = new maplibregl.Map({
            container: containerRef.current,
            style: basemapStyle(),
            center: originRef.current
              ? [originRef.current.longitude, originRef.current.latitude]
              : [76.3869, 30.3398],
            zoom: 10,
            attributionControl: true,
          })
          mapRef.current = { map, maplibregl }
          map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')

          // An error is reported over the map, never instead of it. Hiding
          // the map and the reason together made an earlier failure
          // undiagnosable.
          map.on('error', (event) => {
            const message = event?.error?.message ?? String(event?.error ?? 'unknown error')
            // eslint-disable-next-line no-console
            console.warn('MapLibre error:', message, event)
            setMapError((previous) => previous ?? message)
          })

          map.on('load', () => {
            if (cancelled) return
            setTilesLoaded(true)

            map.addSource(SOURCE_ID, {
              type: 'geojson',
              data: collectionRef.current,
              cluster: true,
              // Points within this many pixels group together: a little over
              // twice a marker's width, so they cluster before they collide.
              clusterRadius: 46,
              // Past this zoom every point stands alone, so an individual
              // record is always reachable by zooming in.
              clusterMaxZoom: 15,
            })

            // Invisible, and load-bearing: a source needs a layer for its
            // tiles to be built, and querySourceFeatures reads those tiles.
            map.addLayer({
              id: PROBE_LAYER_ID,
              type: 'circle',
              source: SOURCE_ID,
              paint: { 'circle-radius': 0, 'circle-opacity': 0 },
            })

            map.on('moveend', renderMarkers)
            map.on('sourcedata', (event) => {
              if (event.sourceId === SOURCE_ID && event.isSourceLoaded) renderMarkers()
            })

            const bounds = boundsOf(collectionRef.current.features)
            if (bounds) map.fitBounds(bounds, { padding: 56, maxZoom: 14, duration: 0 })
            renderMarkers()
          })
        } catch (cause) {
          // eslint-disable-next-line no-console
          console.error('MapLibre could not be constructed:', cause)
          setRenderFailed(true)
        }
      })
      .catch((cause) => {
        // eslint-disable-next-line no-console
        console.error('MapLibre failed to load:', cause)
        setRenderFailed(true)
      })

    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showMap])

  // Filters and new searches update source and markers together, so the map
  // and the list never show different result sets.
  useEffect(() => {
    const source = mapRef.current?.map?.getSource?.(SOURCE_ID)
    if (!source) return
    source.setData(collection)
    renderMarkers()
  }, [collection, renderMarkers])

  // The origin marker: one DOM marker, visually distinct from results.
  useEffect(() => {
    const instance = mapRef.current
    if (!instance || !tilesLoaded) return
    const { map, maplibregl } = instance
    originMarkerRef.current?.remove()
    originMarkerRef.current = null
    if (!origin || !showOrigin) return

    const element = document.createElement('div')
    element.className = 'map-pin map-pin--origin'
    element.innerHTML =
      '<span class="map-pin__glyph" aria-hidden="true">●</span>'
      + '<span class="map-pin__label">Search location</span>'
    element.setAttribute('aria-label', 'Your search location')
    originMarkerRef.current = new maplibregl.Marker({ element, anchor: 'bottom' })
      .setLngLat([origin.longitude, origin.latitude])
      .addTo(map)
  }, [origin, showOrigin, tilesLoaded])

  // Re-centre when the origin moves.
  useEffect(() => {
    const instance = mapRef.current
    if (!instance || !origin) return
    instance.map.easeTo({ center: [origin.longitude, origin.latitude], duration: 500 })
  }, [origin?.latitude, origin?.longitude])

  // Selecting from the list centres the map, highlights the marker and opens
  // its popup — the other half of the synchronisation.
  useEffect(() => {
    const instance = mapRef.current
    if (!instance || !selectedId) return
    const feature = collection.features.find((f) => f.properties.id === selectedId)
    if (!feature) return
    instance.map.easeTo({
      center: feature.geometry.coordinates,
      zoom: Math.max(instance.map.getZoom(), 13),
      duration: 400,
    })
    openPopup(feature.properties, feature.geometry.coordinates)
    renderMarkers()
  }, [selectedId, collection, openPopup, renderMarkers])

  // A container that changes size — a tab becoming visible, a window resize —
  // leaves MapLibre's canvas at the old dimensions until it is told.
  useEffect(() => {
    const instance = mapRef.current
    const node = containerRef.current
    if (!instance || !node || typeof ResizeObserver === 'undefined') return undefined
    const observer = new ResizeObserver(() => instance.map.resize())
    observer.observe(node)
    return () => observer.disconnect()
  }, [tilesLoaded])

  useEffect(() => () => {
    for (const marker of markersRef.current.values()) marker.remove()
    markersRef.current.clear()
    originMarkerRef.current?.remove()
    popupRef.current?.remove()
    mapRef.current?.map?.remove()
    mapRef.current = null
  }, [])

  const fitAll = () => {
    const bounds = boundsOf(collection.features)
    if (bounds) mapRef.current?.map?.fitBounds(bounds, { padding: 56, maxZoom: 14 })
  }

  const resetToOrigin = () => {
    if (!origin) return fitAll()
    return mapRef.current?.map?.easeTo({
      center: [origin.longitude, origin.latitude], zoom: 11, duration: 400,
    })
  }

  if (!showMap) {
    return (
      <div className="map-fallback" style={{ minHeight: height }}>
        <div className="map-fallback__header">
          <strong>List view</strong>
          {renderFailed ? (
            <span className="muted text-xs">
              The map library could not be loaded, so results are listed instead.
            </span>
          ) : (
            <button type="button" className="btn btn--ghost btn--sm"
                    onClick={() => setShowList(false)}>
              Show map
            </button>
          )}
        </div>
        <ResultList
          facilities={facilities} camps={camps}
          onSelect={onSelect} onSelectCamp={onSelectCamp} selectedId={selectedId}
        />
      </div>
    )
  }

  return (
    <div className="map-shell">
      <div className="map-toolbar">
        <div className="map-toolbar__group">
          {facilities.length > 0 && (
            <label className="map-toggle">
              <input type="checkbox" checked={showFacilities}
                     onChange={(e) => setShowFacilities(e.target.checked)} />
              <span className="map-toggle__swatch map-toggle__swatch--facility">◆</span>
              Blood banks
            </label>
          )}
          {camps.length > 0 && (
            <label className="map-toggle">
              <input type="checkbox" checked={showCamps}
                     onChange={(e) => setShowCamps(e.target.checked)} />
              <span className="map-toggle__swatch map-toggle__swatch--camp">▲</span>
              Camps
            </label>
          )}
          <label className="map-toggle">
            <input type="checkbox" checked={showOrigin}
                   onChange={(e) => setShowOrigin(e.target.checked)} />
            <span className="map-toggle__swatch map-toggle__swatch--origin">●</span>
            Search location
          </label>
        </div>
        <div className="map-toolbar__group">
          <button type="button" className="btn btn--ghost btn--sm" onClick={fitAll}>
            Fit results
          </button>
          <button type="button" className="btn btn--ghost btn--sm" onClick={resetToOrigin}>
            Reset
          </button>
          <button type="button" className="btn btn--ghost btn--sm"
                  onClick={() => setShowList(true)}>
            List view
          </button>
        </div>
      </div>

      <div className="map-wrapper" style={{ height }}>
        <div ref={containerRef} className="map-canvas" role="application"
             aria-label="Map of blood banks and donation camps" />

        {!tilesLoaded && !mapError && (
          <p className="map-loading muted text-xs" role="status">Loading map…</p>
        )}

        {mapError && (
          <p className="map-error text-xs" role="status">Map problem: {mapError}</p>
        )}

        <ul className="map-legend" aria-label="Map key">
          <li><span className="map-legend__dot map-legend__dot--origin">●</span> Search location</li>
          <li><span className="map-legend__dot map-legend__dot--facility">◆</span> Blood bank</li>
          <li><span className="map-legend__dot map-legend__dot--camp">▲</span> Donation camp</li>
          <li><span className="map-legend__dot map-legend__dot--cluster">6</span> Several — click to zoom</li>
        </ul>
      </div>

      {skipped > 0 && (
        <p className="text-xs muted">
          {skipped} record{skipped === 1 ? '' : 's'} could not be placed on the
          map because {skipped === 1 ? 'its' : 'their'} coordinates are missing
          or invalid. {skipped === 1 ? 'It is' : 'They are'} still listed below.
        </p>
      )}
    </div>
  )
}
