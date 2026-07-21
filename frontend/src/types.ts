export interface Project {
  id: string
  name: string
  description: string
  variables: Record<string, unknown>
  created_at: string
  updated_at: string
}

export interface ApiDefinition {
  id: string
  project_id: string
  template_id: string | null
  name: string
  protocol: 'http' | 'ws'
  description: string
  request: Record<string, unknown>
  parameters: Record<string, unknown>[]
  examples: Record<string, unknown>[]
  created_at: string
  updated_at: string
}

export interface ApiTemplate {
  id: string
  project_id: string
  name: string
  protocol: 'http' | 'ws'
  description: string
  request: Record<string, unknown>
  parameters: Record<string, unknown>[]
  examples: Record<string, unknown>[]
  usage_count: number
  created_at: string
  updated_at: string
}

export interface RetryPolicy {
  max_attempts: number
  interval_ms: number
  backoff_multiplier: number
}

export interface FlowStep {
  id: string
  name: string
  api_id: string
  enabled: boolean
  request: Record<string, unknown>
  assertions: Record<string, unknown>[]
  extractors: Record<string, unknown>[]
  retry: RetryPolicy
}

export interface TestFlow {
  id: string
  project_id: string
  name: string
  description: string
  variables: Record<string, unknown>
  steps: FlowStep[]
  created_at: string
  updated_at: string
}

export interface StepRun {
  id: string
  step_id: string
  step_name: string
  position: number
  attempt: number
  status: string
  duration_ms: number
  request_snapshot: Record<string, unknown>
  response_snapshot: Record<string, unknown> | null
  extracted: Record<string, unknown>
  error: string | null
}

export interface TestRun {
  id: string
  flow_id: string
  status: string
  inputs: Record<string, unknown>
  context: Record<string, unknown>
  error: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
  step_runs: StepRun[]
}
