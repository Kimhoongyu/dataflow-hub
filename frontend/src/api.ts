export interface Tenant { id: string; name: string }
export interface User { id: string; name: string; email: string; tenants: Tenant[] }
export interface Project { id: string; tenant_id: string; name: string; description: string; created_at: string }
export interface ProjectPage { items: Project[]; total: number }

export type JobType = 'validation' | 'cleansing' | 'transformation' | 'aggregation'
export type JobStatus = 'queued' | 'processing' | 'completed' | 'failed'
export interface Job {
  id: string; project: { id: string; name: string }; file: { id: string; original_name: string; size_bytes: number }
  job_type: JobType; status: JobStatus; notes: string; attempt: number
  rows_in: number | null; rows_out: number | null; error_row_count: number | null
  error_code: string | null; error_message: string | null
  created_at: string; started_at: string | null; finished_at: string | null; duration_ms: number | null
  next_attempt_at: string | null; has_result: boolean
}
export interface JobEvent { from_status: JobStatus | null; to_status: JobStatus; message: string; created_at: string }
export interface JobDetail extends Job { events: JobEvent[] }
export interface JobPage { items: Job[]; total: number }

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

export const errorMessage = (error: unknown) => error instanceof Error ? error.message : '요청을 처리하지 못했습니다.'

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  // Let the browser set the multipart boundary for FormData uploads.
  const contentType: Record<string, string> = options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }
  const response = await fetch(`/api${path}`, { ...options, credentials: 'same-origin', headers: { ...contentType, ...options.headers } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new ApiError(response.status, typeof body.detail === 'string' ? body.detail : '입력값을 확인해 주세요.')
  }
  return response.status === 204 ? undefined as T : response.json()
}
