<script setup lang="ts">
import { Delete, Edit, MoreFilled, Plus, Search, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'

import { api } from '../api/client'
import ApiParametersEditor from '../components/ApiParametersEditor.vue'
import ApiRequestEditor from '../components/ApiRequestEditor.vue'
import ApiResponseFieldsEditor from '../components/ApiResponseFieldsEditor.vue'
import PaginationBar from '../components/PaginationBar.vue'
import { useProjectContext } from '../state/project'
import type { ApiDefinition, ApiGroup, ApiTemplate, AssertionDefinition } from '../types'
import { parseJson, pretty } from '../utils'

const definitions = ref<ApiDefinition[]>([])
const groups = ref<ApiGroup[]>([])
const templates = ref<ApiTemplate[]>([])
const assertions = ref<AssertionDefinition[]>([])
const { projectId } = useProjectContext()
const activeTab = ref<'apis' | 'templates'>('apis')
const dialog = ref(false)
const requestPreviewOpen = ref(false)
const editorConfigTab = ref<'request' | 'response'>('request')
const editorMode = ref<'visual' | 'json'>('visual')
const advancedDraft = ref('{}')
const advancedError = ref('')
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
const parameterEditor = ref<InstanceType<typeof ApiParametersEditor> | null>(null)
type ApiGroupNode = {
  id?: string
  path: string
  label: string
  count: number
  children: ApiGroupNode[]
}

const selectedGroupPath = ref('/')
const activeGroupActionPath = ref<string | null>(null)
const form = reactive({
  key: '', group_path: '/', name: '', protocol: 'http' as 'http' | 'ws', template_id: null as string | null,
  success_assertion_id: undefined as string | null | undefined,
  description: '', request: '{}', request_schema: '{}', response_schema: '{}',
  response_unpack: '{}', parameters: '[]', examples: '[]', success_contract: '{}', response_variants: '[]',
})
const templateForm = reactive({
  name: '', protocol: 'http' as 'http' | 'ws', description: '', request: '{}',
  parameters: '[]', examples: '[]',
})
const executeForm = reactive({ inputs: '{}', request: '{}' })
const commonAcceptOptions = [
  { label: 'JSON', value: 'application/json' },
  { label: 'Problem JSON', value: 'application/problem+json' },
  { label: 'XML', value: 'application/xml' },
  { label: '纯文本', value: 'text/plain' },
  { label: 'HTML', value: 'text/html' },
  { label: 'SSE 流', value: 'text/event-stream' },
  { label: '二进制', value: 'application/octet-stream' },
  { label: '任意类型', value: '*/*' },
]
const availableTemplates = computed(() =>
  templates.value.filter((template) => template.protocol === form.protocol),
)

function normalizeGroupPath(value: unknown) {
  const raw = String(value || '').trim().replace(/\\/g, '/')
  const segments = raw.split('/').map((segment) => segment.trim()).filter(Boolean)
  return segments.length ? `/${segments.join('/')}` : '/'
}

const apiGroupTree = computed<ApiGroupNode[]>(() => {
  const root: ApiGroupNode = { path: '/', label: '全部 API', count: 0, children: [] }
  const nodesByPath = new Map<string, ApiGroupNode>([[root.path, root]])

  const ensureNode = (path: string, label?: string) => {
    const normalized = normalizeGroupPath(path)
    if (normalized === '/') return root
    const segments = normalized.split('/').filter(Boolean)
    let parent = root
    segments.forEach((segment, index) => {
      const childPath = `/${segments.slice(0, index + 1).join('/')}`
      let child = nodesByPath.get(childPath)
      if (!child) {
        child = { path: childPath, label: segment, count: 0, children: [] }
        nodesByPath.set(childPath, child)
        parent.children.push(child)
      }
      if (index === segments.length - 1 && label) child.label = label
      parent = child
    })
    return parent
  }

  for (const group of groups.value) {
    const node = ensureNode(group.path, group.name)
    node.id = group.id
  }
  for (const definition of definitions.value) {
    root.count += 1
    const path = normalizeGroupPath(definition.group_path)
    if (path === '/') continue
    let parent = root
    const segments = path.split('/').filter(Boolean)
    segments.forEach((segment, index) => {
      const childPath = `/${segments.slice(0, index + 1).join('/')}`
      const child = ensureNode(childPath, segment)
      child.count += 1
      parent = child
    })
  }
  const sortNodes = (nodes: ApiGroupNode[]) => {
    nodes.sort((left, right) => left.label.localeCompare(right.label, 'zh-CN'))
    nodes.forEach((node) => sortNodes(node.children))
  }
  sortNodes(root.children)
  return [root]
})

const filteredDefinitions = computed(() => {
  const keyword = apiSearch.value.trim().toLocaleLowerCase()
  const selected = normalizeGroupPath(selectedGroupPath.value)
  return definitions.value.filter((definition) => {
    const path = normalizeGroupPath(definition.group_path)
    if (selected !== '/' && path !== selected && !path.startsWith(`${selected}/`)) return false
    if (!keyword) return true
    return definition.name.toLocaleLowerCase().includes(keyword)
      || definition.key.toLocaleLowerCase().includes(keyword)
      || path.toLocaleLowerCase().includes(keyword)
      || requestTarget(definition).toLocaleLowerCase().includes(keyword)
  })
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
const requestSchemaConfig = computed<Record<string, unknown>>(() => {
  try { return JSON.parse(form.request_schema) as Record<string, unknown> }
  catch { return {} }
})
const responseSchemaConfig = computed<Record<string, unknown>>({
  get: () => {
    try { return JSON.parse(form.response_schema) as Record<string, unknown> }
    catch { return {} }
  },
  set: (value) => { form.response_schema = pretty(value) },
})
const responseUnpackConfig = computed<Record<string, unknown>>({
  get: () => {
    try {
      const value = JSON.parse(form.response_unpack)
      return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
    } catch { return {} }
  },
  set: (value) => { form.response_unpack = pretty(value) },
})
const responseUnpackEnabled = computed({
  get: () => form.protocol === 'http' && responseUnpackConfig.value.enabled === true,
  set: (enabled: boolean) => {
    if (form.protocol !== 'http') return
    const next: Record<string, unknown> = { ...responseUnpackConfig.value, enabled }
    if (enabled && (typeof next.source !== 'string' || !next.source.trim())) next.source = 'body.data'
    responseUnpackConfig.value = next
  },
})
const responseUnpackSource = computed({
  get: () => typeof responseUnpackConfig.value.source === 'string'
    ? responseUnpackConfig.value.source
    : 'body.data',
  set: (value: string) => {
    responseUnpackConfig.value = { ...responseUnpackConfig.value, source: value.trim() || 'body.data' }
  },
})
const requestSchemaAccept = computed({
  get: () => {
    const configured = requestSchemaConfig.value.accept
    if (typeof configured === 'string') return configured
    const headers = requestConfig.value.headers
    if (!headers || typeof headers !== 'object' || Array.isArray(headers)) return ''
    const entry = Object.entries(headers as Record<string, unknown>)
      .find(([name]) => name.toLowerCase() === 'accept')
    return typeof entry?.[1] === 'string' ? entry[1] : ''
  },
  set: (value: string) => {
    const accept = value.trim()
    const nextSchema = { ...requestSchemaConfig.value }
    if (accept) nextSchema.accept = accept
    else delete nextSchema.accept
    form.request_schema = pretty(nextSchema)

    const request = { ...requestConfig.value }
    const headers = request.headers && typeof request.headers === 'object'
      && !Array.isArray(request.headers)
      ? { ...(request.headers as Record<string, unknown>) }
      : {}
    Object.keys(headers).forEach((name) => {
      if (name.toLowerCase() === 'accept') delete headers[name]
    })
    if (accept) headers.Accept = accept
    request.headers = headers
    form.request = pretty(request)
  },
})
const routeKey = computed(() => {
  const request = requestConfig.value
  if (form.protocol === 'http') {
    const method = String(request.method || 'GET').toUpperCase()
    const target = String(request.path || request.url || '').trim()
    return target ? `http:${method}:${target}` : ''
  }
  const target = String(request.url || request.path || '').trim()
  return target ? `ws:${target}` : ''
})
const displayKey = computed(() => routeKey.value || form.key)

function addParameter() {
  parameterEditor.value?.add()
}

function selectApiGroup(node: ApiGroupNode) {
  selectedGroupPath.value = node.path
  activeGroupActionPath.value = null
}

function toggleGroupActions(path: string) {
  activeGroupActionPath.value = activeGroupActionPath.value === path ? null : path
}

function closeGroupActionsOnOutsideClick(event: MouseEvent) {
  if (!activeGroupActionPath.value) return
  const target = event.target
  if (target instanceof Element && target.closest('.api-group-actions, .api-group-menu-trigger')) return
  activeGroupActionPath.value = null
}

onMounted(() => document.addEventListener('click', closeGroupActionsOnOutsideClick))
onBeforeUnmount(() => document.removeEventListener('click', closeGroupActionsOnOutsideClick))

function normalizeGroupName(value: unknown) {
  const name = String(value || '').trim()
  if (!name) return ''
  if (name.includes('/') || name.includes('\\') || name === '.' || name === '..') return ''
  return name
}

function isMessageBoxCancelled(error: unknown) {
  return error === 'cancel' || error === 'close'
}

async function createApiGroup(parent: ApiGroupNode) {
  if (!projectId.value) return
  try {
    const result = await ElMessageBox.prompt(
      `在“${parent.path === '/' ? '全部 API' : parent.path}”下新建目录`,
      '新建目录',
      {
        inputPlaceholder: '例如：用户管理',
        confirmButtonText: '创建',
        cancelButtonText: '取消',
        inputValidator: (value: string) => normalizeGroupName(value) ? true : '请输入不含斜杠的目录名称',
      },
    )
    const group = await api.groups.create({
      project_id: projectId.value,
      parent_path: parent.path,
      name: normalizeGroupName(result.value),
    })
    selectedGroupPath.value = group.path
    activeGroupActionPath.value = null
    await load()
    ElMessage.success('目录已创建')
  } catch (error) {
    if (!isMessageBoxCancelled(error)) ElMessage.error((error as Error).message)
  }
}

async function renameApiGroup(node: ApiGroupNode) {
  if (!node.id) return
  try {
    const result = await ElMessageBox.prompt(
      `修改目录“${node.path}”的名称`,
      '编辑目录',
      {
        inputValue: node.label,
        confirmButtonText: '保存',
        cancelButtonText: '取消',
        inputValidator: (value: string) => normalizeGroupName(value) ? true : '请输入不含斜杠的目录名称',
      },
    )
    const group = await api.groups.update(node.id, { name: normalizeGroupName(result.value) })
    selectedGroupPath.value = group.path
    activeGroupActionPath.value = null
    await load()
    ElMessage.success('目录已重命名')
  } catch (error) {
    if (!isMessageBoxCancelled(error)) ElMessage.error((error as Error).message)
  }
}

async function removeApiGroup(node: ApiGroupNode) {
  if (!node.id) return
  try {
    await ElMessageBox.confirm(
      `删除目录“${node.path}”？仅空目录可以删除。`,
      '确认删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await api.groups.remove(node.id)
    activeGroupActionPath.value = null
    if (selectedGroupPath.value === node.path || selectedGroupPath.value.startsWith(`${node.path}/`)) {
      selectedGroupPath.value = normalizeGroupPath(node.path.slice(0, node.path.lastIndexOf('/')))
    }
    await load()
    ElMessage.success('目录已删除')
  } catch (error) {
    if (!isMessageBoxCancelled(error)) ElMessage.error((error as Error).message)
  }
}

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
const requestAddress = computed(() => {
  const request = requestConfig.value
  const path = String(request.path || '')
  if (path) return path
  const url = String(request.url || '')
  if (inheritedRequestBase.value && url.startsWith(inheritedRequestBase.value))
    return url.slice(inheritedRequestBase.value.length) || '/'
  return url
})
const requestMethod = computed(() => form.protocol === 'ws'
  ? 'WS'
  : String(requestConfig.value.method || 'GET').toUpperCase())
const requestTargetPreview = computed(() => {
  const request = mergeConfig(findTemplate(form.template_id)?.request || {}, requestConfig.value)
  const directUrl = String(request.url || '').trim()
  const path = String(request.path || '').trim()
  if (!directUrl && !path && !request.base_url) return '尚未填写请求目标'
  if (directUrl && !directUrl.startsWith('/')) return withProtocol(directUrl, form.protocol)
  return composeRequestEndpoint(request.base_url, path || directUrl, form.protocol)
})
const requestPreviewTemplate = computed(() => findTemplate(form.template_id))
const requestPreviewText = computed(() => buildRequestPreview())
const responsePreviewText = computed(() => buildResponsePreview())
const requestPreviewTemplateText = computed(() => buildTemplatePreview())

function updateRequestConfig(patch: Record<string, unknown>) {
  form.request = pretty({ ...requestConfig.value, ...patch })
}

function updateRequestTarget(value: string) {
  const current = requestConfig.value
  const normalized = value.trim()
  const usePath = Boolean(inheritedRequestBase.value)
    || Object.prototype.hasOwnProperty.call(current, 'path')
    || (!current.url && !normalized.includes('://'))
  if (usePath) {
    const { url: _url, ...rest } = current
    form.request = pretty({ ...rest, path: value })
  } else {
    const { path: _path, ...rest } = current
    form.request = pretty({ ...rest, url: value })
  }
  syncPathParameters(parsePathParameterNames(value))
}
async function load() {
  if (!projectId.value) {
    definitions.value = []
    groups.value = []
    templates.value = []
    assertions.value = []
    selectedGroupPath.value = '/'
    activeGroupActionPath.value = null
    return
  }
  try {
    ;[definitions.value, groups.value, templates.value, assertions.value] = await Promise.all([
      api.definitions.list(projectId.value), api.groups.list(projectId.value),
      api.templates.list(projectId.value), api.assertionDefinitions.list(projectId.value),
    ])
  }
  catch (error) { ElMessage.error((error as Error).message) }
}

function defaultRequest(protocol: 'http' | 'ws') {
  return protocol === 'http'
    ? { method: 'GET', path: '/health', headers: defaultHttpHeaders(), query: {} }
    : { path: '/', headers: {}, messages: [{ type: 'ping' }], receive_count: 1 }
}

function defaultRequestSchema(protocol: 'http' | 'ws') {
  return protocol === 'http' ? { accept: 'application/json', schema: {} } : {}
}

function previewValue(value: unknown, fallback: string) {
  if (value === undefined || value === null || value === '') return fallback
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function parameterChildren(parameter: Record<string, unknown>): Record<string, unknown>[] {
  const children = Array.isArray(parameter.children)
    ? parameter.children
    : parameter.child_params
  return Array.isArray(children) ? children.filter(isRecord) : []
}

function previewParameters() {
  const parameters = new Map<string, Record<string, unknown>>()
  for (const item of [...(requestPreviewTemplate.value?.parameters || []), ...parameterItems.value]) {
    const name = String(item.name || '').trim()
    const location = String(item.in || 'query')
    if (!name) continue
    parameters.set(`${location}:${name}`, item)
  }
  return [...parameters.values()]
}

function previewParameterLiteral(parameter: Record<string, unknown>, value: unknown) {
  const type = String(parameter.type || 'string')
  if (['object', 'array'].includes(type) && typeof value === 'string') {
    try { return JSON.parse(value) as unknown }
    catch { return value }
  }
  return value
}

function previewParameterValue(parameter: Record<string, unknown>, parentPath: string[] = []): unknown {
  const name = String(parameter.name || 'value').trim() || 'value'
  const path = [...parentPath, name]
  let explicitValue: unknown
  if (Object.prototype.hasOwnProperty.call(parameter, 'default')
    && parameter.default !== null && parameter.default !== undefined && parameter.default !== '')
    explicitValue = previewParameterLiteral(parameter, parameter.default)
  else if (Object.prototype.hasOwnProperty.call(parameter, 'example')
    && parameter.example !== null && parameter.example !== undefined && parameter.example !== '')
    explicitValue = previewParameterLiteral(parameter, parameter.example)

  const children = parameterChildren(parameter)
  if (String(parameter.type || 'string') === 'object' && children.length) {
    let generatedValue: Record<string, unknown> = {}
    for (const child of children) {
      generatedValue = setPreviewParameterValue(
        generatedValue,
        [String(child.name || 'field')],
        previewParameterValue(child, path),
      )
    }
    if (isRecord(explicitValue)) return mergePreviewParameterValue(explicitValue, generatedValue)
    if (explicitValue !== undefined) return explicitValue
    return generatedValue
  }
  if (explicitValue !== undefined) return explicitValue
  return `{{ ${path.join('.')} }}`
}

function previewSchemaSample(schema: unknown): unknown {
  if (!isRecord(schema)) return {}
  if (Object.prototype.hasOwnProperty.call(schema, 'example')) return schema.example
  if (Object.prototype.hasOwnProperty.call(schema, 'default')) return schema.default
  if (Object.prototype.hasOwnProperty.call(schema, 'const')) return schema.const
  if (Array.isArray(schema.enum) && schema.enum.length) return schema.enum[0]
  if (Array.isArray(schema.oneOf) && schema.oneOf.length) return previewSchemaSample(schema.oneOf[0])
  if (Array.isArray(schema.anyOf) && schema.anyOf.length) return previewSchemaSample(schema.anyOf[0])

  const type = String(schema.type || '')
  if (type === 'object' || isRecord(schema.properties)) {
    const properties = isRecord(schema.properties) ? schema.properties : {}
    return Object.fromEntries(Object.entries(properties).map(([name, value]) => (
      [name, previewSchemaSample(value)]
    )))
  }
  if (type === 'array') return [previewSchemaSample(schema.items)]
  if (type === 'integer' || type === 'number') return 0
  if (type === 'boolean') return false
  if (type === 'null') return null
  return ''
}

function previewRequestBodyValue() {
  const request = mergeConfig(requestPreviewTemplate.value?.request || {}, requestConfig.value)
  const bodyParameters = previewParameters().filter((parameter) => parameter.in === 'body')
  if (bodyParameters.length) {
    const configuredBody = request.body
    if (configuredBody !== undefined && configuredBody !== null && configuredBody !== ''
      && !isRecord(configuredBody)) return configuredBody

    let body = isRecord(configuredBody) ? configuredBody : {}
    for (const parameter of bodyParameters) {
      body = setPreviewParameterValue(
        body,
        [String(parameter.name || 'value')],
        previewParameterValue(parameter),
      )
    }
    return body
  }

  if (Object.prototype.hasOwnProperty.call(request, 'body')
    && request.body !== undefined && request.body !== null && request.body !== '') return request.body

  const schema = requestSchemaConfig.value.schema
  if (isRecord(schema) && Object.keys(schema).length) return previewSchemaSample(schema)
  return undefined
}

function mergePreviewParameterValue(current: unknown, generated: unknown): unknown {
  if (isRecord(current) && isRecord(generated)) {
    const merged: Record<string, unknown> = { ...generated, ...current }
    for (const key of Object.keys(generated)) {
      if (Object.prototype.hasOwnProperty.call(current, key)) {
        merged[key] = mergePreviewParameterValue(current[key], generated[key])
      }
    }
    return merged
  }
  return current === undefined || current === null || current === '' ? generated : current
}

function setPreviewParameterValue(
  target: Record<string, unknown>,
  path: string[],
  value: unknown,
): Record<string, unknown> {
  if (!path.length) return target
  const [part, ...rest] = path
  const next = { ...target }
  if (!rest.length) {
    next[part] = mergePreviewParameterValue(target[part], value)
    return next
  }
  next[part] = setPreviewParameterValue(
    isRecord(target[part]) ? target[part] : {},
    rest,
    value,
  )
  return next
}

function formatPreviewBody(value: unknown) {
  if (value === undefined || value === null || value === '') return '(无请求体)'
  return typeof value === 'string' ? value : pretty(value)
}

function parsePreviewJson(value: string) {
  try { return JSON.parse(value) as unknown }
  catch { return undefined }
}

function previewExpectedBody(examples: unknown) {
  if (!Array.isArray(examples)) return undefined
  for (const item of examples) {
    if (!isRecord(item) || !isRecord(item.expected_response)) continue
    const expected = item.expected_response
    if (Object.prototype.hasOwnProperty.call(expected, 'body')) return expected.body
    return expected
  }
  return undefined
}

function previewResponseExampleValue() {
  const apiExampleBody = previewExpectedBody(parsePreviewJson(form.examples))
  if (apiExampleBody !== undefined) return apiExampleBody
  return previewExpectedBody(requestPreviewTemplate.value?.examples)
}

function previewNestedValue(value: unknown, path: string) {
  let current = value
  for (const segment of path.split('.').filter(Boolean)) {
    if (!isRecord(current) || !Object.prototype.hasOwnProperty.call(current, segment)) return undefined
    current = current[segment]
  }
  return current
}

function setPreviewNestedValue(target: Record<string, unknown>, path: string[], value: unknown) {
  if (!path.length) return target
  const [segment, ...rest] = path
  if (!rest.length) {
    target[segment] = value
    return target
  }
  const child: Record<string, unknown> = isRecord(target[segment]) ? { ...target[segment] } : {}
  target[segment] = setPreviewNestedValue(child, rest, value)
  return target
}

function previewResponseEnvelopeValue(payload: unknown) {
  const source = responseUnpackSource.value.split('.').slice(1).filter(Boolean)
  const envelopeSchema = responseUnpackConfig.value.envelope_schema
  const envelope = isRecord(envelopeSchema) ? previewSchemaSample(envelopeSchema) : {}
  const result = isRecord(envelope) ? envelope : {}
  if (source.length) setPreviewNestedValue(result, source, payload)
  if (source[0] === 'data' && !Object.prototype.hasOwnProperty.call(result, 'code')) result.code = 0
  return result
}

function previewResponsePayloadValue() {
  const example = previewResponseExampleValue()
  if (example !== undefined) {
    if (responseUnpackEnabled.value) {
      const source = responseUnpackSource.value.replace(/^body\.?/, '')
      const unpacked = previewNestedValue(example, source)
      if (unpacked !== undefined) return unpacked
    }
    return example
  }
  if (Object.keys(responseSchemaConfig.value).length) return previewSchemaSample(responseSchemaConfig.value)
  return {}
}

function previewResponseBodyValue() {
  const example = previewResponseExampleValue()
  if (example !== undefined) {
    if (responseUnpackEnabled.value) {
      const source = responseUnpackSource.value.replace(/^body\.?/, '')
      if (previewNestedValue(example, source) === undefined) return previewResponseEnvelopeValue(example)
    }
    return example
  }
  const payload = previewResponsePayloadValue()
  return responseUnpackEnabled.value ? previewResponseEnvelopeValue(payload) : payload
}

function previewResponseStatusCode() {
  const contract = parsePreviewJson(form.success_contract)
  const statusCodes = isRecord(contract) && isRecord(contract.status_codes)
    ? contract.status_codes
    : {}
  const min = Number(statusCodes.min)
  return Number.isFinite(min) ? min : 200
}

function previewResponseReason(statusCode: number) {
  return {
    200: 'OK', 201: 'Created', 202: 'Accepted', 204: 'No Content',
    400: 'Bad Request', 401: 'Unauthorized', 403: 'Forbidden',
    404: 'Not Found', 409: 'Conflict', 422: 'Unprocessable Entity',
    500: 'Internal Server Error',
  }[statusCode] || 'OK'
}

function buildRequestPreview() {
  const request = mergeConfig(requestPreviewTemplate.value?.request || {}, requestConfig.value)
  const target = requestTargetPreview.value
  const targetMatch = target.match(/^[a-z]+:\/\/([^/]+)(\/.*)?$/i)
  const host = targetMatch?.[1] || '{{ base_url }}'
  let path = targetMatch?.[2] || (target.startsWith('/') ? target : '/')
  const query = request.query && typeof request.query === 'object' && !Array.isArray(request.query)
    ? request.query as Record<string, unknown>
    : {}
  const queryPairs = Object.entries(query).map(([name, value]) => `${name}=${previewValue(value, `{{ ${name} }}`)}`)
  const configuredQueryNames = new Set(Object.keys(query))
  previewParameters()
    .filter((item) => item.in === 'query' && String(item.name || '').trim())
    .forEach((item) => {
      const name = String(item.name)
      if (configuredQueryNames.has(name)) return
      queryPairs.push(`${name}=${previewParameterValue(item)}`)
    })
  const querySeparator = path.indexOf('?')
  const basePath = querySeparator >= 0 ? path.slice(0, querySeparator) : path
  const existingQuery = querySeparator >= 0 ? path.slice(querySeparator + 1) : ''
  const queryString = [existingQuery, ...queryPairs].filter(Boolean).join('&')
  path = `${basePath || '/'}${queryString ? `?${queryString}` : ''}`
  const scheme = target.match(/^([a-z]+):\/\//i)?.[1] || protocolScheme(form.protocol)
  const fullTarget = targetMatch
    ? `${scheme}://${host}${path}`
    : target.startsWith('/') ? `${scheme}://${host}${path}` : target

  const headers = request.headers && typeof request.headers === 'object' && !Array.isArray(request.headers)
    ? request.headers as Record<string, unknown>
    : {}
  const configuredHost = Object.entries(headers)
    .find(([name]) => name.toLowerCase() === 'host')?.[1]
  const headerLines = Object.entries(headers)
    .filter(([name, value]) => name.toLowerCase() !== 'host'
      && value !== undefined && value !== null && value !== '')
    .map(([name, value]) => `${name}: ${previewValue(value, '')}`)
  if (!Object.keys(headers).some((name) => name.toLowerCase() === 'accept'))
    headerLines.push(`Accept: ${requestSchemaAccept.value || 'application/json'}`)

  const bodyText = formatPreviewBody(previewRequestBodyValue())
  const requestLine = form.protocol === 'http'
    ? `${requestMethod.value} ${fullTarget}`
    : `GET ${fullTarget}`
  const lines = [requestLine, '', `Host: ${previewValue(configuredHost, host)}`, ...headerLines]
  if (form.protocol === 'ws') lines.push('Connection: Upgrade', 'Upgrade: websocket')
  if (bodyText !== '(无请求体)' && !Object.keys(headers).some((name) => name.toLowerCase() === 'content-type'))
    lines.push('Content-Type: application/json')
  lines.push('', bodyText)
  return lines.join('\n')
}

function buildResponsePreview() {
  const statusCode = previewResponseStatusCode()
  const accept = requestSchemaAccept.value || 'application/json'
  const lines = [
    `${statusCode} ${previewResponseReason(statusCode)}`,
    `Content-Type: ${accept}`,
    '',
    'BODY',
    formatPreviewBody(previewResponseBodyValue()),
  ]
  if (responseUnpackEnabled.value) {
    lines.push('', 'UNPACKED DATA (response.payload)', formatPreviewBody(previewResponsePayloadValue()))
  }
  return lines.join('\n')
}

function buildTemplatePreview() {
  const template = requestPreviewTemplate.value
  if (!template) return ''
  return pretty({
    name: template.name,
    protocol: template.protocol,
    description: template.description,
    request: template.request,
    parameters: template.parameters,
    examples: template.examples,
  })
}

function defaultSuccessContract(protocol: 'http' | 'ws') {
  return protocol === 'ws'
    ? { messages: { min: 1 }, body_schema: {} }
    : { status_codes: { min: 200, max: 299 }, body_schema: {} }
}

function defaultResponseSchema(protocol: 'http' | 'ws') {
  return protocol === 'http' ? { type: 'object', properties: {}, required: [] } : {}
}

function defaultResponseUnpack(protocol: 'http' | 'ws') {
  return protocol === 'http' ? { enabled: false, source: 'body.data' } : {}
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
  return flattenParameterTree([...parameters.values()])
}

function flattenParameterTree(
  parameters: Record<string, unknown>[],
  parentPath: string[] = [],
  inheritedLocation = 'query',
): Record<string, unknown>[] {
  const flattened: Record<string, unknown>[] = []
  for (const parameter of parameters) {
    const name = String(parameter.name || '').trim()
    if (!name) continue
    const path = [...parentPath, name]
    const location = parentPath.length ? inheritedLocation : String(parameter.in || 'query')
    flattened.push({
      ...parameter,
      in: location,
      parameter_path: path,
      parameter_depth: parentPath.length,
    })
    if (String(parameter.type || 'string') === 'object') {
      flattened.push(...flattenParameterTree(parameterChildren(parameter), path, location))
    }
  }
  return flattened
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
  return `${String(parameter.in || 'query')}:${parameterPath(parameter).join('.')}`
}

function parameterPath(parameter: Record<string, unknown>) {
  const path = parameter.parameter_path
  if (Array.isArray(path) && path.length) return path.map((part) => String(part))
  return [String(parameter.name || '')]
}

function parameterDisplayName(parameter: Record<string, unknown>) {
  return parameterPath(parameter).join('.')
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
    let normalizedValue = value
    if (isComplexParameter(parameter) && typeof value === 'string') {
      try {
        normalizedValue = JSON.parse(value)
      } catch {
        throw new Error(`参数 ${parameterDisplayName(parameter)} 必须是有效 JSON`)
      }
    }
    setNestedParameterValue(inputs, parameterPath(parameter), normalizedValue)
  }
  return inputs
}

function setNestedParameterValue(target: Record<string, unknown>, path: string[], value: unknown) {
  if (!path.length) return
  let current = target
  path.forEach((part, index) => {
    if (index === path.length - 1) {
      current[part] = value
      return
    }
    if (!isRecord(current[part])) current[part] = {}
    current = current[part] as Record<string, unknown>
  })
}

function effectiveRequest(definition: ApiDefinition) {
  return mergeConfig(findTemplate(definition.template_id)?.request || {}, definition.request)
}

function requestSchemaFor(definition: ApiDefinition) {
  const schema = definition.request_schema && typeof definition.request_schema === 'object'
    ? { ...definition.request_schema }
    : {}
  if (definition.protocol === 'http' && !schema.accept) {
    const headers = definition.request?.headers
    if (headers && typeof headers === 'object' && !Array.isArray(headers)) {
      const entry = Object.entries(headers as Record<string, unknown>)
        .find(([name]) => name.toLowerCase() === 'accept')
      if (typeof entry?.[1] === 'string' && entry[1].trim()) schema.accept = entry[1]
    }
  }
  return schema
}

function rawResponseSchemaFor(definition: ApiDefinition) {
  if (definition.response_schema && typeof definition.response_schema === 'object'
    && Object.keys(definition.response_schema).length)
    return { ...definition.response_schema }
  const schema = definition.success_contract?.body_schema
  return schema && typeof schema === 'object' && !Array.isArray(schema)
    ? { ...schema as Record<string, unknown> }
    : {}
}

function responseDataSchema(schema: Record<string, unknown>) {
  const properties = schema.properties
  if (schema.type !== 'object' || !isRecord(properties) || !isRecord(properties.data)) return null
  const code = properties.code
  const required = Array.isArray(schema.required) ? schema.required.map(String) : []
  const hasSuccessSignal = isRecord(code)
    && ('const' in code || Array.isArray(code.enum))
  if (!(required.includes('code') && required.includes('data')) && !hasSuccessSignal) return null
  return properties.data
}

function responseUnpackFor(definition: ApiDefinition) {
  const configured = definition.response_unpack && typeof definition.response_unpack === 'object'
    ? { ...definition.response_unpack }
    : {}
  if (configured.enabled === true) {
    if (typeof configured.source !== 'string' || !configured.source.trim()) configured.source = 'body.data'
    return configured
  }
  const legacySchema = rawResponseSchemaFor(definition)
  if (definition.protocol === 'http' && responseDataSchema(legacySchema)) {
    return { enabled: true, source: 'body.data', envelope_schema: legacySchema }
  }
  return defaultResponseUnpack(definition.protocol)
}

function responseSchemaFor(definition: ApiDefinition) {
  const schema = rawResponseSchemaFor(definition)
  const unpack = responseUnpackFor(definition)
  if (unpack.enabled === true && unpack.source === 'body.data') return responseDataSchema(schema) || schema
  return schema
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
  Object.assign(form, { key: '', group_path: selectedGroupPath.value === '/' ? '/' : selectedGroupPath.value, name: '', protocol: 'http', template_id: null, success_assertion_id: undefined, description: '', request: pretty(defaultRequest('http')), request_schema: pretty(defaultRequestSchema('http')), response_schema: pretty(defaultResponseSchema('http')), response_unpack: pretty(defaultResponseUnpack('http')), parameters: '[]', examples: '[]', success_contract: pretty(defaultSuccessContract('http')), response_variants: '[]' })
  editorMode.value = 'visual'
  editorConfigTab.value = 'request'
  requestPreviewOpen.value = false
  advancedError.value = ''
  syncPathParameters(parsePathParameterNames(requestAddress.value))
  dialog.value = true
}

function openEdit(row: ApiDefinition) {
  editingId.value = row.id
  Object.assign(form, { key: row.key, group_path: normalizeGroupPath(row.group_path), name: row.name, protocol: row.protocol, template_id: row.template_id, success_assertion_id: row.success_assertion_id, description: row.description, request: pretty(row.request), request_schema: pretty(requestSchemaFor(row)), response_schema: pretty(responseSchemaFor(row)), response_unpack: pretty(responseUnpackFor(row)), parameters: pretty(row.parameters), examples: pretty(row.examples), success_contract: pretty(Object.keys(row.success_contract || {}).length ? row.success_contract : defaultSuccessContract(row.protocol)), response_variants: pretty(row.response_variants) })
  editorMode.value = 'visual'
  editorConfigTab.value = 'request'
  requestPreviewOpen.value = false
  advancedError.value = ''
  syncPathParameters(parsePathParameterNames(requestAddress.value))
  dialog.value = true
}

function switchProtocol(protocol: 'http' | 'ws') {
  form.protocol = protocol
  form.template_id = null
  form.success_assertion_id = undefined
  form.request_schema = pretty(defaultRequestSchema(protocol))
  form.response_schema = pretty(defaultResponseSchema(protocol))
  form.response_unpack = pretty(defaultResponseUnpack(protocol))
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
    form.request_schema = pretty(defaultRequestSchema(template.protocol))
    form.response_schema = pretty(defaultResponseSchema(template.protocol))
    form.response_unpack = pretty(defaultResponseUnpack(template.protocol))
  }
  syncPathParameters(parsePathParameterNames(requestAddress.value))
}

function advancedConfig() {
  const parse = (value: string) => {
    try { return JSON.parse(value) }
    catch { return {} }
  }
  return {
    key: displayKey.value,
    group_path: normalizeGroupPath(form.group_path),
    name: form.name,
    protocol: form.protocol,
    template_id: form.template_id,
    success_assertion_id: form.success_assertion_id,
    description: form.description,
    request: parse(form.request),
    request_schema: parse(form.request_schema),
    parameters: parse(form.parameters),
    response_schema: parse(form.response_schema),
    response_unpack: parse(form.response_unpack),
    success_contract: parse(form.success_contract),
    response_variants: parse(form.response_variants),
    examples: parse(form.examples),
  }
}

function syncAdvancedDraft() {
  advancedDraft.value = pretty(advancedConfig())
  advancedError.value = ''
}

function applyAdvancedDraft() {
  try {
    const value = JSON.parse(advancedDraft.value) as Record<string, unknown>
    if (!value || typeof value !== 'object' || Array.isArray(value))
      throw new Error('高级 JSON 必须是对象')
    if (value.name !== undefined && typeof value.name !== 'string')
      throw new Error('name 必须是字符串')
    if (value.protocol !== undefined && value.protocol !== 'http' && value.protocol !== 'ws')
      throw new Error('protocol 只能是 http 或 ws')
    form.name = String(value.name || '')
    form.group_path = normalizeGroupPath(value.group_path)
    form.protocol = (value.protocol || form.protocol) as 'http' | 'ws'
    form.template_id = typeof value.template_id === 'string' ? value.template_id : null
    form.success_assertion_id = typeof value.success_assertion_id === 'string'
      ? value.success_assertion_id : value.success_assertion_id === null ? null : undefined
    form.description = String(value.description || '')
    form.request = pretty(value.request && typeof value.request === 'object' ? value.request : {})
    form.request_schema = pretty(value.request_schema && typeof value.request_schema === 'object' ? value.request_schema : {})
    form.parameters = pretty(Array.isArray(value.parameters) ? value.parameters : [])
    form.response_schema = pretty(value.response_schema && typeof value.response_schema === 'object' ? value.response_schema : {})
    form.response_unpack = pretty(value.response_unpack && typeof value.response_unpack === 'object'
      ? value.response_unpack
      : defaultResponseUnpack(form.protocol))
    form.success_contract = pretty(value.success_contract && typeof value.success_contract === 'object' ? value.success_contract : {})
    form.response_variants = pretty(Array.isArray(value.response_variants) ? value.response_variants : [])
    form.examples = pretty(Array.isArray(value.examples) ? value.examples : [])
    syncPathParameters(parsePathParameterNames(requestAddress.value))
    advancedError.value = ''
    return true
  } catch (error) {
    advancedError.value = (error as Error).message
    return false
  }
}

function switchEditorMode(value: 'visual' | 'json') {
  if (value === 'json') {
    syncAdvancedDraft()
    editorMode.value = value
    return
  }
  if (applyAdvancedDraft()) editorMode.value = value
}

function openRequestPreview() {
  if (editorMode.value === 'json' && !applyAdvancedDraft()) return
  requestPreviewOpen.value = true
}

function updateResponseSchema(value: Record<string, unknown>) {
  form.response_schema = pretty(value)
}

function parsePathParameterNames(value: string) {
  const normalized = value.replace(/\{\{[^}]+}}/g, '')
  const names = new Set<string>()
  for (const match of normalized.matchAll(/\{([A-Za-z_][A-Za-z0-9_]*)}/g)) names.add(match[1])
  for (const match of normalized.matchAll(/(?:^|\/)\:([A-Za-z_][A-Za-z0-9_]*)/g)) names.add(match[1])
  return [...names]
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
    if (editorMode.value === 'json' && !applyAdvancedDraft()) return
    const requestSchema = parseJson<Record<string, unknown>>(form.request_schema, '请求 Schema')
    const request = parseJson<Record<string, unknown>>(form.request, '请求配置')
    const responseSchema = parseJson<Record<string, unknown>>(form.response_schema, '响应 Schema')
    const responseUnpack = parseJson<Record<string, unknown>>(form.response_unpack, '响应解包配置')
    const successContract = parseJson<Record<string, unknown>>(form.success_contract, '成功契约')
    form.group_path = normalizeGroupPath(form.group_path)
    if (form.protocol === 'http' && typeof requestSchema.accept === 'string') {
      const accept = requestSchema.accept.trim()
      const headers = request.headers && typeof request.headers === 'object'
        && !Array.isArray(request.headers)
        ? { ...(request.headers as Record<string, unknown>) }
        : {}
      Object.keys(headers).forEach((name) => {
        if (name.toLowerCase() === 'accept') delete headers[name]
      })
      if (accept) headers.Accept = accept
      request.headers = headers
    }
    const payload: Record<string, unknown> = {
      project_id: projectId.value, key: routeKey.value || form.key, group_path: form.group_path, name: form.name, protocol: form.protocol,
      template_id: form.template_id,
      description: form.description,
      request,
      request_schema: requestSchema,
      response_schema: responseSchema,
      response_unpack: responseUnpack,
      parameters: parseJson<Record<string, unknown>[]>(form.parameters, '参数说明'),
      examples: parseJson<Record<string, unknown>[]>(form.examples, '参考案例'),
      success_contract: Object.keys(responseSchema).length
        ? { ...successContract, body_schema: responseSchema }
        : successContract,
      response_variants: parseJson<Record<string, unknown>[]>(form.response_variants, '响应分支'),
    }
    if (editingId.value || form.success_assertion_id !== undefined)
      payload.success_assertion_id = form.success_assertion_id
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

function findAssertion(assertionId: string | null) {
  return assertions.value.find((assertion) => assertion.id === assertionId)
}

async function execute() {
  if (!executing.value) return
  try {
    const missing = effectiveParameters(executing.value)
      .filter((parameter) => Boolean(parameter.required)
        && parameterChildren(parameter).length === 0
        && executionParameterValue(parameter) === undefined)
      .map((parameter) => parameterDisplayName(parameter))
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
  selectedGroupPath.value = '/'
  activeGroupActionPath.value = null
  void load()
}, { immediate: true })
watch(activeTab, (tab) => {
  if (tab === 'apis') apiPage.value = 1
  else templatePage.value = 1
})
watch([apiSearch, selectedGroupPath], () => { apiPage.value = 1 })
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
          placeholder="搜索名称、Key 或 URL"
          aria-label="搜索 API 名称、Key 或 URL"
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
  <div v-if="activeTab === 'apis'" class="api-list-layout">
    <aside class="api-group-sidebar">
      <div class="api-group-heading">
        <div><strong>API 目录</strong><span>按业务分组管理接口</span></div>
        <el-tag size="small" effect="plain">{{ definitions.length }}</el-tag>
      </div>
      <el-tree
        class="api-group-tree"
        :data="apiGroupTree"
        node-key="path"
        highlight-current
        default-expand-all
        :current-node-key="selectedGroupPath"
        :props="{ label: 'label', children: 'children' }"
        aria-label="API 分组目录"
        @node-click="selectApiGroup"
      >
        <template #default="{ data }">
          <div class="api-group-node" :title="data.path">
            <span>{{ data.label }}</span>
            <div class="api-group-node-tools">
              <small class="api-group-count">{{ data.count }}</small>
              <el-button
                v-if="activeGroupActionPath !== data.path"
                class="api-group-menu-trigger"
                link
                :icon="MoreFilled"
                :aria-label="`打开${data.label}的目录操作`"
                title="更多操作"
                @click.stop="toggleGroupActions(data.path)"
              />
              <div v-else class="api-group-actions" @click.stop>
                <el-button
                  class="api-group-action"
                  link
                  :icon="Plus"
                  :aria-label="`在${data.label}下新增目录`"
                  title="新增子目录"
                  @click.stop="createApiGroup(data)"
                />
                <template v-if="data.id">
                  <el-button
                    class="api-group-action"
                    link
                    :icon="Edit"
                    :aria-label="`编辑${data.label}`"
                    title="编辑目录"
                    @click.stop="renameApiGroup(data)"
                  />
                  <el-button
                    class="api-group-action is-danger"
                    link
                    :icon="Delete"
                    :aria-label="`删除${data.label}`"
                    title="删除目录"
                    @click.stop="removeApiGroup(data)"
                  />
                </template>
              </div>
            </div>
          </div>
        </template>
      </el-tree>
    </aside>
    <el-card class="panel api-list-content" shadow="never">
      <el-table class="list-table" :data="pagedDefinitions">
        <el-table-column prop="name" label="名称" fixed="left" min-width="180" align="center" show-overflow-tooltip />
        <el-table-column label="分组目录" min-width="190" align="left" show-overflow-tooltip><template #default="scope"><code class="api-group-path">{{ normalizeGroupPath(scope.row.group_path) }}</code></template></el-table-column>
        <el-table-column label="URL / 请求目标" min-width="300" align="left" show-overflow-tooltip><template #default="scope"><code>{{ requestTarget(scope.row) }}</code></template></el-table-column>
        <el-table-column label="协议类型" width="100" align="center"><template #default="scope"><el-tag :type="scope.row.protocol === 'http' ? 'success' : 'warning'" effect="dark">{{ scope.row.protocol.toUpperCase() }}</el-tag></template></el-table-column>
        <el-table-column prop="key" label="Key" min-width="180" align="center" show-overflow-tooltip />
        <el-table-column label="Accept" min-width="170" align="center" show-overflow-tooltip><template #default="scope"><code v-if="scope.row.protocol === 'http'">{{ requestSchemaFor(scope.row).accept || '默认 application/json' }}</code><span v-else class="muted">—</span></template></el-table-column>
        <el-table-column label="模板" min-width="140" align="center"><template #default="scope"><el-tag v-if="findTemplate(scope.row.template_id)" effect="plain">{{ findTemplate(scope.row.template_id)?.name }}</el-tag><span v-else class="muted">无</span></template></el-table-column>
        <el-table-column label="成功条件" min-width="150" align="center"><template #default="scope"><el-tag v-if="findAssertion(scope.row.success_assertion_id)" type="success" effect="plain">{{ findAssertion(scope.row.success_assertion_id)?.name }}</el-tag><span v-else class="muted">兼容契约</span></template></el-table-column>
        <el-table-column prop="description" label="功能说明" min-width="190" align="left" show-overflow-tooltip />
        <el-table-column label="有效参数" width="90" align="center"><template #default="scope">{{ effectiveParameterCount(scope.row) }}</template></el-table-column>
        <el-table-column label="操作" fixed="right" width="200" align="center"><template #default="scope"><div class="icon-action-group"><el-button class="icon-action-button" link type="success" :icon="VideoPlay" aria-label="执行" @click="openExecute(scope.row)"><span class="icon-action-label">执行</span></el-button><el-button class="icon-action-button" link type="primary" :icon="Edit" aria-label="编辑" @click="openEdit(scope.row)"><span class="icon-action-label">编辑</span></el-button><el-button class="icon-action-button" link type="danger" :icon="Delete" aria-label="删除" @click="remove(scope.row)"><span class="icon-action-label">删除</span></el-button></div></template></el-table-column>
      </el-table>
      <div v-if="projectId && !definitions.length" class="empty-state">当前项目还没有 API。</div>
      <div v-else-if="projectId && !filteredDefinitions.length" class="empty-state">当前目录下未找到匹配的 API。</div>
      <div v-if="!projectId" class="empty-state">请先创建一个项目。</div>
    </el-card>
  </div>

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
        <div class="api-dialog-title-group">
          <h2>{{ editingId ? '编辑 API' : '登记 API' }}</h2>
          <div class="api-dialog-key" :title="displayKey || '未生成稳定 Key'">
            <span>KEY</span>
            <code>{{ displayKey || '未生成稳定 Key' }}</code>
          </div>
        </div>
        <div class="api-dialog-header-actions">
          <el-segmented :model-value="editorMode" :options="[{ label: '可视化', value: 'visual' }, { label: '高级 JSON', value: 'json' }]" aria-label="编辑模式" @update:model-value="switchEditorMode" />
          <el-tag :type="form.protocol === 'http' ? 'success' : 'warning'" effect="dark">{{ form.protocol === 'http' ? 'HTTP' : 'WebSocket' }}</el-tag>
        </div>
      </div>
    </template>
    <div v-if="editorMode === 'json'" class="api-advanced-config">
      <div class="api-advanced-heading">
        <div><strong>完整 API 配置</strong><p>一次编辑基础信息、请求配置、请求参数、响应字段和成功条件引用；切回可视化前会校验 JSON。</p></div>
      </div>
      <div class="api-code-editor api-advanced-code-editor">
        <div class="api-code-editor-heading"><span>api-definition.json</span><span class="api-code-dots"><i></i><i></i><i></i></span></div>
        <el-input v-model="advancedDraft" class="json-input api-advanced-input" type="textarea" :rows="26" spellcheck="false" aria-label="完整 API JSON" />
      </div>
      <p v-if="advancedError" class="field-error">{{ advancedError }}</p>
      <p v-else class="api-advanced-hint">保存时仍会执行请求 Schema、响应 Schema、成功条件和协议一致性校验。</p>
    </div>
    <div v-else class="api-editor-workspace">
      <div class="api-request-head">
        <div :class="['api-request-method', `is-${requestMethod.toLowerCase()}`]">{{ requestMethod }}</div>
        <div class="api-request-endpoint">
          <code>{{ requestTargetPreview }}</code>
          <p>{{ form.name || '未命名 API' }} · {{ form.protocol === 'http' ? 'HTTP API' : 'WebSocket API' }}</p>
        </div>
        <div class="api-request-environment"><span class="api-environment-dot"></span> 当前项目</div>
      </div>

      <div class="api-editor-content">
        <el-form label-position="top" class="api-editor-form api-editor-single-page api-editor-main">
          <section class="api-editor-section api-editor-section-intro">
        <div class="api-section-heading"><span class="api-section-index">01</span><div><h3>接口信息</h3><p>定义 API 的稳定身份、请求目标，以及在文档中的基本描述。</p></div></div>
        <div class="api-basic-grid">
          <el-form-item label="API 名称" required><el-input v-model="form.name" placeholder="例如：查询用户订单" /></el-form-item>
          <el-form-item label="API 模板">
            <el-select v-model="form.template_id" clearable placeholder="不使用模板" style="width: 100%" @change="selectTemplate">
              <el-option v-for="item in availableTemplates" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="分组目录" class="api-group-path-field"><el-input v-model="form.group_path" placeholder="例如：/用户服务/用户管理" /></el-form-item>
        </div>
        <div class="api-target-grid" :class="{ 'is-ws': form.protocol === 'ws' }">
          <el-form-item label="协议" class="api-protocol-field">
            <el-radio-group :model-value="form.protocol" @update:model-value="switchProtocol"><el-radio-button value="http">HTTP</el-radio-button><el-radio-button value="ws">WS</el-radio-button></el-radio-group>
          </el-form-item>
          <el-form-item v-if="form.protocol === 'http'" label="请求方法" class="api-method-field">
            <el-select :model-value="requestMethod" aria-label="请求方法" style="width: 100%" @update:model-value="updateRequestConfig({ method: $event })">
              <el-option v-for="method in ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'TRACE']" :key="method" :label="method" :value="method" />
            </el-select>
          </el-form-item>
          <el-form-item :label="form.protocol === 'http' ? '请求目标（URL / 路径）' : 'WebSocket 地址'" class="api-address-field">
            <div class="endpoint-builder">
              <div v-if="inheritedRequestBase" class="base-url-prefix" :title="inheritedRequestBase">{{ inheritedRequestBase }}</div>
              <el-input :model-value="requestAddress" :placeholder="form.protocol === 'http' ? (inheritedRequestBase ? '/users/{user_id}/orders/{order_id}' : '{{ base_url }}/users/{user_id}') : 'wss://example.com/ws/{channel}'" aria-label="请求地址" @update:model-value="updateRequestTarget" />
            </div>
            <p v-if="inheritedRequestBase" class="request-target-hint">模板已提供基础地址，这里填写接口相对路径。</p>
          </el-form-item>
        </div>
        <el-form-item label="功能说明" class="api-description-field"><el-input v-model="form.description" type="textarea" :rows="1" placeholder="简要说明这个 API 做什么、适用于什么场景" /></el-form-item>
          </section>

          <el-tabs v-model="editorConfigTab" class="api-config-tabs" aria-label="API 配置模块">
            <el-tab-pane label="请求配置" name="request">
              <section class="api-editor-section api-editor-section-request">
                <div class="api-section-heading api-section-heading-with-action">
                  <span class="api-section-index">02</span>
                  <div><h3>请求配置</h3><p>维护 Query、Header 和 Body 参数契约。</p></div>
                  <el-button type="primary" plain size="small" :icon="Plus" @click="addParameter">添加参数</el-button>
                </div>
                <ApiRequestEditor
                  v-if="form.protocol === 'ws'"
                  v-model="form.request"
                  :protocol="form.protocol"
                />
                <ApiParametersEditor ref="parameterEditor" v-model="parameterItems" :path-params="pathParameterNames" />
              </section>
            </el-tab-pane>

            <el-tab-pane label="响应配置" name="response">
              <section class="api-editor-section api-editor-section-response">
                <div class="api-section-heading api-section-heading-with-meta"><span class="api-section-index">03</span><div><h3>响应配置</h3><p>配置响应媒体类型、成功条件和响应字段结构。</p></div></div>
                <div :class="['response-config-grid', { 'is-http': form.protocol === 'http' }]">
                  <div class="response-contract-card">
                    <div class="response-config-card-heading"><strong>响应契约</strong><span>类型与判定</span></div>
                    <div class="response-config-fields">
                      <el-form-item v-if="form.protocol === 'http'" label="响应媒体类型（Accept）" class="response-accept-field response-floating-field">
                        <el-select
                          v-model="requestSchemaAccept"
                          class="response-accept-select"
                          filterable
                          allow-create
                          clearable
                          default-first-option
                          popper-class="response-accept-popper"
                          placeholder="选择或输入媒体类型"
                        >
                          <el-option v-for="option in commonAcceptOptions" :key="option.value" :label="option.value" :value="option.value">
                            <span>{{ option.label }}</span><code>{{ option.value }}</code>
                          </el-option>
                        </el-select>
                      </el-form-item>
                      <el-form-item label="成功条件" class="response-success-assertion-field response-floating-field">
                        <el-select v-model="form.success_assertion_id" clearable placeholder="选择一个成功条件">
                          <el-option v-for="item in assertions" :key="item.id" :label="item.name" :value="item.id">
                            <span>{{ item.name }}</span><code class="select-option-key">{{ item.key }}</code>
                          </el-option>
                        </el-select>
                      </el-form-item>
                    </div>
                  </div>
                  <div v-if="form.protocol === 'http'" class="response-unpack-panel">
                    <div class="response-unpack-heading">
                      <div>
                        <strong>响应解包</strong>
                        <p>保留原始 body，按路径提取 payload；响应字段按解包后的数据填写。</p>
                      </div>
                      <el-switch v-model="responseUnpackEnabled" active-text="启用" inactive-text="关闭" />
                    </div>
                    <div v-if="responseUnpackEnabled" class="response-unpack-controls">
                      <el-form-item label="解包路径">
                        <el-select v-model="responseUnpackSource" filterable allow-create default-first-option placeholder="例如：body.data">
                          <el-option label="响应体 data" value="body.data" />
                          <el-option label="响应体 result" value="body.result" />
                          <el-option label="响应体 payload" value="body.payload" />
                        </el-select>
                      </el-form-item>
                      <div class="response-unpack-flow"><code>response.body</code><span>→</span><code>response.payload</code></div>
                    </div>
                  </div>
                </div>
                <ApiResponseFieldsEditor :model-value="responseSchemaConfig" @update:model-value="updateResponseSchema" />
              </section>
            </el-tab-pane>
          </el-tabs>
        </el-form>
      </div>
    </div>
    <template #footer>
      <div class="api-editor-footer">
        <el-button plain @click="openRequestPreview">请求预览</el-button>
        <div class="api-editor-footer-actions">
          <el-button @click="dialog = false">取消</el-button>
          <el-button type="primary" :disabled="!displayKey || !form.name" @click="save">保存</el-button>
        </div>
      </div>
    </template>
  </el-dialog>

  <el-dialog
    v-model="requestPreviewOpen"
    title="请求预览"
    width="860px"
    class="api-request-preview-dialog"
  >
    <div class="api-request-preview-body">
      <section class="api-request-preview-section">
        <div class="api-request-preview-section-head">
          <strong>REQUEST</strong>
          <small>模板配置与当前 API 配置合并后的请求</small>
        </div>
        <pre class="api-request-preview-code">{{ requestPreviewText }}</pre>
      </section>

      <section class="api-request-preview-section">
        <div class="api-request-preview-section-head">
          <strong>RESPONSE</strong>
          <small>按响应 Schema、成功契约和参考案例生成的预期响应</small>
        </div>
        <pre class="api-request-preview-code api-request-preview-code-response">{{ responsePreviewText }}</pre>
      </section>

      <section v-if="requestPreviewTemplate" class="api-request-preview-section api-request-preview-template">
        <div class="api-request-preview-section-head">
          <strong>API TEMPLATE</strong>
          <small>{{ requestPreviewTemplate.name }}</small>
        </div>
        <pre class="api-request-preview-code api-request-preview-code-template">{{ requestPreviewTemplateText }}</pre>
      </section>

      <p class="api-request-preview-note">仅展示按当前配置拼接的请求与预期响应；选择 API 模板时同时展示模板配置，不会发送请求。</p>
    </div>
    <template #footer>
      <el-button @click="requestPreviewOpen = false">关闭</el-button>
    </template>
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
                  <code :style="{ paddingLeft: `${Number(parameter.parameter_depth || 0) * 12}px` }">{{ parameterDisplayName(parameter) }}</code>
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
