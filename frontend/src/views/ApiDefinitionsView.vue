<script setup lang="ts">
import { Delete, Edit, VideoPlay } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { api } from '../api/client'
import ApiParametersEditor from '../components/ApiParametersEditor.vue'
import type { ApiDefinition, ApiTemplate, AssertionProfile, Project } from '../types'
import { parseJson, pretty } from '../utils'

const projects = ref<Project[]>([])
const definitions = ref<ApiDefinition[]>([])
const templates = ref<ApiTemplate[]>([])
const profiles = ref<AssertionProfile[]>([])
const projectId = ref('')
const activeTab = ref<'apis' | 'templates'>('apis')
const dialog = ref(false)
const templateDialog = ref(false)
const executeDialog = ref(false)
const editingId = ref('')
const editingTemplateId = ref('')
const executing = ref<ApiDefinition | null>(null)
const executionResult = ref<object | null>(null)
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
const requestAddressPlaceholder = computed(() => inheritedRequestBase.value
  ? (form.protocol === 'http' ? '/users/{user_id}' : '/channels/{channel_id}')
  : (form.protocol === 'http' ? '{{ base_url }}/users/{user_id}' : 'wss://example.com/ws/{channel_id}'))
const requestMethod = computed(() => form.protocol === 'ws'
  ? 'WS'
  : String(requestConfig.value.method || 'GET').toUpperCase())
const requestEndpoint = computed(() => {
  const request = requestConfig.value
  if (request.url) return String(request.url)
  const template = findTemplate(form.template_id)
  const base = String(template?.request.base_url || template?.request.url || request.base_url || '')
  const path = String(request.path || '')
  if (base && path) return `${base.replace(/\/$/, '')}/${path.replace(/^\//, '')}`
  return path || (form.protocol === 'ws' ? '填写 WebSocket 地址' : '填写请求路径')
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
    ? { method: 'GET', url: '{{ base_url }}/health', headers: {}, query: {} }
    : { url: '{{ ws_url }}', headers: {}, messages: [{ type: 'ping' }], receive_count: 1 }
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
    : { base_url: '{{ ws_url }}', headers: {}, timeout_seconds: 30 }
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

function effectiveRequest(definition: ApiDefinition) {
  return mergeConfig(findTemplate(definition.template_id)?.request || {}, definition.request)
}

function requestTarget(definition: ApiDefinition) {
  const request = effectiveRequest(definition)
  if (request.url) return `${request.method || ''} ${request.url}`
  return `${request.method || ''} ${request.base_url || ''}${request.path || ''}`
}

function effectiveParameterCount(definition: ApiDefinition) {
  return (findTemplate(definition.template_id)?.parameters.length || 0)
    + definition.parameters.length
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
      ? { method: 'GET', path: '/health' }
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
  executeDialog.value = true
}

function findProfile(profileId: string | null) {
  return profiles.value.find((profile) => profile.id === profileId)
}

async function execute() {
  if (!executing.value) return
  try {
    executionResult.value = await api.definitions.execute(
      executing.value.id,
      parseJson<object>(executeForm.inputs, '运行输入'),
      parseJson<object>(executeForm.request, '请求覆盖'),
    )
    ElMessage.success('执行完成')
  } catch (error) { ElMessage.error((error as Error).message) }
}

watch(projectId, load)
onMounted(async () => {
  try { projects.value = await api.projects.list(); projectId.value = projects.value[0]?.id || '' }
  catch (error) { ElMessage.error((error as Error).message) }
})
</script>

<template>
  <div class="page-head">
    <div><h2>API 资产</h2><p>用项目模板复用公共配置，再为每个 API 维护差异并直接执行。</p></div>
    <el-button v-if="activeTab === 'apis'" type="primary" :disabled="!projectId" @click="openCreate">登记 API</el-button>
    <el-button v-else type="primary" :disabled="!projectId" @click="openTemplateCreate">新建模板</el-button>
  </div>
  <div class="toolbar">
    <el-select v-model="projectId" placeholder="选择项目" style="width: 260px"><el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" /></el-select>
    <el-radio-group v-model="activeTab">
      <el-radio-button value="apis">API 列表</el-radio-button>
      <el-radio-button value="templates">API 模板</el-radio-button>
    </el-radio-group>
  </div>
  <el-card v-if="activeTab === 'apis'" class="panel" shadow="never">
    <el-table :data="definitions">
      <el-table-column prop="name" label="名称" fixed="left" min-width="180" show-overflow-tooltip />
      <el-table-column label="URL / 请求目标" min-width="300" show-overflow-tooltip><template #default="scope"><code>{{ requestTarget(scope.row) }}</code></template></el-table-column>
      <el-table-column label="协议类型" width="100"><template #default="scope"><el-tag :type="scope.row.protocol === 'http' ? 'success' : 'warning'" effect="dark">{{ scope.row.protocol.toUpperCase() }}</el-tag></template></el-table-column>
      <el-table-column prop="key" label="Key" min-width="180" show-overflow-tooltip />
      <el-table-column label="模板" min-width="140"><template #default="scope"><el-tag v-if="findTemplate(scope.row.template_id)" effect="plain">{{ findTemplate(scope.row.template_id)?.name }}</el-tag><span v-else class="muted">无</span></template></el-table-column>
      <el-table-column label="成功条件集合" min-width="150"><template #default="scope"><el-tag v-if="findProfile(scope.row.assertion_profile_id)" type="success" effect="plain">{{ findProfile(scope.row.assertion_profile_id)?.name }}</el-tag><span v-else class="muted">无</span></template></el-table-column>
      <el-table-column prop="description" label="功能说明" min-width="190" show-overflow-tooltip />
      <el-table-column label="有效参数" width="90"><template #default="scope">{{ effectiveParameterCount(scope.row) }}</template></el-table-column>
      <el-table-column label="操作" fixed="right" width="200" align="right"><template #default="scope"><el-button class="icon-action-button" link type="success" :icon="VideoPlay" aria-label="执行" @click="openExecute(scope.row)"><span class="icon-action-label">执行</span></el-button><el-button class="icon-action-button" link type="primary" :icon="Edit" aria-label="编辑" @click="openEdit(scope.row)"><span class="icon-action-label">编辑</span></el-button><el-button class="icon-action-button" link type="danger" :icon="Delete" aria-label="删除" @click="remove(scope.row)"><span class="icon-action-label">删除</span></el-button></template></el-table-column>
    </el-table>
    <div v-if="projectId && !definitions.length" class="empty-state">当前项目还没有 API。</div>
    <div v-if="!projectId" class="empty-state">请先创建一个项目。</div>
  </el-card>

  <el-card v-else class="panel" shadow="never">
    <el-table :data="templates">
      <el-table-column prop="name" label="模板名称" fixed="left" min-width="180" show-overflow-tooltip />
      <el-table-column label="基础地址" min-width="280" show-overflow-tooltip><template #default="scope"><code>{{ scope.row.request.url || scope.row.request.base_url || '—' }}</code></template></el-table-column>
      <el-table-column label="协议类型" width="100"><template #default="scope"><el-tag :type="scope.row.protocol === 'http' ? 'success' : 'warning'" effect="dark">{{ scope.row.protocol.toUpperCase() }}</el-tag></template></el-table-column>
      <el-table-column prop="description" label="说明" min-width="240" show-overflow-tooltip />
      <el-table-column label="引用 API" width="100"><template #default="scope"><el-tag effect="plain">{{ scope.row.usage_count }}</el-tag></template></el-table-column>
      <el-table-column label="公共参数" width="100"><template #default="scope">{{ scope.row.parameters.length }}</template></el-table-column>
      <el-table-column label="操作" fixed="right" width="140" align="right"><template #default="scope"><el-button class="icon-action-button" link type="primary" :icon="Edit" aria-label="编辑" @click="openTemplateEdit(scope.row)"><span class="icon-action-label">编辑</span></el-button><el-button class="icon-action-button" link type="danger" :icon="Delete" aria-label="删除" @click="removeTemplate(scope.row)"><span class="icon-action-label">删除</span></el-button></template></el-table-column>
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
          <el-form-item label="协议"><el-radio-group :model-value="form.protocol" @update:model-value="switchProtocol"><el-radio-button value="http">HTTP</el-radio-button><el-radio-button value="ws">WebSocket</el-radio-button></el-radio-group></el-form-item>
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
          <el-form-item v-if="form.protocol === 'http'" label="请求方法">
            <el-select :model-value="requestMethod" style="width: 100%" @update:model-value="updateRequestMethod">
              <el-option v-for="method in ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD']" :key="method" :label="method" :value="method" />
            </el-select>
          </el-form-item>
          <el-form-item label="请求地址" class="request-address-item">
            <el-input :model-value="requestAddress" :placeholder="requestAddressPlaceholder" @update:model-value="updateRequestEndpoint">
              <template v-if="inheritedRequestBase" #prepend><code>{{ inheritedRequestBase }}</code></template>
            </el-input>
            <div class="request-address-hint"><span>最终地址</span><code>{{ requestEndpoint }}</code></div>
          </el-form-item>
        </div>
        <el-form-item label="功能说明"><el-input v-model="form.description" type="textarea" :rows="2" placeholder="简要说明这个 API 做什么、适用于什么场景" /></el-form-item>
      </section>

      <div v-if="findTemplate(form.template_id)" class="inheritance-notice">
        <div><strong>已继承 {{ findTemplate(form.template_id)?.name }}</strong><span>基础地址、公共请求头和超时会自动合并，当前 API 只需填写差异。</span></div>
        <code>{{ findTemplate(form.template_id)?.request.base_url || findTemplate(form.template_id)?.request.url }}</code>
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

  <el-dialog v-model="executeDialog" :title="`执行 · ${executing?.name || ''}`" width="800px">
    <div class="two-col">
      <el-form label-position="top">
        <el-form-item label="运行输入（合并到项目上下文）"><el-input v-model="executeForm.inputs" class="json-input" type="textarea" :rows="7" /><p class="muted">未传入的参数会自动使用 Parameters 中配置的默认值。</p></el-form-item>
        <el-form-item label="本次请求覆盖"><el-input v-model="executeForm.request" class="json-input" type="textarea" :rows="7" /></el-form-item>
      </el-form>
      <div><p class="muted" style="margin-bottom: 8px">请求 / 响应</p><pre class="code-block">{{ executionResult ? pretty(executionResult) : '等待执行…' }}</pre></div>
    </div>
    <template #footer><el-button @click="executeDialog = false">关闭</el-button><el-button type="primary" @click="execute">执行请求</el-button></template>
  </el-dialog>
</template>
