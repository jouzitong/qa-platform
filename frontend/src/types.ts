export interface Project {
  id: string
  name: string
  description: string
  variables: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type ImportAction = 'create' | 'update' | 'unchanged'

export interface ImportPreviewItem {
  type: string
  key: string
  name: string
  action: ImportAction
  changes: string[]
}

export interface ImportSession {
  id: string
  project_id: string | null
  status: 'pending' | 'approved' | 'applied' | 'rejected' | 'failed'
  filename: string
  archive_format: string
  package_version: string
  source: Record<string, unknown>
  preview: {
    package_version?: string
    target_project_id?: string | null
    project?: Record<string, unknown>
    summary?: Record<string, number>
    items?: ImportPreviewItem[]
  }
  errors: string[]
  warnings: string[]
  created_at: string
  updated_at: string
  reviewed_at: string | null
  applied_at: string | null
}

export interface ApiDefinition {
  id: string
  project_id: string
  key: string
  group_path: string
  template_id: string | null
  success_assertion_id: string | null
  name: string
  protocol: 'http' | 'ws'
  description: string
  request: Record<string, unknown>
  request_schema: Record<string, unknown>
  response_schema: Record<string, unknown>
  response_unpack?: Record<string, unknown>
  parameters: Record<string, unknown>[]
  examples: Record<string, unknown>[]
  success_contract: Record<string, unknown>
  response_variants: Record<string, unknown>[]
  created_at: string
  updated_at: string
}

export interface ApiGroup {
  id: string
  project_id: string
  path: string
  name: string
  created_at: string
  updated_at: string
}

export interface AssertionDefinition {
  id: string
  project_id: string
  key: string
  name: string
  engine: 'path' | 'json_schema' | 'expression'
  description: string
  config: Record<string, unknown>
  default_params: Record<string, unknown>
  severity: 'success' | 'error' | 'warning'
  message: string
  created_at: string
  updated_at: string
}

export interface AssertionResult {
  assertion_id: string
  name: string
  engine: string
  passed: boolean
  severity: 'success' | 'error' | 'warning'
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
  key: string
  name: string
  description: string
  variables: Record<string, unknown>
  steps: FlowStep[]
  created_at: string
  updated_at: string
}

export type TestPlanItemType = 'api' | 'flow'

export interface TestPlanItem {
  id: string
  type: TestPlanItemType
  target_id: string
  enabled: boolean
}

export interface TestPlan {
  id: string
  project_id: string
  key: string
  version: string
  name: string
  description: string
  items: TestPlanItem[]
  created_at: string
  updated_at: string
}

export interface TestPlanRun {
  id: string
  plan_id: string
  status: string
  inputs: Record<string, unknown>
  results: Record<string, unknown>[]
  total_count: number
  passed_count: number
  failed_count: number
  error: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
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
