import { ref, watch } from 'vue'

import { api } from '../api/client'
import type { Project } from '../types'

const projects = ref<Project[]>([])
const projectId = ref('')
let loadingPromise: Promise<void> | null = null

watch(projectId, (value) => {
  if (typeof window !== 'undefined' && value) {
    window.localStorage.setItem('qa-platform.project-id', value)
  }
})

async function loadProjects() {
  if (loadingPromise) return loadingPromise
  loadingPromise = (async () => {
    const loaded = await api.projects.list()
    projects.value = loaded
    const savedId = typeof window !== 'undefined'
      ? window.localStorage.getItem('qa-platform.project-id')
      : null
    if (!loaded.some((project) => project.id === projectId.value)) {
      projectId.value = loaded.find((project) => project.id === savedId)?.id
        || loaded[0]?.id || ''
    }
  })().finally(() => {
    loadingPromise = null
  })
  return loadingPromise
}

async function refreshProjects() {
  loadingPromise = null
  return loadProjects()
}

export function useProjectContext() {
  return { projects, projectId, loadProjects, refreshProjects }
}
