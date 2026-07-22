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
  assertion_profile_id: string | null
  name: string
  protocol: 'http' | 'ws'
  description: string
  request: Record<string, unknown>
  parameters: Record<string, unknown>[]
  examples: Record<string, unknown>[]
  response_variants: Record<string, unknown>[]
  created_at: string
  updated_at: string
}

export interface AssertionDefinition {
  id: string
  project_id: string
  name: string
  engine: 'path' | 'json_schema' | 'expression'
  description: string
  config: Record<string, unknown>
  default_params: Record<string, unknown>
  severity: 'error' | 'warning'
  message: string
  created_at: string
  updated_at: string
}

export interface AssertionProfile {
  id: string
  project_id: string
  name: string
  protocol: 'http' | 'ws'
  description: string
  is_default: boolean
  bindings: Record<string, unknown>[]
  usage_count: number
  created_at: string
  updated_at: string
}

export interface AssertionResult {
  assertion_id: string
  name: string
  engine: string
  passed: boolean
  severity: 'error' | 'warning'
  message: string
  actual: unknown
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
  disabled_assertion_ids: string[]
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
  assertion_results: AssertionResult[]
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
