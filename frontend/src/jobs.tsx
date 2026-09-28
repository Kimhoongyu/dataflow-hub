import { useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError, errorMessage, type Job, type JobDetail, type JobStatus, type JobType } from './api'

const STATUS_LABEL: Record<JobStatus, string> = { queued: '대기', processing: '처리 중', completed: '완료', failed: '실패' }
const TYPE_LABEL: Record<JobType, string> = { validation: '검증', cleansing: '정제', transformation: '변환', aggregation: '집계' }
const POLL_MS = 3000
// Mirrors the server default so users get instant feedback; the server still enforces its own limit.
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024

const formatBytes = (n: number) => n < 1024 ? `${n} B` : n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`
const formatTime = (value: string) => new Date(value).toLocaleString('ko-KR')

export function StatusBadge({ status }: { status: JobStatus }) {
  return <span className={`status ${status}`}>{STATUS_LABEL[status]}</span>
}

export function JobTable({ jobs, showProject, onOpen }: { jobs: Job[]; showProject?: boolean; onOpen: (id: string) => void }) {
  return <div className="table-scroll"><table><thead><tr><th>파일</th>{showProject && <th>프로젝트</th>}<th>유형</th><th>상태</th><th>크기</th><th>등록</th></tr></thead><tbody>
    {jobs.map(job => <tr key={job.id}>
      <td><button className="text-button" onClick={() => onOpen(job.id)}>{job.file.original_name}</button></td>
      {showProject && <td>{job.project.name}</td>}
      <td>{TYPE_LABEL[job.job_type]}</td>
      <td><StatusBadge status={job.status} /></td>
      <td>{formatBytes(job.file.size_bytes)}</td>
      <td>{formatTime(job.created_at)}</td>
    </tr>)}
  </tbody></table></div>
}

export function UploadForm({ tenantId, projectId, onUploaded, onError }: {
  tenantId: string; projectId: string; onUploaded: (fileName: string) => void; onError: (error: unknown) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [jobType, setJobType] = useState<JobType>('validation')
  const [notes, setNotes] = useState('')
  const [hint, setHint] = useState('')
  const [busy, setBusy] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  function reset() { setFile(null); if (input.current) input.current.value = '' }
  function choose(next: File | null) {
    setHint('')
    if (next && !next.name.toLowerCase().endsWith('.csv')) { setHint('.csv 파일만 선택할 수 있습니다.'); reset() }
    else if (next && next.size > MAX_UPLOAD_BYTES) { setHint('파일은 10MB 이하만 업로드할 수 있습니다.'); reset() }
    else setFile(next)
  }
  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!file) return
    setBusy(true)
    const body = new FormData()
    body.append('file', file); body.append('job_type', jobType); body.append('notes', notes)
    try {
      await api<Job>(`/tenants/${tenantId}/projects/${projectId}/jobs`, { method: 'POST', body })
      reset(); setNotes(''); onUploaded(file.name)
    } catch (error) { onError(error) }
    finally { setBusy(false) }
  }
  return <form className="upload-form" onSubmit={submit}>
    <h4>CSV 업로드</h4>
    <label>CSV 파일 (UTF-8, 10MB 이하)<input ref={input} type="file" accept=".csv,text/csv" onChange={e => choose(e.target.files?.[0] ?? null)} /></label>
    {hint && <p className="field-error" role="alert">{hint}</p>}
    <label>처리 유형<select value={jobType} onChange={e => setJobType(e.target.value as JobType)}>
      {(Object.keys(TYPE_LABEL) as JobType[]).map(type => <option key={type} value={type}>{TYPE_LABEL[type]}</option>)}
    </select></label>
    <label>메모 (선택)<textarea rows={2} maxLength={1000} value={notes} onChange={e => setNotes(e.target.value)} /></label>
    <button disabled={busy || !file}>{busy ? '업로드 중…' : '업로드 후 처리 요청'}</button>
  </form>
}

export function JobDetailPanel({ tenantId, jobId, onClose, onExpired }: { tenantId: string; jobId: string; onClose: () => void; onExpired: () => void }) {
  const [job, setJob] = useState<JobDetail | null>(null)
  const [error, setError] = useState('')
  const [tick, setTick] = useState(0)
  const path = `/tenants/${tenantId}/jobs/${jobId}`
  useEffect(() => {
    const controller = new AbortController()
    api<JobDetail>(path, { signal: controller.signal }).then(setJob).catch(error => {
      if (controller.signal.aborted) return
      if (error instanceof ApiError && error.status === 401) onExpired()
      else setError(errorMessage(error))
    })
    return () => controller.abort()
  }, [path, tick, onExpired])
  // Follow the job until it reaches a final state.
  const active = job?.status === 'queued' || job?.status === 'processing'
  useEffect(() => {
    if (!active) return
    const timer = setTimeout(() => setTick(v => v + 1), POLL_MS)
    return () => clearTimeout(timer)
  }, [active, job])
  return <section className="panel detail" aria-label="작업 상세">
    <div className="panel-title"><h3>{job?.file.original_name ?? '작업 상세'}</h3><button className="secondary" onClick={onClose}>상세 닫기</button></div>
    {error && <p role="alert" className="error">{error}</p>}
    {!job && !error && <p role="status">불러오는 중…</p>}
    {job && <>
      <dl className="facts">
        <dt>상태</dt><dd><StatusBadge status={job.status} /></dd>
        <dt>프로젝트</dt><dd>{job.project.name}</dd>
        <dt>처리 유형</dt><dd>{TYPE_LABEL[job.job_type]}</dd>
        <dt>파일 크기</dt><dd>{formatBytes(job.file.size_bytes)}</dd>
        <dt>등록</dt><dd>{formatTime(job.created_at)}</dd>
        {job.finished_at && <><dt>종료</dt><dd>{formatTime(job.finished_at)}</dd></>}
        {job.duration_ms !== null && <><dt>처리 시간</dt><dd>{(job.duration_ms / 1000).toFixed(2)}초</dd></>}
        {job.attempt > 0 && <><dt>시도</dt><dd>{job.attempt}회</dd></>}
        {job.next_attempt_at && job.status === 'queued' && <><dt>재시도 예정</dt><dd>{formatTime(job.next_attempt_at)}</dd></>}
        {job.rows_in !== null && <><dt>처리 행</dt><dd>{job.rows_in} → {job.rows_out ?? '—'} (오류 {job.error_row_count ?? 0})</dd></>}
        {job.notes && <><dt>메모</dt><dd>{job.notes}</dd></>}
      </dl>
      {job.error_message && <p className="error">[{job.error_code}] {job.error_message}{job.status === 'queued' && ' — 자동으로 다시 시도합니다.'}</p>}
      {job.has_result && <a className="button-link" href={`/api${path}/result`} download>결과 CSV 다운로드</a>}
      <h4>처리 이력</h4>
      <ol className="timeline">{job.events.map((event, index) => <li key={index}>
        <StatusBadge status={event.to_status} /> <span>{event.message}</span> <small>{formatTime(event.created_at)}</small>
      </li>)}</ol>
    </>}
  </section>
}
