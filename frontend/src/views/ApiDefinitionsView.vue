<script setup lang="ts">
import { Delete, Edit, Search, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, reactive, ref, watch } from 'vue'

import { api } from '../api/client'
import ApiParametersEditor from '../components/ApiParametersEditor.vue'
import PaginationBar from '../components/PaginationBar.vue'
import { useProjectContext } from '../state/project'
import type { ApiDefinition, ApiTemplate, AssertionProfile } from '../types'
import { parseJson, pretty } from '../utils'

const definitions = ref<ApiDefinition[]>([])
const templates = ref<ApiTemplate[]>([])
const profiles = ref<AssertionProfile[]>([])
const { projectId } = useProjectContext()
const activeTab = ref<'apis' | 'templates'>('apis')
const dialog = ref(false)
const templateDialog = ref(false)
const executeDialog = ref(false)
const apiPage = ref(1)
const apiPageSize = ref(20)
const apiSearch = ref('')
const templatePage = ref(1)
const templatePageSize = ref(20)
const editingId = ref('')
const editingTemplateId = ref('')
const executing = ref<ApiDefinition | null>(null)
const executionResult = ref<object | null>(null)
const executeAdvancedOpen = ref<string[]>([])
const executeValues = reactive<Record<string, unknown>>({})
const pathParameterNames = ref<string[]>([])
const form = reactive({
  key: '', name: '', protocol: 'http' as 'http' | 'ws', template_id: null as string | null,
  assertion_profile_id: undefined as string | null | undefined,
  description: '', request: '{}',
  parameters: '[]', examples: '[]', success_contract: '{}', response_variants: '[]',
})
const templateForm = reactive({
  name: '', protocol: 'http' as 'http' | 'ws', description: '', request: '{}',
  parameters: '[]', examples: '[]',
})
const executeForm = reactive({ inputs: '{}', request: '{}' })
const availableTemplates = computed(() =>
  templates.value.filter((template) => template.protocol === form.protocol),
)
const availableProfiles = computed(() =>
  profiles.value.filter((profile) => profile.protocol === form.protocol),
)
const filteredDefinitions = computed(() => {
  const keyword = apiSearch.value.trim().toLocaleLowerCase()
  if (!keyword) return definitions.value
  return definitions.value.filter((definition) => (
    definition.name.toLocaleLowerCase().includes(keyword)
    || requestTarget(definition).toLocaleLowerCase().includes(keyword)
  ))
})
const pagedDefinitions = computed(() => filteredDefinitions.value.slice(
  (apiPage.value - 1) * apiPageSize.value, apiPage.value * apiPageSize.value,
))
const pagedTemplates = computed(() => templates.value.slice(
  (templatePage.value - 1) * templatePageSize.value, templatePage.value * templatePageSize.value,
))
const parameterItems = computed<Record<string, unknown>[]>({
  get: () => {
    try { return JSON.parse(form.parameters) as Record<string, unknown>[] }
    catch { return [] }
  },
  set: (value) => { form.parameters = pretty(value) },
})
const requestConfig = computed<Record<string, unknown>>(() => {
  try { return JSON.parse(form.request) as Record<string, unknown> }
  catch { return {} }
})
function protocolScheme(protocol: 'http' | 'ws') {
  return protocol === 'ws' ? 'ws' : 'http'
}

function withProtocol(value: string, protocol: 'http' | 'ws') {
  const address = value.trim()
  if (!address || address.startsWith('/') || address.includes('://')) return address
  if (address.startsWith('//')) return `${protocolScheme(protocol)}:${address}`
  return `${protocolScheme(protocol)}://${address}`
}

const defaultRequestBase = '{{ base_url }}'

function composeRequestEndpoint(
  base: unknown,
  path: unknown,
  protocol: 'http' | 'ws',
) {
  const normalizedBase = withProtocol(String(base || defaultRequestBase), protocol).replace(/\/$/, '')
  const normalizedPath = String(path || '').trim()
  if (!normalizedPath) return normalizedBase
  if (normalizedPath.includes('://')) return withProtocol(normalizedPath, protocol)
  return `${normalizedBase}/${normalizedPath.replace(/^\//, '')}`
}

function defaultHttpHeaders() {
  return {
    'X-trade-id': '{{ random.uuid(32) }}',
    Accept: 'application/json',
  }
}

const inheritedRequestBase = computed(() => {
  const request = findTemplate(form.template_id)?.request || {}
  return String(request.base_url || request.url || '')
})
const displayRequestBase = computed(() => withProtocol(inheritedRequestBase.value, form.protocol))
const requestAddress = computed(() => {
  const request = requestConfig.value
  const path = String(request.path || '')
  if (path) return path
  const url = String(request.url || '')
  if (inheritedRequestBase.value && url.startsWith(inheritedRequestBase.value))
    return url.slice(inheritedRequestBase.value.length) || '/'
  return withProtocol(url, form.protocol)
})
const requestAddressPlaceholder = computed(() => inheritedRequestBase.value
  ? (form.protocol === 'http' ? '/users/{user_id}' : '/channels/{channel_id}')
  : (form.protocol === 'http' ? '/users/{user_id}' : '/channels/{channel_id}'))
const requestMethod = computed(() => form.protocol === 'ws'
  ? 'WS'
  : String(requestConfig.value.method || 'GET').toUpperCase())
const requestEndpoint = computed(() => {
  const request = requestConfig.value
  const directUrl = String(request.url || '').trim()
  if (directUrl && !directUrl.startsWith('/')) return withProtocol(directUrl, form.protocol)
  const template = findTemplate(form.template_id)
  const base = request.base_url || template?.request.base_url || template?.request.url
  return composeRequestEndpoint(base, request.path || directUrl, form.protocol)
})

async function load() {
  if (!projectId.value) { definitions.value = []; templates.value = []; return }
  try {
    ;[definitions.value, templates.value, profiles.value] = await Promise.all([
      api.definitions.list(projectId.value), api.templates.list(projectId.value),
      api.assertionProfiles.list(projectId.value),
    ])
  }
  catch (error) { ElMessage.error((error as Error).message) }
}

function defaultRequest(protocol: 'http' | 'ws') {
  return protocol === 'http'
    ? { method: 'GET', path: '/health', headers: defaultHttpHeaders(), query: {} }
    : { path: '/', headers: {}, messages: [{ type: 'ping' }], receive_count: 1 }
}

function defaultSuccessContract(protocol: 'http' | 'ws') {
  return protocol === 'ws'
    ? { messages: { min: 1 }, body_schema: {} }
    : {
        status_codes: { min: 200, max: 299 },
        body_schema: {
          type: 'object', required: ['code', 'data'], properties: { code: { const: 0 } },
        },
      }
}

function defaultTemplateRequest(protocol: 'http' | 'ws') {
  return protocol === 'http'
    ? { base_url: '{{ base_url }}', headers: { 'Content-Type': 'application/json' }, timeout_seconds: 30 }
    : { base_url: '{{ base_url }}', headers: {}, timeout_seconds: 30 }
}

function mergeConfig(base: Record<string, unknown>, override: Record<string, unknown>) {
  const result: Record<string, unknown> = { ...base }
  for (const [key, value] of Object.entries(override)) {
    const current = result[key]
    if (value && current && typeof value === 'object' && typeof current === 'object'
      && !Array.isArray(value) && !Array.isArray(current)) {
      result[key] = mergeConfig(
        current as Record<string, unknown>, value as Record<string, unknown>,
      )
    } else result[key] = value
  }
  return result
}

function findTemplate(templateId: string | null) {
  return templates.value.find((template) => template.id === templateId)
}

const parameterLocations = [
  { value: 'path', label: 'Path' },
  { value: 'query', label: 'Query' },
  { value: 'header', label: 'Headers' },
  { value: 'body', label: 'Body' },
] as const

function effectiveParameters(definition: ApiDefinition) {
  const parameters = new Map<string, Record<string, unknown>>()
  const template = findTemplate(definition.template_id)
  for (const item of [...(template?.parameters || []), ...definition.parameters]) {
    const name = String(item.name || '').trim()
    const location = String(item.in || 'query')
    if (!name || !parameterLocations.some((item) => item.value === location)) continue
    parameters.set(`${location}:${name}`, item)
  }
  return [...parameters.values()]
}

const executionParameterGroups = computed(() => {
  const parameters = executing.value ? effectiveParameters(executing.value) : []
  return parameterLocations
    .map((location) => ({
      ...location,
      parameters: parameters.filter((item) => item.in === location.value),
    }))
    .filter((group) => group.parameters.length)
})
const executionParameterCount = computed(() => executionParameterGroups.value
  .reduce((total, group) => total + group.parameters.length, 0))

function parameterKey(parameter: Record<string, unknown>) {
  return `${String(parameter.in || 'query')}:${String(parameter.name || '')}`
}

function hasParameterValue(parameter: Record<string, unknown>, field: string) {
  return Object.prototype.hasOwnProperty.call(parameter, field)
    && parameter[field] !== null && parameter[field] !== undefined
}

function cloneParameterValue(value: unknown) {
  if (!value || typeof value !== 'object') return value
  return JSON.parse(JSON.stringify(value)) as unknown
}

function initialParameterValue(parameter: Record<string, unknown>) {
  if (hasParameterValue(parameter, 'default')) return cloneParameterValue(parameter.default)
  if (hasParameterValue(parameter, 'example')) return cloneParameterValue(parameter.example)
  return ''
}

function resetExecutionValues(definition: ApiDefinition) {
  Object.keys(executeValues).forEach((key) => delete executeValues[key])
  effectiveParameters(definition).forEach((parameter) => {
    executeValues[parameterKey(parameter)] = initialParameterValue(parameter)
  })
}

function executionParameterText(parameter: Record<string, unknown>) {
  const value = executeValues[parameterKey(parameter)]
  return formatParameterValue(value)
}

function formatParameterValue(value: unknown) {
  if (value === null || value === undefined) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function updateExecutionParameter(parameter: Record<string, unknown>, value: unknown) {
  executeValues[parameterKey(parameter)] = value
}

function isComplexParameter(parameter: Record<string, unknown>) {
  return ['object', 'array'].includes(String(parameter.type || 'string'))
}

function parameterHint(parameter: Record<string, unknown>) {
  const description = String(parameter.description || '').trim()
  const defaultText = hasParameterValue(parameter, 'default')
    ? `默认：${formatParameterValue(parameter.default)}`
    : ''
  return [description, defaultText].filter(Boolean).join(' · ')
}

function executionParameterValue(parameter: Record<string, unknown>) {
  const value = executeValues[parameterKey(parameter)]
  return value === '' || value === null || value === undefined ? undefined : value
}

function collectExecutionParameters() {
  const inputs: Record<string, unknown> = {}
  for (const parameter of executing.value ? effectiveParameters(executing.value) : []) {
    const value = executionParameterValue(parameter)
    if (value === undefined) continue
    if (isComplexParameter(parameter) && typeof value === 'string') {
      try {
        inputs[String(parameter.name)] = JSON.parse(value)
      } catch {
        throw new Error(`参数 ${String(parameter.name)} 必须是有效 JSON`)
      }
    } else inputs[String(parameter.name)] = value
  }
  return inputs
}

function effectiveRequest(definition: ApiDefinition) {
  return mergeConfig(findTemplate(definition.template_id)?.request || {}, definition.request)
}

function requestTarget(definition: ApiDefinition) {
  const request = effectiveRequest(definition)
  const method = request.method || (definition.protocol === 'ws' ? 'WS' : '')
  const directUrl = String(request.url || '').trim()
  const target = directUrl && !directUrl.startsWith('/')
    ? withProtocol(directUrl, definition.protocol)
    : composeRequestEndpoint(request.base_url, request.path || directUrl, definition.protocol)
  return `${method} ${target}`.trim()
}

function displayRequestAddress(value: unknown, protocol: 'http' | 'ws') {
  return withProtocol(String(value || ''), protocol)
}

function effectiveParameterCount(definition: ApiDefinition) {
  return effectiveParameters(definition).length
}

function openCreate() {
  if (!projectId.value) { ElMessage.warning('请先选择项目'); return }
  editingId.value = ''
  Object.assign(form, { key: '', name: '', protocol: 'http', template_id: null, assertion_profile_id: undefined, description: '', request: pretty(defaultRequest('http')), parameters: '[]', examples: '[]', success_contract: pretty(defaultSuccessContract('http')), response_variants: '[]' })
  syncPathParameters(parsePathParameterNames(requestAddress.value))
  dialog.value = true
}

function openEdit(row: ApiDefinition) {
  editingId.value = row.id
  Object.assign(form, { key: row.key, name: row.name, protocol: row.protocol, template_id: row.template_id, assertion_profile_id: row.assertion_profile_id, description: row.description, request: pretty(row.request), parameters: pretty(row.parameters), examples: pretty(row.examples), success_contract: pretty(Object.keys(row.success_contract || {}).length ? row.success_contract : defaultSuccessContract(row.protocol)), response_variants: pretty(row.response_variants) })
  syncPathParameters(parsePathParameterNames(requestAddress.value))
  dialog.value = true
}

function switchProtocol(protocol: 'http' | 'ws') {
  form.protocol = protocol
  form.template_id = null
  form.assertion_profile_id = undefined
  if (!editingId.value) {
    form.request = pretty(defaultRequest(protocol))
    form.success_contract = pretty(defaultSuccessContract(protocol))
  }
  syncPathParameters(parsePathParameterNames(requestAddress.value))
}

function selectTemplate(templateId: string | null) {
  if (!templateId) return
  const template = findTemplate(templateId)
  if (!template) return
  form.protocol = template.protocol
  if (!editingId.value) {
    form.request = pretty(template.protocol === 'http'
      ? { method: 'GET', path: '/health', headers: defaultHttpHeaders() }
      : { path: '/', messages: [{ type: 'ping' }], receive_count: 1 })
  }
  syncPathParameters(parsePathParameterNames(requestAddress.value))
}

function updateRequestConfig(patch: Record<string, unknown>) {
  form.request = pretty({ ...requestConfig.value, ...patch })
}

function updateRequestEndpoint(value: string) {
  const request = requestConfig.value
  const templateRequest = findTemplate(form.template_id)?.request || {}
  const usesPath = Boolean(
    templateRequest.base_url || templateRequest.url || request.base_url || 'path' in request,
  )
  if (usesPath) {
    const { url: _url, ...rest } = request
    form.request = pretty({ ...rest, path: value })
  } else {
    const { path: _path, ...rest } = request
    form.request = pretty({ ...rest, url: value })
  }
  syncPathParameters(parsePathParameterNames(value))
}

function parsePathParameterNames(value: string) {
  const normalized = value.replace(/\{\{[^}]+}}/g, '')
  const names = new Set<string>()
  for (const match of normalized.matchAll(/\{([A-Za-z_][A-Za-z0-9_]*)}/g)) names.add(match[1])
  for (const match of normalized.matchAll(/(?:^|\/)\:([A-Za-z_][A-Za-z0-9_]*)/g)) names.add(match[1])
  return [...names]
}

function updateRequestMethod(value: string) {
  updateRequestConfig({ method: value })
}

function syncPathParameters(names: string[]) {
  pathParameterNames.value = names
  if (!names.length) return
  const current = [...parameterItems.value]
  let changed = false
  for (const name of names) {
    if (current.some((item) => item.name === name && item.in === 'path')) continue
    current.push({
      name, in: 'path', type: 'string', required: true,
      description: `路径参数 ${name}`, example: '',
    })
    changed = true
  }
  if (changed) parameterItems.value = current
}

async function save() {
  try {
    const payload: Record<string, unknown> = {
      project_id: projectId.value, key: form.key, name: form.name, protocol: form.protocol,
      template_id: form.template_id,
      description: form.description,
      request: parseJson<Record<string, unknown>>(form.request, '请求配置'),
      parameters: parseJson<Record<string, unknown>[]>(form.parameters, '参数说明'),
      examples: parseJson<Record<string, unknown>[]>(form.examples, '参考案例'),
      success_contract: parseJson<Record<string, unknown>>(form.success_contract, '成功契约'),
      response_variants: parseJson<Record<string, unknown>[]>(form.response_variants, '响应分支'),
    }
    if (editingId.value || form.assertion_profile_id !== undefined)
      payload.assertion_profile_id = form.assertion_profile_id
    if (editingId.value) await api.definitions.update(editingId.value, payload)
    else await api.definitions.create(payload)
    dialog.value = false
    ElMessage.success('API 已保存')
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
}

function openTemplateCreate() {
  editingTemplateId.value = ''
  Object.assign(templateForm, { name: '', protocol: 'http', description: '', request: pretty(defaultTemplateRequest('http')), parameters: '[]', examples: '[]' })
  templateDialog.value = true
}

function openTemplateEdit(row: ApiTemplate) {
  editingTemplateId.value = row.id
  Object.assign(templateForm, { name: row.name, protocol: row.protocol, description: row.description, request: pretty(row.request), parameters: pretty(row.parameters), examples: pretty(row.examples) })
  templateDialog.value = true
}

function switchTemplateProtocol(protocol: 'http' | 'ws') {
  templateForm.protocol = protocol
  if (!editingTemplateId.value) templateForm.request = pretty(defaultTemplateRequest(protocol))
}

async function saveTemplate() {
  try {
    const payload = {
      project_id: projectId.value, name: templateForm.name,
      protocol: templateForm.protocol, description: templateForm.description,
      request: parseJson<Record<string, unknown>>(templateForm.request, '模板请求配置'),
      parameters: parseJson<Record<string, unknown>[]>(templateForm.parameters, '模板参数说明'),
      examples: parseJson<Record<string, unknown>[]>(templateForm.examples, '模板参考案例'),
    }
    if (editingTemplateId.value) await api.templates.update(editingTemplateId.value, payload)
    else await api.templates.create(payload)
    templateDialog.value = false
    ElMessage.success('API 模板已保存')
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
}

async function removeTemplate(row: ApiTemplate) {
  await ElMessageBox.confirm(`删除模板“${row.name}”？`, '确认删除', { type: 'warning' })
  try { await api.templates.remove(row.id); await load(); ElMessage.success('模板已删除') }
  catch (error) { ElMessage.error((error as Error).message) }
}

async function remove(row: ApiDefinition) {
  await ElMessageBox.confirm(`删除 API“${row.name}”？被流程引用时删除会失败。`, '确认删除', { type: 'warning' })
  try { await api.definitions.remove(row.id); await load(); ElMessage.success('API 已删除') }
  catch (error) { ElMessage.error((error as Error).message) }
}

function openExecute(row: ApiDefinition) {
  executing.value = row
  executionResult.value = null
  Object.assign(executeForm, { inputs: '{}', request: '{}' })
  executeAdvancedOpen.value = []
  resetExecutionValues(row)
  executeDialog.value = true
}

function findProfile(profileId: string | null) {
  return profiles.value.find((profile) => profile.id === profileId)
}

async function execute() {
  if (!executing.value) return
  try {
    const missing = effectiveParameters(executing.value)
      .filter((parameter) => Boolean(parameter.required) && executionParameterValue(parameter) === undefined)
      .map((parameter) => String(parameter.name))
    if (missing.length) {
      ElMessage.warning(`请填写必填参数：${missing.join('、')}`)
      return
    }
    const inputOverrides = parseJson<Record<string, unknown>>(executeForm.inputs, '运行输入')
    const parameterInputs = collectExecutionParameters()
    executionResult.value = await api.definitions.execute(
      executing.value.id,
      { ...inputOverrides, ...parameterInputs },
      parseJson<object>(executeForm.request, '请求覆盖'),
    )
    ElMessage.success('执行完成')
  } catch (error) { ElMessage.error((error as Error).message) }
}

watch(projectId, () => {
  apiPage.value = 1
  templatePage.value = 1
  void load()
}, { immediate: true })
watch(activeTab, (tab) => {
  if (tab === 'apis') apiPage.value = 1
  else templatePage.value = 1
})
watch(apiSearch, () => { apiPage.value = 1 })
</script>

<template>
  <Teleport to="#page-header-content">
    <div class="page-header-content-inner" :class="{ 'api-list-page-header': activeTab === 'apis' }">
      <div class="api-list-header-main">
        <el-radio-group v-model="activeTab">
          <el-radio-button value="apis">API 列表</el-radio-button>
          <el-radio-button value="templates">API 模板</el-radio-button>
        </el-radio-group>
        <el-button v-if="activeTab === 'apis'" type="primary" :disabled="!projectId" @click="openCreate">登记 API</el-button>
        <el-button v-else type="primary" :disabled="!projectId" @click="openTemplateCreate">新建模板</el-button>
      </div>
      <div v-if="activeTab === 'apis'" class="api-list-header-search">
        <el-input
          v-model="apiSearch"
          class="api-list-search"
          :prefix-icon="Search"
          clearable
          placeholder="搜索名称或 URL"
          aria-label="搜索 API 名称或 URL"
        />
      </div>
    </div>
  </Teleport>
  <Teleport to="#page-footer-content">
    <div class="page-footer-content-inner">
      <PaginationBar
        v-if="activeTab === 'apis'"
        v-model:page="apiPage"
        v-model:page-size="apiPageSize"
        :total="filteredDefinitions.length"
      />
      <PaginationBar
        v-else
        v-model:page="templatePage"
        v-model:page-size="templatePageSize"
        :total="templates.length"
      />
    </div>
  </Teleport>
  <el-card v-if="activeTab === 'apis'" class="panel" shadow="never">
    <el-table class="list-table" :data="pagedDefinitions">
      <el-table-column prop="name" label="名称" fixed="left" min-width="180" align="center" show-overflow-tooltip />
      <el-table-column label="URL / 请求目标" min-width="300" align="left" show-overflow-tooltip><template #default="scope"><code>{{ requestTarget(scope.row) }}</code></template></el-table-column>
      <el-table-column label="协议类型" width="100" align="center"><template #default="scope"><el-tag :type="scope.row.protocol === 'http' ? 'success' : 'warning'" effect="dark">{{ scope.row.protocol.toUpperCase() }}</el-tag></template></el-table-column>
      <el-table-column prop="key" label="Key" min-width="180" align="center" show-overflow-tooltip />
      <el-table-column label="模板" min-width="140" align="center"><template #default="scope"><el-tag v-if="findTemplate(scope.row.template_id)" effect="plain">{{ findTemplate(scope.row.template_id)?.name }}</el-tag><span v-else class="muted">无</span></template></el-table-column>
      <el-table-column label="成功条件集合" min-width="150" align="center"><template #default="scope"><el-tag v-if="findProfile(scope.row.assertion_profile_id)" type="success" effect="plain">{{ findProfile(scope.row.assertion_profile_id)?.name }}</el-tag><span v-else class="muted">无</span></template></el-table-column>
      <el-table-column prop="description" label="功能说明" min-width="190" align="left" show-overflow-tooltip />
      <el-table-column label="有效参数" width="90" align="center"><template #default="scope">{{ effectiveParameterCount(scope.row) }}</template></el-table-column>
      <el-table-column label="操作" fixed="right" width="200" align="center"><template #default="scope"><div class="icon-action-group"><el-button class="icon-action-button" link type="success" :icon="VideoPlay" aria-label="执行" @click="openExecute(scope.row)"><span class="icon-action-label">执行</span></el-button><el-button class="icon-action-button" link type="primary" :icon="Edit" aria-label="编辑" @click="openEdit(scope.row)"><span class="icon-action-label">编辑</span></el-button><el-button class="icon-action-button" link type="danger" :icon="Delete" aria-label="删除" @click="remove(scope.row)"><span class="icon-action-label">删除</span></el-button></div></template></el-table-column>
    </el-table>
    <div v-if="projectId && !definitions.length" class="empty-state">当前项目还没有 API。</div>
    <div v-else-if="projectId && !filteredDefinitions.length" class="empty-state">未找到匹配的 API。</div>
    <div v-if="!projectId" class="empty-state">请先创建一个项目。</div>
  </el-card>

  <el-card v-else class="panel" shadow="never">
    <el-table class="list-table" :data="pagedTemplates">
      <el-table-column prop="name" label="模板名称" fixed="left" min-width="180" align="center" show-overflow-tooltip />
      <el-table-column label="基础地址" min-width="280" align="left" show-overflow-tooltip><template #default="scope"><code>{{ displayRequestAddress(scope.row.request.url || scope.row.request.base_url, scope.row.protocol) || '—' }}</code></template></el-table-column>
      <el-table-column label="协议类型" width="100" align="center"><template #default="scope"><el-tag :type="scope.row.protocol === 'http' ? 'success' : 'warning'" effect="dark">{{ scope.row.protocol.toUpperCase() }}</el-tag></template></el-table-column>
      <el-table-column prop="description" label="说明" min-width="240" align="left" show-overflow-tooltip />
      <el-table-column label="引用 API" width="100" align="center"><template #default="scope"><el-tag effect="plain">{{ scope.row.usage_count }}</el-tag></template></el-table-column>
      <el-table-column label="公共参数" width="100" align="center"><template #default="scope">{{ scope.row.parameters.length }}</template></el-table-column>
      <el-table-column label="操作" fixed="right" width="140" align="center"><template #default="scope"><div class="icon-action-group"><el-button class="icon-action-button" link type="primary" :icon="Edit" aria-label="编辑" @click="openTemplateEdit(scope.row)"><span class="icon-action-label">编辑</span></el-button><el-button class="icon-action-button" link type="danger" :icon="Delete" aria-label="删除" @click="removeTemplate(scope.row)"><span class="icon-action-label">删除</span></el-button></div></template></el-table-column>
    </el-table>
    <div v-if="projectId && !templates.length" class="empty-state">还没有 API 模板。创建模板后可统一维护基础地址、请求头和超时等配置。</div>
  </el-card>

  <el-dialog v-model="dialog" width="1180px" top="2vh" class="api-editor-dialog">
    <template #header>
      <div class="api-dialog-heading">
        <h2>{{ editingId ? '编辑 API' : '登记 API' }}</h2>
        <el-tag :type="form.protocol === 'http' ? 'success' : 'warning'" effect="dark">{{ form.protocol === 'http' ? 'HTTP' : 'WebSocket' }}</el-tag>
      </div>
    </template>
    <el-form label-position="top" class="api-editor-form api-editor-single-page">
      <section class="api-editor-section">
        <div class="api-section-heading"><span class="api-section-index">01</span><div><h3>接口信息</h3><p>定义 API 的稳定标识，以及它在文档中的基本描述。</p></div></div>
        <div class="api-basic-grid">
          <el-form-item label="API Key" required><el-input v-model="form.key" placeholder="例如：user.orders.query" /></el-form-item>
          <el-form-item label="API 名称" required><el-input v-model="form.name" placeholder="例如：查询用户订单" /></el-form-item>
          <el-form-item label="API 模板">
            <el-select v-model="form.template_id" clearable placeholder="不使用模板" style="width: 100%" @change="selectTemplate">
              <el-option v-for="item in availableTemplates" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="成功断言集合">
            <el-select v-model="form.assertion_profile_id" clearable placeholder="自动绑定协议默认集合" style="width: 100%">
              <el-option v-for="item in availableProfiles" :key="item.id" :label="`${item.name}${item.is_default ? '（默认）' : ''}`" :value="item.id" />
            </el-select>
          </el-form-item>
        </div>
        <div class="request-target-fields" :class="{ 'is-http': form.protocol === 'http' }">
          <el-form-item label="协议"><el-radio-group :model-value="form.protocol" @update:model-value="switchProtocol"><el-radio-button value="http">HTTP</el-radio-button><el-radio-button value="ws">WS</el-radio-button></el-radio-group></el-form-item>
          <el-form-item v-if="form.protocol === 'http'" label="请求方法">
            <el-select :model-value="requestMethod" style="width: 100%" @update:model-value="updateRequestMethod">
              <el-option v-for="method in ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD']" :key="method" :label="method" :value="method" />
            </el-select>
          </el-form-item>
          <el-form-item label="请求路径" class="request-address-item">
            <el-input :model-value="requestAddress" :placeholder="requestAddressPlaceholder" @update:model-value="updateRequestEndpoint" />
            <div class="request-address-hint"><span>最终地址</span><code>{{ requestEndpoint }}</code></div>
          </el-form-item>
        </div>
        <el-form-item label="功能说明"><el-input v-model="form.description" type="textarea" :rows="2" placeholder="简要说明这个 API 做什么、适用于什么场景" /></el-form-item>
      </section>

      <div v-if="findTemplate(form.template_id)" class="inheritance-notice">
        <div><strong>已继承 {{ findTemplate(form.template_id)?.name }}</strong><span>基础地址、公共请求头和超时会自动合并，当前 API 只需填写差异。</span></div>
        <code>{{ displayRequestBase }}</code>
      </div>

      <section class="api-editor-section">
        <div class="api-section-heading"><span class="api-section-index">02</span><div><h3>Parameters</h3></div><el-tag type="info" effect="plain">{{ parameterItems.length }} 个参数</el-tag></div>
        <ApiParametersEditor v-model="parameterItems" :path-params="pathParameterNames" />
      </section>

    </el-form>
    <template #footer><el-button @click="dialog = false">取消</el-button><el-button type="primary" :disabled="!form.key || !form.name" @click="save">保存</el-button></template>
  </el-dialog>

  <el-dialog v-model="templateDialog" :title="editingTemplateId ? '编辑 API 模板' : '新建 API 模板'" width="700px">
    <el-form label-position="top">
      <div class="two-col">
        <el-form-item label="模板名称"><el-input v-model="templateForm.name" placeholder="例如：内部服务通用模板" /></el-form-item>
        <el-form-item label="协议"><el-radio-group :model-value="templateForm.protocol" @update:model-value="switchTemplateProtocol"><el-radio-button value="http">HTTP</el-radio-button><el-radio-button value="ws">WebSocket</el-radio-button></el-radio-group></el-form-item>
      </div>
      <el-form-item label="模板说明"><el-input v-model="templateForm.description" type="textarea" :rows="2" /></el-form-item>
      <el-tabs>
        <el-tab-pane label="公共请求配置"><el-input v-model="templateForm.request" class="json-input" type="textarea" :rows="13" /><div class="muted">推荐维护 <code>base_url</code>、公共 headers、query、timeout_seconds 等字段。API 可通过相同字段覆盖。</div></el-tab-pane>
        <el-tab-pane label="公共参数说明"><el-input v-model="templateForm.parameters" class="json-input" type="textarea" :rows="13" /></el-tab-pane>
        <el-tab-pane label="公共参考案例"><el-input v-model="templateForm.examples" class="json-input" type="textarea" :rows="13" /></el-tab-pane>
      </el-tabs>
    </el-form>
    <template #footer><el-button @click="templateDialog = false">取消</el-button><el-button type="primary" :disabled="!templateForm.name" @click="saveTemplate">保存模板</el-button></template>
  </el-dialog>

  <el-dialog v-model="executeDialog" width="1040px" top="4vh" class="execute-dialog">
    <template #header>
      <div class="execute-dialog-heading">
        <div>
          <span class="execute-dialog-kicker">API RUNNER</span>
          <h2>执行 API</h2>
          <p>{{ executing?.name || '未选择 API' }}</p>
        </div>
        <el-tag v-if="executing" :type="executing.protocol === 'http' ? 'success' : 'warning'" effect="dark">
          {{ executing.protocol.toUpperCase() }}
        </el-tag>
      </div>
    </template>
    <div class="execute-layout">
      <section class="execute-panel execute-config-panel">
        <div class="execute-panel-heading">
          <span class="execute-panel-index">01</span>
          <div><h3>请求参数</h3><p>填写 API 契约中的参数，系统会按位置组装请求。</p></div>
          <el-tag type="info" effect="plain">{{ executionParameterCount }} 个参数</el-tag>
        </div>
        <div v-if="executionParameterGroups.length" class="execution-parameter-groups">
          <section v-for="group in executionParameterGroups" :key="group.value" class="execution-parameter-group">
            <div class="execution-parameter-group-heading">
              <span>{{ group.label }}</span>
              <small>{{ group.parameters.length }} 个</small>
            </div>
            <div class="execution-parameter-grid">
              <label v-for="parameter in group.parameters" :key="parameterKey(parameter)" class="execution-parameter-field">
                <span class="execution-parameter-label">
                  <code>{{ parameter.name }}</code>
                  <em v-if="parameter.required">必填</em>
                </span>
                <el-input
                  :model-value="executionParameterText(parameter)"
                  :type="isComplexParameter(parameter) ? 'textarea' : 'text'"
                  :rows="isComplexParameter(parameter) ? 2 : undefined"
                  :placeholder="isComplexParameter(parameter) ? 'JSON 格式' : '请输入值'"
                  spellcheck="false"
                  @update:model-value="updateExecutionParameter(parameter, $event)"
                />
                <small v-if="parameterHint(parameter)">{{ parameterHint(parameter) }}</small>
              </label>
            </div>
          </section>
        </div>
        <div v-else class="execute-no-parameters">
          <strong>当前 API 没有参数定义</strong>
          <span>可直接执行，或在高级 JSON 覆盖中传入上下文。</span>
        </div>
        <el-collapse v-model="executeAdvancedOpen" class="execute-advanced">
          <el-collapse-item title="高级 JSON 覆盖" name="advanced">
            <el-form label-position="top" class="execute-form">
              <el-form-item label="运行输入（合并到项目上下文）">
                <el-input v-model="executeForm.inputs" class="execute-json-input" type="textarea" :rows="5" spellcheck="false" />
              </el-form-item>
              <el-form-item label="本次请求覆盖">
                <el-input v-model="executeForm.request" class="execute-json-input" type="textarea" :rows="5" spellcheck="false" />
              </el-form-item>
            </el-form>
          </el-collapse-item>
        </el-collapse>
      </section>
      <section class="execute-panel execute-result-panel">
        <div class="execute-panel-heading">
          <span class="execute-panel-index">02</span>
          <div><h3>执行结果</h3><p>查看实际请求、响应和成功判断详情。</p></div>
          <el-tag v-if="executionResult" type="success" effect="plain">已完成</el-tag>
        </div>
        <pre v-if="executionResult" class="execute-code-block">{{ pretty(executionResult) }}</pre>
        <div v-else class="execute-empty-state">
          <strong>等待执行</strong>
          <span>点击右下角“执行请求”查看结果。</span>
        </div>
      </section>
    </div>
    <template #footer><el-button @click="executeDialog = false">关闭</el-button><el-button type="primary" @click="execute">执行请求</el-button></template>
  </el-dialog>
</template>
