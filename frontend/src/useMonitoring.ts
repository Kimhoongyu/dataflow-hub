import { useEffect, useState } from 'react'
import { api, ApiError, errorMessage, type Monitoring, type Period } from './api'

const POLL_MS = 10000

/** Tenant operations overview, refreshed every 10 seconds while mounted. */
export function useMonitoring(tenantId: string, period: Period, refreshKey: number, onExpired: () => void) {
  const [data, setData] = useState<Monitoring | null>(null)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    api<Monitoring>(`/tenants/${tenantId}/monitoring?period=${period}`, { signal: controller.signal })
      .then(value => { setData(value); setError('') })
      .catch(error => {
        if (controller.signal.aborted) return
        if (error instanceof ApiError && error.status === 401) onExpired()
        else setError(errorMessage(error))
      })
    const timer = setTimeout(() => setTick(v => v + 1), POLL_MS)
    return () => { controller.abort(); clearTimeout(timer) }
  }, [tenantId, period, refreshKey, tick, onExpired])
  return { data, error }
}
