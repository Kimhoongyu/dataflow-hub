import { useCallback, useEffect, useState } from 'react'
import './App.css'
import NewJobModal from './NewJobModal'
import type { Job, NewJobInput } from './types'

const initialJobs: Job[] = [
  { id: '1', name: 'sales-report-september.csv', project: 'Retail Analytics', type: 'Aggregation', status: 'Completed', time: '2 minutes ago' },
  { id: '2', name: 'passenger-feedback.csv', project: 'Customer Insights', type: 'Cleansing', status: 'Processing', time: '8 minutes ago' },
  { id: '3', name: 'inventory-data.csv', project: 'Supply Operations', type: 'Validation', status: 'Queued', time: '14 minutes ago' },
]

// Local stand-in for a future backend call (e.g. POST /jobs).
function createJob(input: NewJobInput): Job {
  return { ...input, id: crypto.randomUUID(), status: 'Queued', time: 'Just now' }
}

function App() {
  const [jobs, setJobs] = useState<Job[]>(initialJobs)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    if (!toast) return
    const timer = setTimeout(() => setToast(null), 3000)
    return () => clearTimeout(timer)
  }, [toast])

  const closeModal = useCallback(() => setIsModalOpen(false), [])

  const handleCreate = (input: NewJobInput) => {
    const job = createJob(input)
    setJobs((prev) => [job, ...prev])
    setIsModalOpen(false)
    setToast(`"${job.name}" was added to the queue.`)
  }

  return (
    <main className="app">
      <aside className="sidebar">
        <h1>DataFlow <span>Hub</span></h1>
        <p className="workspace">WORKSPACE<br /><strong>Demo Organization</strong></p>

        <nav>
          <a className="active" href="#dashboard">Dashboard</a>
          <a href="#projects">Projects</a>
          <a href="#jobs">Processing Jobs</a>
          <a href="#storage">Storage</a>
        </nav>

        <div className="sidebar-footer">Signed in as<br /><strong>Hoon-gyu Kim</strong></div>
      </aside>

      <section className="content">
        <header>
          <div>
            <p className="eyebrow">OVERVIEW</p>
            <h2>Good morning, Hoon-gyu</h2>
            <p className="subtext">Monitor your projects and data-processing jobs.</p>
          </div>
          <button onClick={() => setIsModalOpen(true)}>+ New processing job</button>
        </header>

        <section className="cards">
          <article><p>Active projects</p><strong>3</strong><small>All services healthy</small></article>
          <article><p>Jobs processed</p><strong>128</strong><small>+18 this week</small></article>
          <article><p>Success rate</p><strong>98.4%</strong><small>Last 30 days</small></article>
        </section>

        <section className="panel">
          <div className="panel-title">
            <div><h3>Recent processing jobs</h3><p>Latest uploads and processing status</p></div>
            <a href="#all">View all</a>
          </div>

          <div className="table">
            <div className="row heading"><span>FILE</span><span>PROJECT</span><span>STATUS</span><span>UPDATED</span></div>
            {jobs.map((job) => (
              <div className="row" key={job.id}>
                <strong>{job.name}</strong>
                <span>{job.project}</span>
                <span className={`status ${job.status.toLowerCase()}`}>{job.status}</span>
                <span>{job.time}</span>
              </div>
            ))}
          </div>
        </section>
      </section>

      {isModalOpen && <NewJobModal onCancel={closeModal} onSubmit={handleCreate} />}
      {toast && <div className="toast" role="status">{toast}</div>}
    </main>
  )
}

export default App