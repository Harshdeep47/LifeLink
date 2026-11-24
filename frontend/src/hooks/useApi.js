/**
 * Data-fetching hooks.
 *
 * `useApiData` handles the lifecycle every view needs: loading, error, retry,
 * and aborting a request whose component has unmounted or whose inputs changed.
 * Without the abort, a slow search that the user has already moved past can
 * land after a newer one and overwrite fresher results.
 */
import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * @param fetcher  (signal) => Promise<data>
 * @param deps     dependency array, as for useEffect
 * @param options  { enabled, initialData }
 */
export function useApiData(fetcher, deps = [], { enabled = true, initialData = null } = {}) {
  const [data, setData] = useState(initialData)
  const [loading, setLoading] = useState(enabled)
  const [error, setError] = useState(null)
  const [reloadToken, setReloadToken] = useState(0)
  const controllerRef = useRef(null)

  const reload = useCallback(() => setReloadToken((n) => n + 1), [])

  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      return undefined
    }

    // Cancel whatever is in flight before starting a newer request.
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller

    let active = true
    setLoading(true)
    setError(null)

    fetcher(controller.signal)
      .then((result) => {
        if (active) {
          setData(result)
          setLoading(false)
        }
      })
      .catch((cause) => {
        if (!active || cause?.name === 'AbortError') return
        setError(cause)
        setLoading(false)
      })

    return () => {
      active = false
      controller.abort()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled, reloadToken])

  return { data, loading, error, reload, setData }
}

/** For mutations: tracks submitting state and surfaces the error to the form. */
export function useMutation(mutator) {
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  const run = useCallback(
    async (...args) => {
      setSubmitting(true)
      setError(null)
      try {
        const outcome = await mutator(...args)
        setResult(outcome)
        return outcome
      } catch (cause) {
        setError(cause)
        // Rethrowing lets a caller distinguish success from failure while the
        // hook still owns the error state for rendering.
        throw cause
      } finally {
        setSubmitting(false)
      }
    },
    [mutator],
  )

  const reset = useCallback(() => {
    setError(null)
    setResult(null)
  }, [])

  return { run, submitting, error, result, reset }
}

/** Debounces a value, for search-as-you-type without a request per keystroke. */
export function useDebounced(value, delay = 350) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(timer)
  }, [value, delay])
  return debounced
}

/**
 * Browser geolocation with every failure mode the specification lists handled
 * explicitly: permission denied, position unavailable, timeout and the API
 * being absent entirely. The user is never forced to share location -- manual
 * entry is always available, and that is the point of returning a reason
 * rather than just null.
 */
export function useGeolocation() {
  const [state, setState] = useState({
    status: 'idle', // idle | locating | granted | denied | unavailable | timeout | error
    coords: null,
    accuracy: null,
    message: null,
  })

  const request = useCallback(() => {
    if (!('geolocation' in navigator)) {
      setState({
        status: 'unavailable',
        coords: null,
        accuracy: null,
        message: 'This browser does not provide location. Enter a place name instead.',
      })
      return
    }

    setState((prev) => ({ ...prev, status: 'locating', message: null }))

    navigator.geolocation.getCurrentPosition(
      (position) => {
        setState({
          status: 'granted',
          coords: {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
          },
          accuracy: position.coords.accuracy,
          message:
            position.coords.accuracy > 2000
              ? 'Your location is only roughly known. Results may be imprecise.'
              : null,
        })
      },
      (geoError) => {
        const map = {
          1: {
            status: 'denied',
            message:
              'Location permission was declined. You can search by place name instead.',
          },
          2: {
            status: 'unavailable',
            message: 'Your position could not be determined. Try searching by place name.',
          },
          3: {
            status: 'timeout',
            message: 'Finding your location took too long. Try again or search by name.',
          },
        }
        const mapped = map[geoError.code] ?? {
          status: 'error',
          message: 'Location could not be read. Search by place name instead.',
        }
        setState({ coords: null, accuracy: null, ...mapped })
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 },
    )
  }, [])

  return { ...state, request }
}
