import type {
  ApiDefinition,
  ApiTemplate,
  ImportSession,
  AssertionDefinition,
  AssertionProfile,
  Project,
  TestFlow,
  TestPlan,
  TestPlanRun,
  TestRun,
} from '../types'

const API_ROOT = import.meta.env.VITE_API_ROOT || '/api/v1'

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail
    if (typeof detail === 'object' && detail) {
      const message = typeof detail.message === 'string' ? detail.message : '请求失败'
      const errors = Array.isArray(detail.errors) ? `：${detail.errors.join('；')}` : ''
      throw new Error(`${message}${errors}`)
    }
    throw new Error(detail || `请求失败 (${response.status})`)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export const api = {
  projects: {
    list: () => request<Project[]>('/projects'),
    create: (payload: Partial<Project>) =>
      request<Project>('/projects', { method: 'POST', body: JSON.stringify(payload) }),
    update: (id: string, payload: Partial<Project>) =>
      request<Project>(`/projects/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    remove: (id: string) => request<void>(`/projects/${id}`, { method: 'DELETE' }),
  },
  imports: {
    preview: (file: File, projectId?: string) => request<ImportSession>(
      `/imports/preview${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`,
      {
        method: 'POST',
        body: file,
        headers: {
          'Content-Type': file.type || 'application/zip',
          'X-Import-Filename': encodeURIComponent(file.name),
          'X-Import-Source': 'workspace',
        },
      },
    ),
    get: (id: string) => request<ImportSession>(`/imports/${id}`),
    approve: (id: string) => request<ImportSession>(`/imports/${id}/approve`, { method: 'POST' }),
    reject: (id: string) => request<ImportSession>(`/imports/${id}/reject`, { method: 'POST' }),
    oneClick: (file: File, projectId?: string) => request<ImportSession>(
      `/imports/one-click${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ''}`,
      {
        method: 'POST',
        body: file,
        headers: {
          'Content-Type': file.type || 'application/zip',
          'X-Import-Filename': encodeURIComponent(file.name),
          'X-Import-Source': 'external',
        },
      },
    ),
  },
  definitions: {
    list: (projectId?: string) =>
      request<ApiDefinition[]>(`/apis${projectId ? `?project_id=${projectId}` : ''}`),
    create: (payload: Partial<ApiDefinition>) =>
      request<ApiDefinition>('/apis', { method: 'POST', body: JSON.stringify(payload) }),
    update: (id: string, payload: Partial<ApiDefinition>) =>
      request<ApiDefinition>(`/apis/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    remove: (id: string) => request<void>(`/apis/${id}`, { method: 'DELETE' }),
    execute: (id: string, inputs: object, requestOverride: object) =>
      request<{ request: object; response: object; validation: object }>(`/apis/${id}/execute`, {
        method: 'POST',
        body: JSON.stringify({ inputs, request: requestOverride }),
      }),
  },
  assertionDefinitions: {
    list: (projectId?: string) =>
      request<AssertionDefinition[]>(
        `/assertion-definitions${projectId ? `?project_id=${projectId}` : ''}`,
      ),
    create: (payload: Partial<AssertionDefinition>) =>
      request<AssertionDefinition>('/assertion-definitions', {
        method: 'POST', body: JSON.stringify(payload),
      }),
    update: (id: string, payload: Partial<AssertionDefinition>) =>
      request<AssertionDefinition>(`/assertion-definitions/${id}`, {
        method: 'PATCH', body: JSON.stringify(payload),
      }),
    remove: (id: string) =>
      request<void>(`/assertion-definitions/${id}`, { method: 'DELETE' }),
  },
  assertionProfiles: {
    list: (projectId?: string) =>
      request<AssertionProfile[]>(
        `/assertion-profiles${projectId ? `?project_id=${projectId}` : ''}`,
      ),
    create: (payload: Partial<AssertionProfile>) =>
      request<AssertionProfile>('/assertion-profiles', {
        method: 'POST', body: JSON.stringify(payload),
      }),
    update: (id: string, payload: Partial<AssertionProfile>) =>
      request<AssertionProfile>(`/assertion-profiles/${id}`, {
        method: 'PATCH', body: JSON.stringify(payload),
      }),
    remove: (id: string) =>
      request<void>(`/assertion-profiles/${id}`, { method: 'DELETE' }),
  },
  templates: {
    list: (projectId?: string) =>
      request<ApiTemplate[]>(
        `/api-templates${projectId ? `?project_id=${projectId}` : ''}`,
      ),
    create: (payload: Partial<ApiTemplate>) =>
      request<ApiTemplate>('/api-templates', {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    update: (id: string, payload: Partial<ApiTemplate>) =>
      request<ApiTemplate>(`/api-templates/${id}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      }),
    remove: (id: string) =>
      request<void>(`/api-templates/${id}`, { method: 'DELETE' }),
  },
  flows: {
    list: (projectId?: string) =>
      request<TestFlow[]>(`/flows${projectId ? `?project_id=${projectId}` : ''}`),
    create: (payload: Partial<TestFlow>) =>
      request<TestFlow>('/flows', { method: 'POST', body: JSON.stringify(payload) }),
    update: (id: string, payload: Partial<TestFlow>) =>
      request<TestFlow>(`/flows/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    remove: (id: string) => request<void>(`/flows/${id}`, { method: 'DELETE' }),
  },
  testPlans: {
    list: (projectId?: string) =>
      request<TestPlan[]>(`/test-plans${projectId ? `?project_id=${projectId}` : ''}`),
    create: (payload: Partial<TestPlan>) =>
      request<TestPlan>('/test-plans', { method: 'POST', body: JSON.stringify(payload) }),
    update: (id: string, payload: Partial<TestPlan>) =>
      request<TestPlan>(`/test-plans/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    remove: (id: string) => request<void>(`/test-plans/${id}`, { method: 'DELETE' }),
    runs: (id: string) => request<TestPlanRun[]>(`/test-plans/${id}/runs`),
    run: (id: string, inputs: object = {}) =>
      request<TestPlanRun>(`/test-plans/${id}/runs`, {
        method: 'POST', body: JSON.stringify({ inputs }),
      }),
    getRun: (runId: string) => request<TestPlanRun>(`/test-plan-runs/${runId}`),
  },
  runs: {
    list: (flowId?: string) =>
      request<TestRun[]>(`/runs${flowId ? `?flow_id=${flowId}` : ''}`),
    create: (flowId: string, inputs: object) =>
      request<TestRun>(`/flows/${flowId}/runs`, {
        method: 'POST',
        body: JSON.stringify({ inputs }),
      }),
  },
}
