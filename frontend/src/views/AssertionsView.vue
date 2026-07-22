<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref, watch } from 'vue'

import { api } from '../api/client'
import type { AssertionDefinition, AssertionProfile, Project } from '../types'
import { parseJson, pretty } from '../utils'

const projects = ref<Project[]>([])
const definitions = ref<AssertionDefinition[]>([])
const profiles = ref<AssertionProfile[]>([])
const projectId = ref('')
const activeTab = ref<'definitions' | 'profiles'>('definitions')
const definitionDialog = ref(false)
const profileDialog = ref(false)
const editingDefinitionId = ref('')
const editingProfileId = ref('')

const definitionForm = reactive({
  name: '',
  engine: 'expression' as 'path' | 'json_schema' | 'expression',
  description: '',
  config: '{\n  "expression": "response.status_code == 200"\n}',
  default_params: '{}',
  severity: 'error' as 'error' | 'warning',
  message: '',
})
const profileForm = reactive({
  name: '',
  protocol: 'http' as 'http' | 'ws',
  description: '',
  is_default: false,
  bindings: '[]',
})

async function load() {
  if (!projectId.value) { definitions.value = []; profiles.value = []; return }
  try {
    ;[definitions.value, profiles.value] = await Promise.all([
      api.assertionDefinitions.list(projectId.value),
      api.assertionProfiles.list(projectId.value),
    ])
  } catch (error) { ElMessage.error((error as Error).message) }
}

function defaultConfig(engine: 'path' | 'json_schema' | 'expression') {
  if (engine === 'path')
    return { source: 'status_code', operator: 'equals', expected: 200 }
  if (engine === 'json_schema')
    return { source: 'body', schema: { type: 'object', required: [] } }
  return { expression: 'response.status_code == 200' }
}

function openDefinitionCreate() {
  editingDefinitionId.value = ''
  Object.assign(definitionForm, {
    name: '', engine: 'expression', description: '',
    config: pretty(defaultConfig('expression')), default_params: '{}',
    severity: 'error', message: '',
  })
  definitionDialog.value = true
}

function openDefinitionEdit(row: AssertionDefinition) {
  editingDefinitionId.value = row.id
  Object.assign(definitionForm, {
    name: row.name, engine: row.engine, description: row.description,
    config: pretty(row.config), default_params: pretty(row.default_params),
    severity: row.severity, message: row.message,
  })
  definitionDialog.value = true
}

function switchEngine(engine: 'path' | 'json_schema' | 'expression') {
  definitionForm.engine = engine
  if (!editingDefinitionId.value) definitionForm.config = pretty(defaultConfig(engine))
}

async function saveDefinition() {
  try {
    const payload = {
      project_id: projectId.value,
      name: definitionForm.name,
      engine: definitionForm.engine,
      description: definitionForm.description,
      config: parseJson<Record<string, unknown>>(definitionForm.config, '断言配置'),
      default_params: parseJson<Record<string, unknown>>(
        definitionForm.default_params, '默认参数',
      ),
      severity: definitionForm.severity,
      message: definitionForm.message,
    }
    if (editingDefinitionId.value)
      await api.assertionDefinitions.update(editingDefinitionId.value, payload)
    else await api.assertionDefinitions.create(payload)
    definitionDialog.value = false
    ElMessage.success('断言定义已保存')
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
}

async function removeDefinition(row: AssertionDefinition) {
  await ElMessageBox.confirm(`删除断言“${row.name}”？被集合引用时无法删除。`, '确认删除', { type: 'warning' })
  try {
    await api.assertionDefinitions.remove(row.id)
    ElMessage.success('断言定义已删除')
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
}

function openProfileCreate() {
  editingProfileId.value = ''
  Object.assign(profileForm, {
    name: '', protocol: 'http', description: '', is_default: false, bindings: '[]',
  })
  profileDialog.value = true
}

function openProfileEdit(row: AssertionProfile) {
  editingProfileId.value = row.id
  Object.assign(profileForm, {
    name: row.name, protocol: row.protocol, description: row.description,
    is_default: row.is_default, bindings: pretty(row.bindings),
  })
  profileDialog.value = true
}

function addBinding(definition: AssertionDefinition) {
  try {
    const bindings = parseJson<Record<string, unknown>[]>(profileForm.bindings, '集合绑定')
    if (!bindings.some((item) => item.assertion_id === definition.id)) {
      bindings.push({ assertion_id: definition.id, enabled: true, params: {} })
      profileForm.bindings = pretty(bindings)
    }
  } catch (error) { ElMessage.error((error as Error).message) }
}

function definitionName(assertionId: unknown) {
  return definitions.value.find((item) => item.id === assertionId)?.name || assertionId
}

async function saveProfile() {
  try {
    const payload = {
      project_id: projectId.value,
      name: profileForm.name,
      protocol: profileForm.protocol,
      description: profileForm.description,
      is_default: profileForm.is_default,
      bindings: parseJson<Record<string, unknown>[]>(profileForm.bindings, '集合绑定'),
    }
    if (editingProfileId.value)
      await api.assertionProfiles.update(editingProfileId.value, payload)
    else await api.assertionProfiles.create(payload)
    profileDialog.value = false
    ElMessage.success('断言集合已保存')
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
}

async function removeProfile(row: AssertionProfile) {
  await ElMessageBox.confirm(`删除集合“${row.name}”？被 API 引用时无法删除。`, '确认删除', { type: 'warning' })
  try {
    await api.assertionProfiles.remove(row.id)
    ElMessage.success('断言集合已删除')
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
}

watch(projectId, load)
onMounted(async () => {
  try {
    projects.value = await api.projects.list()
    projectId.value = projects.value[0]?.id || ''
  } catch (error) { ElMessage.error((error as Error).message) }
})
</script>

<template>
  <div class="page-head">
    <div><h2>可复用断言</h2><p>将通用判断定义一次，再通过断言集合绑定到项目 API。</p></div>
    <el-button v-if="activeTab === 'definitions'" type="primary" :disabled="!projectId" @click="openDefinitionCreate">新建断言</el-button>
    <el-button v-else type="primary" :disabled="!projectId" @click="openProfileCreate">新建集合</el-button>
  </div>
  <div class="toolbar">
    <el-select v-model="projectId" placeholder="选择项目" style="width: 260px">
      <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
    </el-select>
    <el-radio-group v-model="activeTab">
      <el-radio-button value="definitions">原子断言</el-radio-button>
      <el-radio-button value="profiles">断言集合</el-radio-button>
    </el-radio-group>
  </div>

  <el-card v-if="activeTab === 'definitions'" class="panel" shadow="never">
    <el-table :data="definitions">
      <el-table-column prop="name" label="名称" min-width="180" />
      <el-table-column label="引擎" width="130"><template #default="scope"><el-tag effect="plain">{{ scope.row.engine }}</el-tag></template></el-table-column>
      <el-table-column prop="description" label="用途" min-width="220" show-overflow-tooltip />
      <el-table-column label="级别" width="100"><template #default="scope"><el-tag :type="scope.row.severity === 'warning' ? 'warning' : 'danger'">{{ scope.row.severity }}</el-tag></template></el-table-column>
      <el-table-column label="配置" min-width="300" show-overflow-tooltip><template #default="scope"><code>{{ pretty(scope.row.config) }}</code></template></el-table-column>
      <el-table-column label="操作" width="140" align="right"><template #default="scope"><el-button link type="primary" @click="openDefinitionEdit(scope.row)">编辑</el-button><el-button link type="danger" @click="removeDefinition(scope.row)">删除</el-button></template></el-table-column>
    </el-table>
    <div v-if="projectId && !definitions.length" class="empty-state">当前项目还没有断言定义。</div>
  </el-card>

  <el-card v-else class="panel" shadow="never">
    <el-table :data="profiles">
      <el-table-column prop="name" label="集合名称" min-width="190" />
      <el-table-column label="协议" width="100"><template #default="scope"><el-tag>{{ scope.row.protocol.toUpperCase() }}</el-tag></template></el-table-column>
      <el-table-column label="默认" width="90"><template #default="scope"><el-tag v-if="scope.row.is_default" type="success">默认</el-tag><span v-else class="muted">—</span></template></el-table-column>
      <el-table-column label="断言" min-width="280"><template #default="scope"><el-space wrap><el-tag v-for="binding in scope.row.bindings" :key="String(binding.assertion_id)" effect="plain">{{ definitionName(binding.assertion_id) }}</el-tag><span v-if="!scope.row.bindings.length" class="muted">空集合</span></el-space></template></el-table-column>
      <el-table-column label="引用 API" width="100"><template #default="scope">{{ scope.row.usage_count }}</template></el-table-column>
      <el-table-column label="操作" width="140" align="right"><template #default="scope"><el-button link type="primary" @click="openProfileEdit(scope.row)">编辑</el-button><el-button link type="danger" @click="removeProfile(scope.row)">删除</el-button></template></el-table-column>
    </el-table>
    <div v-if="projectId && !profiles.length" class="empty-state">创建一个默认集合后，新 API 会自动绑定它。</div>
  </el-card>

  <el-dialog v-model="definitionDialog" :title="editingDefinitionId ? '编辑断言定义' : '新建断言定义'" width="720px">
    <el-form label-position="top">
      <div class="two-col">
        <el-form-item label="名称"><el-input v-model="definitionForm.name" placeholder="例如：业务 code 成功" /></el-form-item>
        <el-form-item label="级别"><el-radio-group v-model="definitionForm.severity"><el-radio-button value="error">失败</el-radio-button><el-radio-button value="warning">警告</el-radio-button></el-radio-group></el-form-item>
      </div>
      <el-form-item label="引擎"><el-radio-group :model-value="definitionForm.engine" @update:model-value="switchEngine"><el-radio-button value="path">路径比较</el-radio-button><el-radio-button value="json_schema">JSON Schema</el-radio-button><el-radio-button value="expression">安全表达式</el-radio-button></el-radio-group></el-form-item>
      <el-form-item label="说明"><el-input v-model="definitionForm.description" /></el-form-item>
      <el-form-item label="断言配置"><el-input v-model="definitionForm.config" class="json-input" type="textarea" :rows="10" /></el-form-item>
      <el-form-item label="默认参数"><el-input v-model="definitionForm.default_params" class="json-input" type="textarea" :rows="4" /><div class="muted">表达式通过 <code>params</code> 读取；集合绑定可以覆盖这些参数。</div></el-form-item>
      <el-form-item label="失败消息"><el-input v-model="definitionForm.message" placeholder="留空时使用系统消息" /></el-form-item>
    </el-form>
    <template #footer><el-button @click="definitionDialog = false">取消</el-button><el-button type="primary" :disabled="!definitionForm.name" @click="saveDefinition">保存</el-button></template>
  </el-dialog>

  <el-dialog v-model="profileDialog" :title="editingProfileId ? '编辑断言集合' : '新建断言集合'" width="780px">
    <el-form label-position="top">
      <div class="two-col">
        <el-form-item label="集合名称"><el-input v-model="profileForm.name" /></el-form-item>
        <el-form-item label="协议"><el-radio-group v-model="profileForm.protocol"><el-radio-button value="http">HTTP</el-radio-button><el-radio-button value="ws">WebSocket</el-radio-button></el-radio-group></el-form-item>
      </div>
      <el-form-item label="说明"><el-input v-model="profileForm.description" /></el-form-item>
      <el-form-item label="默认集合"><el-switch v-model="profileForm.is_default" active-text="新建 API 自动绑定" /></el-form-item>
      <el-form-item label="快速添加断言">
        <el-space wrap><el-button v-for="item in definitions" :key="item.id" size="small" @click="addBinding(item)">+ {{ item.name }}</el-button></el-space>
      </el-form-item>
      <el-form-item label="集合绑定"><el-input v-model="profileForm.bindings" class="json-input" type="textarea" :rows="11" /><div class="muted">每项包含 <code>assertion_id</code>、<code>enabled</code> 和可选的 <code>params</code>、<code>severity</code>、<code>message</code>。</div></el-form-item>
    </el-form>
    <template #footer><el-button @click="profileDialog = false">取消</el-button><el-button type="primary" :disabled="!profileForm.name" @click="saveProfile">保存集合</el-button></template>
  </el-dialog>
</template>
