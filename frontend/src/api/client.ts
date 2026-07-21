import type { ApiDefinition, ApiTemplate, Project, TestFlow, TestRun } from '../types'

const API_ROOT = import.meta.env.VITE_API_ROOT || '/api/v1'

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  })
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new Error(payload?.detail || `请求失败 (${response.status})`)
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
  definitions: {
    list: (projectId?: string) =>
      request<ApiDefinition[]>(`/apis${projectId ? `?project_id=${projectId}` : ''}`),
    create: (payload: Partial<ApiDefinition>) =>
      request<ApiDefinition>('/apis', { method: 'POST', body: JSON.stringify(payload) }),
    update: (id: string, payload: Partial<ApiDefinition>) =>
      request<ApiDefinition>(`/apis/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    remove: (id: string) => request<void>(`/apis/${id}`, { method: 'DELETE' }),
    execute: (id: string, inputs: object, requestOverride: object) =>
      request<{ request: object; response: object }>(`/apis/${id}/execute`, {
        method: 'POST',
        body: JSON.stringify({ inputs, request: requestOverride }),
      }),
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
