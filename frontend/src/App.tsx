import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, ApiError, errorMessage as message, type Project, type ProjectPage, type Tenant, type User } from './api'
import { JobDetailPanel, JobTable, UploadForm } from './jobs'
import { MonitoringDashboard } from './monitoring'
import { useJobs } from './useJobs'
import './App.css'

function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError('')
    try { onLogin(await api<User>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })) }
    catch (error) { setError(message(error)) }
    finally { setBusy(false) }
  }
  return <main className="login-page">
    <div className="login-brand"><p className="eyebrow">DATAFLOW HUB</p><h1>데이터 작업의 시작,<br />하나의 워크스페이스에서.</h1><p>조직별 프로젝트를 관리하고 데이터 처리 서비스를 준비하세요.</p></div>
    <form className="login-card" onSubmit={submit}>
      <h2>로그인</h2><p className="subtext">소속 조직의 프로젝트에 접속합니다. (자동 배포 테스트)</p>
      <label>이메일<input type="email" autoComplete="username" required maxLength={254} value={email} onChange={e => setEmail(e.target.value)} /></label>
      <label>비밀번호<input type="password" autoComplete="current-password" required maxLength={256} value={password} onChange={e => setPassword(e.target.value)} /></label>
      {error && <p role="alert" className="error">{error}</p>}
      <button disabled={busy}>{busy ? '로그인 중…' : '로그인'}</button>
      <small>현재는 사전에 생성한 데모 계정으로 이용할 수 있습니다.</small>
    </form>
  </main>
}

function ProjectJobs({ tenantId, projectId, refreshKey, onExpired, onOpen }: {
  tenantId: string; projectId: string; refreshKey: number; onExpired: () => void; onOpen: (id: string) => void
}) {
  const { data, error } = useJobs(tenantId, projectId, refreshKey, onExpired)
  if (error) return <p role="alert" className="error">{error}</p>
  if (!data) return <p role="status">작업 불러오는 중…</p>
  if (data.total === 0) return <p className="empty">이 프로젝트에 업로드한 CSV가 없습니다.</p>
  return <JobTable jobs={data.items} onOpen={onOpen} />
}

function Workspace({ tenant, onExpired }: { tenant: Tenant; onExpired: () => void }) {
  const [page, setPage] = useState<'dashboard' | 'projects'>('dashboard')
  const [data, setData] = useState<ProjectPage | null>(null)
  const [offset, setOffset] = useState(0)
  const [revision, setRevision] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [selected, setSelected] = useState<Project | null>(null)
  const [detailBusy, setDetailBusy] = useState(false)
  const [jobsRevision, setJobsRevision] = useState(0)
  const [openJobId, setOpenJobId] = useState<string | null>(null)
  const path = `/tenants/${tenant.id}/projects`
  const recentJobs = useJobs(tenant.id, undefined, jobsRevision, onExpired)

  useEffect(() => {
    const controller = new AbortController()
    api<ProjectPage>(`${path}?offset=${offset}`, { signal: controller.signal }).then(setData).catch(error => {
      if (controller.signal.aborted) return
      if (error instanceof ApiError && error.status === 401) onExpired()
      else setError(message(error))
    })
    return () => controller.abort()
  }, [path, offset, revision, onExpired])

  function handleError(error: unknown) {
    if (error instanceof ApiError && error.status === 401) onExpired()
    else setError(message(error))
  }
  async function create(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(''); setNotice('')
    try {
      await api<Project>(path, { method: 'POST', body: JSON.stringify({ name, description }) })
      setName(''); setDescription(''); setOffset(0); setData(null); setRevision(v => v + 1)
      setNotice('프로젝트를 생성했습니다.')
    } catch (error) { handleError(error) }
    finally { setBusy(false) }
  }
  async function openProject(id: string) {
    setDetailBusy(true); setError(''); setSelected(null)
    try { setSelected(await api<Project>(`${path}/${id}`)) }
    catch (error) { handleError(error) }
    finally { setDetailBusy(false) }
  }
  function uploaded(fileName: string) {
    setError(''); setNotice(`"${fileName}" 파일을 업로드하고 처리 대기열에 등록했습니다.`); setJobsRevision(v => v + 1)
  }
  return <>
    <nav className="page-tabs" aria-label="페이지">
      <button className={page === 'dashboard' ? 'active' : 'secondary'} onClick={() => setPage('dashboard')}>대시보드</button>
      <button className={page === 'projects' ? 'active' : 'secondary'} onClick={() => setPage('projects')}>프로젝트</button>
    </nav>
    <header><div><p className="eyebrow">{tenant.name}</p><h2>{page === 'dashboard' ? '워크스페이스 현황' : '프로젝트 관리'}</h2><p className="subtext">현재 조직에 속한 프로젝트만 표시됩니다.</p></div></header>
    {error && <div role="alert" className="error">{error} <button className="secondary" onClick={() => { setError(''); setData(null); setRevision(v => v + 1) }}>다시 조회</button></div>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {page === 'dashboard' && <>
      <MonitoringDashboard tenantId={tenant.id} refreshKey={jobsRevision} onExpired={onExpired} onOpenJob={setOpenJobId} />
      <section className="panel recent-jobs">
        <div className="panel-title"><h3>최근 처리 작업</h3><span>{recentJobs.data ? `${recentJobs.data.total}건` : '조회 중'}</span></div>
        {recentJobs.error && <p role="alert" className="error">{recentJobs.error}</p>}
        {recentJobs.data?.total === 0 && <p className="empty">아직 업로드한 CSV가 없습니다. 프로젝트 상세에서 CSV를 업로드하세요.</p>}
        {recentJobs.data && recentJobs.data.items.length > 0 && <JobTable jobs={recentJobs.data.items} showProject onOpen={setOpenJobId} />}
      </section>
    </>}
    {page === 'projects' && <form className="panel project-form" onSubmit={create}>
      <h3>프로젝트 만들기</h3>
      <label>프로젝트 이름<input required maxLength={100} value={name} onChange={e => setName(e.target.value)} /></label>
      <label>설명 (선택)<textarea maxLength={1000} rows={2} value={description} onChange={e => setDescription(e.target.value)} /></label>
      <button disabled={busy || !name.trim()}>{busy ? '저장 중…' : '프로젝트 생성'}</button>
    </form>}
    <section className="panel">
      <div className="panel-title"><h3>프로젝트 목록</h3><span>{data ? `${data.total}개` : '조회 중'}</span></div>
      {!data && !error && <p role="status">불러오는 중…</p>}
      {data?.total === 0 && <p className="empty">아직 프로젝트가 없습니다. 프로젝트 메뉴에서 첫 프로젝트를 만들어보세요.</p>}
      {data && data.items.length > 0 && <div className="table-scroll"><table><thead><tr><th>프로젝트</th><th>설명</th><th>생성일</th></tr></thead><tbody>
        {data.items.map(project => <tr key={project.id}><td><button disabled={detailBusy} className="text-button" onClick={() => void openProject(project.id)}>{project.name}</button></td><td>{project.description || '—'}</td><td>{new Date(project.created_at).toLocaleDateString('ko-KR')}</td></tr>)}
      </tbody></table></div>}
      {data && data.total > 20 && <div className="pagination"><button disabled={offset === 0} onClick={() => { setOffset(v => v - 20); setData(null) }}>이전</button><span>{Math.floor(offset / 20) + 1} 페이지</span><button disabled={offset + 20 >= data.total} onClick={() => { setOffset(v => v + 20); setData(null) }}>다음</button></div>}
    </section>
    {detailBusy && <p role="status">프로젝트 상세 조회 중…</p>}
    {selected && <section className="panel detail" aria-label="프로젝트 상세"><div className="panel-title"><h3>{selected.name}</h3><button className="secondary" onClick={() => setSelected(null)}>상세 닫기</button></div><p>{selected.description || '등록된 설명이 없습니다.'}</p><p className="subtext">생성: {new Date(selected.created_at).toLocaleString('ko-KR')}</p>
      <UploadForm tenantId={tenant.id} projectId={selected.id} onUploaded={uploaded} onError={handleError} />
      <h4>이 프로젝트의 작업</h4>
      <ProjectJobs tenantId={tenant.id} projectId={selected.id} refreshKey={jobsRevision} onExpired={onExpired} onOpen={setOpenJobId} />
    </section>}
    {openJobId && <JobDetailPanel key={openJobId} tenantId={tenant.id} jobId={openJobId} onClose={() => setOpenJobId(null)} onExpired={onExpired} />}
  </>
}

function App() {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [tenantId, setTenantId] = useState('')
  const [loggingOut, setLoggingOut] = useState(false)
  useEffect(() => {
    const controller = new AbortController()
    api<User>('/auth/me', { signal: controller.signal }).then(setUser).catch(error => {
      if (!controller.signal.aborted && !(error instanceof ApiError && error.status === 401)) setError(message(error))
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [])
  async function logout() {
    setLoggingOut(true); setError('')
    try { await api('/auth/logout', { method: 'POST' }); setUser(null); setTenantId('') }
    catch (error) { setError(message(error)) }
    finally { setLoggingOut(false) }
  }
  const expire = useCallback(() => { setUser(null); setTenantId('') }, [])
  if (loading) return <main className="loading" role="status">로그인 상태 확인 중…</main>
  if (!user) return <>{error && <p className="error" role="alert">{error}</p>}<Login onLogin={value => { setUser(value); setTenantId(''); setError('') }} /></>
  const tenant = user.tenants.find(t => t.id === tenantId) ?? user.tenants[0]
  return <main className="app">
    <aside className="sidebar"><h1>DataFlow <span>Hub</span></h1>
      <label className="workspace">WORKSPACE<select aria-label="조직 선택" value={tenant?.id ?? ''} onChange={e => setTenantId(e.target.value)}>{user.tenants.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
      <p className="sidebar-description">팀의 데이터를 위한<br />독립된 작업 공간</p>
      <div className="sidebar-footer"><strong>{user.name}</strong><p>{user.email}</p><button className="secondary" disabled={loggingOut} onClick={() => void logout()}>{loggingOut ? '로그아웃 중…' : '로그아웃'}</button></div>
    </aside>
    <section className="content">{error && <p className="error" role="alert">{error}</p>}{tenant ? <Workspace key={`${user.id}:${tenant.id}`} tenant={tenant} onExpired={expire} /> : <p>소속된 조직이 없습니다. 관리자에게 문의해 주세요.</p>}</section>
  </main>
}

export default App
