<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { api } from '../api/client'
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
const form = reactive({
  name: '', protocol: 'http' as 'http' | 'ws', template_id: null as string | null,
  assertion_profile_id: undefined as string | null | undefined,
  description: '', request: '{}',
  parameters: '[]', examples: '[]', response_variants: '[]',
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
  Object.assign(form, { name: '', protocol: 'http', template_id: null, assertion_profile_id: undefined, description: '', request: pretty(defaultRequest('http')), parameters: '[]', examples: '[]', response_variants: '[]' })
  dialog.value = true
}

function openEdit(row: ApiDefinition) {
  editingId.value = row.id
  Object.assign(form, { name: row.name, protocol: row.protocol, template_id: row.template_id, assertion_profile_id: row.assertion_profile_id, description: row.description, request: pretty(row.request), parameters: pretty(row.parameters), examples: pretty(row.examples), response_variants: pretty(row.response_variants) })
  dialog.value = true
}

function switchProtocol(protocol: 'http' | 'ws') {
  form.protocol = protocol
  form.template_id = null
  form.assertion_profile_id = undefined
  if (!editingId.value) form.request = pretty(defaultRequest(protocol))
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
}

async function save() {
  try {
    const payload: Record<string, unknown> = {
      project_id: projectId.value, name: form.name, protocol: form.protocol,
      template_id: form.template_id,
      description: form.description,
      request: parseJson<Record<string, unknown>>(form.request, '请求配置'),
      parameters: parseJson<Record<string, unknown>[]>(form.parameters, '参数说明'),
      examples: parseJson<Record<string, unknown>[]>(form.examples, '参考案例'),
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
      <el-table-column label="协议" width="92"><template #default="scope"><el-tag :type="scope.row.protocol === 'http' ? 'success' : 'warning'" effect="dark">{{ scope.row.protocol.toUpperCase() }}</el-tag></template></el-table-column>
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column label="模板" min-width="140"><template #default="scope"><el-tag v-if="findTemplate(scope.row.template_id)" effect="plain">{{ findTemplate(scope.row.template_id)?.name }}</el-tag><span v-else class="muted">无</span></template></el-table-column>
      <el-table-column label="断言集合" min-width="150"><template #default="scope"><el-tag v-if="findProfile(scope.row.assertion_profile_id)" type="success" effect="plain">{{ findProfile(scope.row.assertion_profile_id)?.name }}</el-tag><span v-else class="muted">无</span></template></el-table-column>
      <el-table-column prop="description" label="功能说明" min-width="190" show-overflow-tooltip />
      <el-table-column label="有效请求目标" min-width="280" show-overflow-tooltip><template #default="scope"><code>{{ requestTarget(scope.row) }}</code></template></el-table-column>
      <el-table-column label="有效参数" width="90"><template #default="scope">{{ effectiveParameterCount(scope.row) }}</template></el-table-column>
      <el-table-column label="操作" width="200" align="right"><template #default="scope"><el-button link type="success" @click="openExecute(scope.row)">执行</el-button><el-button link type="primary" @click="openEdit(scope.row)">编辑</el-button><el-button link type="danger" @click="remove(scope.row)">删除</el-button></template></el-table-column>
    </el-table>
    <div v-if="projectId && !definitions.length" class="empty-state">当前项目还没有 API。</div>
    <div v-if="!projectId" class="empty-state">请先创建一个项目。</div>
  </el-card>

  <el-card v-else class="panel" shadow="never">
    <el-table :data="templates">
      <el-table-column label="协议" width="92"><template #default="scope"><el-tag :type="scope.row.protocol === 'http' ? 'success' : 'warning'" effect="dark">{{ scope.row.protocol.toUpperCase() }}</el-tag></template></el-table-column>
      <el-table-column prop="name" label="模板名称" min-width="180" />
      <el-table-column prop="description" label="说明" min-width="240" show-overflow-tooltip />
      <el-table-column label="基础地址" min-width="260" show-overflow-tooltip><template #default="scope"><code>{{ scope.row.request.url || scope.row.request.base_url || '—' }}</code></template></el-table-column>
      <el-table-column label="引用 API" width="100"><template #default="scope"><el-tag effect="plain">{{ scope.row.usage_count }}</el-tag></template></el-table-column>
      <el-table-column label="公共参数" width="100"><template #default="scope">{{ scope.row.parameters.length }}</template></el-table-column>
      <el-table-column label="操作" width="140" align="right"><template #default="scope"><el-button link type="primary" @click="openTemplateEdit(scope.row)">编辑</el-button><el-button link type="danger" @click="removeTemplate(scope.row)">删除</el-button></template></el-table-column>
    </el-table>
    <div v-if="projectId && !templates.length" class="empty-state">还没有 API 模板。创建模板后可统一维护基础地址、请求头和超时等配置。</div>
  </el-card>

  <el-dialog v-model="dialog" :title="editingId ? '编辑 API' : '登记 API'" width="760px">
    <el-form label-position="top">
      <div class="two-col">
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="协议"><el-radio-group :model-value="form.protocol" @update:model-value="switchProtocol"><el-radio-button value="http">HTTP</el-radio-button><el-radio-button value="ws">WebSocket</el-radio-button></el-radio-group></el-form-item>
      </div>
      <el-form-item label="API 模板">
        <el-select v-model="form.template_id" clearable placeholder="不使用模板" style="width: 100%" @change="selectTemplate">
          <el-option v-for="item in availableTemplates" :key="item.id" :label="item.name" :value="item.id" />
        </el-select>
        <div class="muted">模板配置会作为基础值，当前 API 的请求配置只需填写差异。</div>
      </el-form-item>
      <el-form-item label="默认断言集合">
        <el-select v-model="form.assertion_profile_id" clearable placeholder="自动使用当前协议的默认集合" style="width: 100%">
          <el-option v-for="item in availableProfiles" :key="item.id" :label="`${item.name}${item.is_default ? '（默认）' : ''}`" :value="item.id" />
        </el-select>
        <div class="muted">新建 API 不选择时自动绑定默认集合；绑定后，集合内容的修改会实时生效。</div>
      </el-form-item>
      <el-alert v-if="findTemplate(form.template_id)" type="success" :closable="false" show-icon>
        <template #title>继承自 {{ findTemplate(form.template_id)?.name }}</template>
        <pre class="template-preview">{{ pretty(findTemplate(form.template_id)?.request) }}</pre>
      </el-alert>
      <el-form-item label="功能说明"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
      <el-tabs>
        <el-tab-pane label="API 请求覆盖"><el-input v-model="form.request" class="json-input" type="textarea" :rows="12" /><p class="muted">合并优先级：模板配置 &lt; API 覆盖。使用模板的 API 推荐通过 <code>path</code> 声明路径。</p></el-tab-pane>
        <el-tab-pane label="参数说明"><el-input v-model="form.parameters" class="json-input" type="textarea" :rows="12" /><p class="muted">示例：[{ "name": "symbol", "in": "query", "required": true, "description": "交易对" }]</p></el-tab-pane>
        <el-tab-pane label="参考案例"><el-input v-model="form.examples" class="json-input" type="textarea" :rows="12" /></el-tab-pane>
        <el-tab-pane label="响应分支"><el-input v-model="form.response_variants" class="json-input" type="textarea" :rows="12" /><p class="muted">每个分支可配置 <code>name</code>、<code>match</code>、<code>schema</code>、<code>assertion_profile_ids</code> 和局部 <code>assertions</code>。</p></el-tab-pane>
      </el-tabs>
    </el-form>
    <template #footer><el-button @click="dialog = false">取消</el-button><el-button type="primary" :disabled="!form.name" @click="save">保存</el-button></template>
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
        <el-form-item label="运行输入（合并到项目上下文）"><el-input v-model="executeForm.inputs" class="json-input" type="textarea" :rows="7" /></el-form-item>
        <el-form-item label="本次请求覆盖"><el-input v-model="executeForm.request" class="json-input" type="textarea" :rows="7" /></el-form-item>
      </el-form>
      <div><p class="muted" style="margin-bottom: 8px">请求 / 响应</p><pre class="code-block">{{ executionResult ? pretty(executionResult) : '等待执行…' }}</pre></div>
    </div>
    <template #footer><el-button @click="executeDialog = false">关闭</el-button><el-button type="primary" @click="execute">执行请求</el-button></template>
  </el-dialog>
</template>
