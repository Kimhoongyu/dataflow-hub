import { useEffect, useState } from 'react'
import { api, ApiError, errorMessage, type Job, type JobPage } from './api'

const POLL_MS = 5000
const isActive = (job: Job) => job.status === 'queued' || job.status === 'processing'

/** Latest jobs for a tenant (optionally one project); polls while any job is still queued or processing. */
export function useJobs(tenantId: string, projectId: string | undefined, refreshKey: number, onExpired: () => void) {
  const [data, setData] = useState<JobPage | null>(null)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  const path = `/tenants/${tenantId}/jobs?limit=10${projectId ? `&project_id=${projectId}` : ''}`
  useEffect(() => {
    const controller = new AbortController()
    api<JobPage>(path, { signal: controller.signal }).then(page => { setData(page); setError('') }).catch(error => {
      if (controller.signal.aborted) return
      if (error instanceof ApiError && error.status === 401) onExpired()
      else setError(errorMessage(error))
    })
    return () => controller.abort()
  }, [path, refreshKey, tick, onExpired])
  const active = data?.items.some(isActive) ?? false
  useEffect(() => {
    if (!active) return
    const timer = setTimeout(() => setTick(v => v + 1), POLL_MS)
    return () => clearTimeout(timer)
  }, [active, data])
  return { data, error }
}
