export interface Tenant { id: string; name: string }
export interface User { id: string; name: string; email: string; tenants: Tenant[] }
export interface Project { id: string; tenant_id: string; name: string; description: string; created_at: string }
export interface ProjectPage { items: Project[]; total: number }

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, { ...options, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', ...options.headers } })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new ApiError(response.status, typeof body.detail === 'string' ? body.detail : '입력값을 확인해 주세요.')
  }
  return response.status === 204 ? undefined as T : response.json()
}
