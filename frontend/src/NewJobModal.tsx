import { useEffect, useState, type FormEvent } from 'react'
import { JOB_TYPES, PROJECTS, type NewJobInput } from './types'

interface Props {
  onCancel: () => void
  onSubmit: (input: NewJobInput) => void
}

type Errors = Partial<Record<keyof NewJobInput, string>>

const emptyForm: NewJobInput = { name: '', project: '', type: 'Cleansing', notes: '' }

function validate(form: NewJobInput): Errors {
  const errors: Errors = {}
  if (!form.name.trim()) errors.name = 'File name is required.'
  if (!form.project) errors.project = 'Select a project.'
  return errors
}

function NewJobModal({ onCancel, onSubmit }: Props) {
  const [form, setForm] = useState<NewJobInput>(emptyForm)
  const [errors, setErrors] = useState<Errors>({})

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onCancel])

  const update = <K extends keyof NewJobInput>(key: K, value: NewJobInput[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
    setErrors((prev) => ({ ...prev, [key]: undefined }))
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    const nextErrors = validate(form)
    if (Object.keys(nextErrors).length > 0) {
      setErrors(nextErrors)
      return
    }
    onSubmit({ ...form, name: form.name.trim(), notes: form.notes.trim() })
  }

  return (
    <div className="modal-backdrop" onMouseDown={onCancel}>
      <form
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-job-title"
        onMouseDown={(e) => e.stopPropagation()}
        onSubmit={handleSubmit}
        noValidate
      >
        <h3 id="new-job-title">New processing job</h3>
        <p className="modal-subtext">The job will be added to the queue.</p>

        <label>
          File name
          <input
            autoFocus
            value={form.name}
            placeholder="e.g. orders-october.csv"
            onChange={(e) => update('name', e.target.value)}
            aria-invalid={!!errors.name}
          />
          {errors.name && <span className="field-error">{errors.name}</span>}
        </label>

        <label>
          Project
          <select
            value={form.project}
            onChange={(e) => update('project', e.target.value)}
            aria-invalid={!!errors.project}
          >
            <option value="">Select a project</option>
            {PROJECTS.map((p) => <option key={p} value={p}>{p}</option>)}
          </select>
          {errors.project && <span className="field-error">{errors.project}</span>}
        </label>

        <label>
          Job type
          <select value={form.type} onChange={(e) => update('type', e.target.value as NewJobInput['type'])}>
            {JOB_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>

        <label>
          Notes <small>(optional)</small>
          <textarea rows={3} value={form.notes} onChange={(e) => update('notes', e.target.value)} />
        </label>

        <div className="modal-actions">
          <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
          <button type="submit">Create job</button>
        </div>
      </form>
    </div>
  )
}

export default NewJobModal
