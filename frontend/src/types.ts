export type JobStatus = 'Completed' | 'Processing' | 'Queued'

export type JobType = 'Cleansing' | 'Transformation' | 'Validation' | 'Aggregation'

export interface Job {
  id: string
  name: string
  project: string
  type: JobType
  status: JobStatus
  notes?: string
  time: string
}

export interface NewJobInput {
  name: string
  project: string
  type: JobType
  notes: string
}

export const PROJECTS = ['Retail Analytics', 'Customer Insights', 'Supply Operations']

export const JOB_TYPES: JobType[] = ['Cleansing', 'Transformation', 'Validation', 'Aggregation']
