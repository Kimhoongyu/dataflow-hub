import { useEffect, useRef, useState } from 'react'
import type { Monitoring, Period } from './api'
import { useMonitoring } from './useMonitoring'

const PERIOD_LABEL: Record<Period, string> = { '24h': '24시간', '7d': '7일', '30d': '30일' }
const num = (n: number) => n.toLocaleString('ko-KR')
const pct = (v: number | null) => v === null ? '—' : `${(v * 100).toFixed(1)}%`
const duration = (ms: number | null) => ms === null ? '—' : ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}초`
const age = (s: number | null) => s === null ? '없음' : s < 60 ? `${Math.round(s)}초` : s < 3600 ? `${Math.round(s / 60)}분` : `${(s / 3600).toFixed(1)}시간`
const time = (value: string | null) => value ? new Date(value).toLocaleString('ko-KR') : '—'

type Level = 'good' | 'warning' | 'critical'
const ICON: Record<Level, string> = { good: '●', warning: '▲', critical: '✕' }

function healthChecks(queue: Monitoring['queue']): { level: Level; label: string }[] {
  const checks: { level: Level; label: string }[] = [queue.workers_alive > 0
    ? { level: 'good', label: `Worker ${queue.workers_alive}개 정상` }
    : { level: 'critical', label: '동작 중인 Worker 없음 — 작업이 처리되지 않습니다' }]
  if (queue.stuck > 0) checks.push({ level: 'warning', label: `멈춘 작업 ${queue.stuck}건 (자동 복구 대기)` })
  if ((queue.oldest_queued_seconds ?? 0) > 300) checks.push({ level: 'warning', label: `대기 지연: 가장 오래 기다린 작업 ${age(queue.oldest_queued_seconds)}` })
  if (checks.length === 1 && queue.workers_alive > 0) checks.push({ level: 'good', label: '대기열 정상' })
  return checks
}

/** Clean integer ticks (1/2/5 × 10ⁿ steps) for count axes. */
function scale(max: number): { top: number; ticks: number[] } {
  if (max <= 0) return { top: 4, ticks: [0, 2, 4] }
  const raw = max / 4
  const power = 10 ** Math.floor(Math.log10(raw))
  const step = Math.max(1, [1, 2, 5, 10].map(f => f * power).find(s => s >= raw) ?? power * 10)
  const top = Math.ceil(max / step) * step
  return { top, ticks: Array.from({ length: top / step + 1 }, (_, i) => i * step) }
}

// Rounded data-end on top, square at the baseline.
function topRounded(x: number, y: number, w: number, h: number) {
  const r = Math.min(4, h, w / 2)
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`
}

function TrendChart({ data }: { data: Monitoring }) {
  const box = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(640)
  const [hover, setHover] = useState<number | null>(null)
  const [asTable, setAsTable] = useState(false)
  useEffect(() => {
    const element = box.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(280, entry.contentRect.width)))
    observer.observe(element)
    return () => observer.disconnect()
  }, [asTable])  // the plot element is remounted when switching back from the table

  const series = data.timeseries
  const hourly = data.bucket === 'hour'
  const short = (start: string) => hourly ? `${start.slice(11, 13)}시` : `${Number(start.slice(5, 7))}/${Number(start.slice(8, 10))}`
  const full = (start: string) => `${Number(start.slice(5, 7))}/${Number(start.slice(8, 10))}${hourly ? ` ${start.slice(11, 16)}` : ''}`
  const H = 200, top = 12, bottom = 26, left = 36, right = 8, GAP = 2
  const plotW = width - left - right, plotH = H - top - bottom, base = top + plotH
  const { top: max, ticks } = scale(Math.max(0, ...series.map(b => b.completed + b.failed)))
  const band = plotW / Math.max(series.length, 1)
  const barW = Math.min(24, Math.max(2, band * 0.6))
  const every = Math.ceil(series.length / Math.max(2, Math.floor(plotW / 56)))
  const empty = series.every(b => b.completed + b.failed === 0)
  const hovered = hover === null ? null : series[hover]

  return <div className="chart">
    <div className="chart-head">
      <ul className="legend" aria-label="범례">
        <li><span className="swatch completed" />완료</li>
        <li><span className="swatch failed" />실패</li>
      </ul>
      <button className="secondary small" onClick={() => setAsTable(v => !v)}>{asTable ? '차트로 보기' : '표로 보기'}</button>
    </div>
    {asTable ? <div className="table-scroll"><table><thead><tr><th>구간 ({data.timezone})</th><th className="num">완료</th><th className="num">실패</th></tr></thead><tbody>
      {series.map(b => <tr key={b.start}><td>{full(b.start)}</td><td className="num">{num(b.completed)}</td><td className="num">{num(b.failed)}</td></tr>)}
    </tbody></table></div>
      : <div className="chart-plot" ref={box}>
        <svg width={width} height={H} role="img" aria-label={`${PERIOD_LABEL[data.period]} 처리 추이: 완료 ${data.summary.completed}건, 실패 ${data.summary.failed}건`}>
          {ticks.map(t => <g key={t}>
            <line x1={left} x2={width - right} y1={base - t / max * plotH} y2={base - t / max * plotH} className="grid" />
            <text x={left - 8} y={base - t / max * plotH} className="tick" textAnchor="end" dominantBaseline="middle">{num(t)}</text>
          </g>)}
          {series.map((b, i) => {
            const x = left + i * band + (band - barW) / 2
            const cH = b.completed / max * plotH
            const fH = b.failed / max * plotH
            const fTop = base - cH - fH
            return <g key={b.start}>
              {hover === i && <rect x={left + i * band} y={top} width={band} height={plotH} className="hover-band" />}
              {b.completed > 0 && (b.failed > 0
                ? <rect x={x} y={base - cH} width={barW} height={cH} className="bar completed" />
                : <path d={topRounded(x, base - cH, barW, cH)} className="bar completed" />)}
              {b.failed > 0 && <path d={topRounded(x, fTop, barW, Math.max(1.5, fH - (b.completed > 0 ? GAP : 0)))} className="bar failed" />}
              {i % every === 0 && <text x={left + i * band + band / 2} y={H - 8} className="tick" textAnchor="middle">{short(b.start)}</text>}
              <rect x={left + i * band} y={top} width={band} height={plotH} fill="transparent"
                onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
            </g>
          })}
        </svg>
        {empty && <p className="chart-empty">이 기간에 끝난 작업이 없습니다.</p>}
        {hovered && hover !== null && <div className="chart-tooltip" role="status"
          // Beside the column, inside the plot, flipping sides past the midpoint so it never covers the header.
          style={left + hover * band + band / 2 > width / 2
            ? { right: width - (left + hover * band) + 6, top }
            : { left: left + (hover + 1) * band + 6, top }}>
          <strong>{full(hovered.start)}</strong>
          <span><i className="swatch completed" />완료 {num(hovered.completed)}건</span>
          <span><i className="swatch failed" />실패 {num(hovered.failed)}건</span>
        </div>}
      </div>}
  </div>
}

export function MonitoringDashboard({ tenantId, refreshKey, onExpired, onOpenJob }: {
  tenantId: string; refreshKey: number; onExpired: () => void; onOpenJob: (id: string) => void
}) {
  const [period, setPeriod] = useState<Period>('24h')
  const { data, error } = useMonitoring(tenantId, period, refreshKey, onExpired)
  const s = data?.summary, q = data?.queue
  return <section className="monitoring" aria-label="운영 현황">
    <div className="monitoring-head">
      <h3>운영 현황</h3>
      <div className="segmented" role="group" aria-label="기간">
        {(Object.keys(PERIOD_LABEL) as Period[]).map(p => <button key={p} aria-pressed={period === p} className={period === p ? 'active' : 'secondary'} onClick={() => setPeriod(p)}>{PERIOD_LABEL[p]}</button>)}
      </div>
    </div>
    {error && <p role="alert" className="error">{error}</p>}
    {!data && !error && <p role="status">운영 현황 불러오는 중…</p>}
    {data && s && q && <>
      <ul className="health" aria-label="시스템 상태">
        {healthChecks(q).map(check => <li key={check.label} className={check.level}><span aria-hidden="true">{ICON[check.level]}</span>{check.label}</li>)}
      </ul>
      <div className="kpis">
        <article><p>업로드</p><strong>{num(s.uploads)}</strong><small>최근 {PERIOD_LABEL[period]}</small></article>
        <article><p>완료</p><strong>{num(s.completed)}</strong><small>종료 시각 기준</small></article>
        <article><p>실패</p><strong>{num(s.failed)}</strong><small>재시도 {num(s.retries)}회 발생</small></article>
        <article><p>성공률</p><strong>{pct(s.success_rate)}</strong><small>완료 ÷ (완료 + 실패)</small></article>
        <article><p>평균 처리 시간</p><strong>{duration(s.avg_duration_ms)}</strong><small>p95 {duration(s.p95_duration_ms)}</small></article>
        <article><p>대기열</p><strong>{num(q.queued)}</strong><small>처리 중 {num(q.processing)} · 최장 대기 {age(q.oldest_queued_seconds)}</small></article>
      </div>
      <section className="panel">
        <div className="panel-title"><h3>처리 추이</h3><span className="subtext">{data.bucket === 'hour' ? '시간별' : '일별'} · {data.timezone}</span></div>
        <TrendChart data={data} />
      </section>
      <div className="monitoring-grid">
        <section className="panel">
          <div className="panel-title"><h3>프로젝트별 현황</h3></div>
          {data.projects.length === 0 ? <p className="empty">프로젝트가 없습니다.</p> : <div className="table-scroll"><table><thead><tr>
            <th>프로젝트</th><th className="num">업로드</th><th className="num">완료</th><th className="num">실패</th><th className="num">성공률</th><th className="num">진행 중</th><th>마지막 처리</th>
          </tr></thead><tbody>
            {data.projects.map(p => <tr key={p.id}><td>{p.name}</td><td className="num">{num(p.uploads)}</td><td className="num">{num(p.completed)}</td>
              <td className="num">{num(p.failed)}</td><td className="num">{pct(p.success_rate)}</td><td className="num">{num(p.active)}</td><td>{time(p.last_finished_at)}</td></tr>)}
          </tbody></table></div>}
        </section>
        <section className="panel">
          <div className="panel-title"><h3>최근 오류</h3>
            {data.error_codes.length > 0 && <ul className="codes">{data.error_codes.map(c => <li key={c.error_code}>{c.error_code} <strong>{num(c.count)}</strong></li>)}</ul>}
          </div>
          {data.recent_errors.length === 0 ? <p className="empty">이 기간에 발생한 오류가 없습니다.</p> : <div className="table-scroll"><table><thead><tr>
            <th>시각</th><th>파일</th><th>상태</th><th>오류</th>
          </tr></thead><tbody>
            {data.recent_errors.map(e => <tr key={e.job_id}>
              <td>{time(e.occurred_at)}</td>
              <td><button className="text-button" onClick={() => onOpenJob(e.job_id)}>{e.file_name}</button><small className="cell-sub">{e.project_name}</small></td>
              <td>{e.status === 'failed' ? <span className="status failed">실패</span> : <span className="status queued">재시도 대기</span>}<small className="cell-sub">{e.attempt}회 시도</small></td>
              <td><code>{e.error_code}</code><small className="cell-sub">{e.error_message}</small></td>
            </tr>)}
          </tbody></table></div>}
        </section>
      </div>
    </>}
  </section>
}
