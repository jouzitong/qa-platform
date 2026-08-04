<script setup lang="ts">
import { Delete, Edit } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, reactive, ref, watch } from 'vue'

import { api } from '../api/client'
import PaginationBar from '../components/PaginationBar.vue'
import { useProjectContext } from '../state/project'
import type { AssertionDefinition, AssertionProfile } from '../types'
import { parseJson, pretty } from '../utils'

const definitions = ref<AssertionDefinition[]>([])
const profiles = ref<AssertionProfile[]>([])
const { projectId } = useProjectContext()
const activeTab = ref<'definitions' | 'profiles'>('definitions')
const definitionPage = ref(1)
const definitionPageSize = ref(20)
const profilePage = ref(1)
const profilePageSize = ref(20)
const definitionDialog = ref(false)
const profileDialog = ref(false)
const editingDefinitionId = ref('')
const editingProfileId = ref('')

const definitionForm = reactive({
  key: '',
  name: '',
  engine: 'expression' as 'path' | 'json_schema' | 'expression',
  description: '',
  config: '{\n  "expression": "response.status_code >= 200 and response.status_code < 300"\n}',
  default_params: '{}',
  severity: 'success' as 'success' | 'error' | 'warning',
  message: '',
})
const profileForm = reactive({
  name: '',
  protocol: 'http' as 'http' | 'ws',
  description: '',
  is_default: false,
  bindings: '[]',
})
const pagedDefinitions = computed(() => definitions.value.slice(
  (definitionPage.value - 1) * definitionPageSize.value,
  definitionPage.value * definitionPageSize.value,
))
const pagedProfiles = computed(() => profiles.value.slice(
  (profilePage.value - 1) * profilePageSize.value,
  profilePage.value * profilePageSize.value,
))

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
  return { expression: 'response.status_code >= 200 and response.status_code < 300' }
}

function openDefinitionCreate() {
  editingDefinitionId.value = ''
  Object.assign(definitionForm, {
    key: '', name: '', engine: 'expression', description: '',
    config: pretty(defaultConfig('expression')), default_params: '{}',
    severity: 'success', message: '',
  })
  definitionDialog.value = true
}

function openDefinitionEdit(row: AssertionDefinition) {
  editingDefinitionId.value = row.id
  Object.assign(definitionForm, {
    key: row.key, name: row.name, engine: row.engine, description: row.description,
    config: pretty(row.config), default_params: pretty(row.default_params),
    severity: 'success', message: row.message,
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
      key: definitionForm.key,
      name: definitionForm.name,
      engine: definitionForm.engine,
      description: definitionForm.description,
      config: parseJson<Record<string, unknown>>(definitionForm.config, '条件配置'),
      default_params: parseJson<Record<string, unknown>>(
        definitionForm.default_params, '默认参数',
      ),
      severity: 'success' as const,
      message: definitionForm.message,
    }
    if (editingDefinitionId.value)
      await api.assertionDefinitions.update(editingDefinitionId.value, payload)
    else await api.assertionDefinitions.create(payload)
    definitionDialog.value = false
    ElMessage.success('成功条件已保存')
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
}

async function removeDefinition(row: AssertionDefinition) {
  await ElMessageBox.confirm(`删除成功条件“${row.name}”？被集合引用时无法删除。`, '确认删除', { type: 'warning' })
  try {
    await api.assertionDefinitions.remove(row.id)
    ElMessage.success('成功条件已删除')
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
    ElMessage.success('成功条件集合已保存')
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
}

async function removeProfile(row: AssertionProfile) {
  await ElMessageBox.confirm(`删除成功条件集合“${row.name}”？被 API 引用时无法删除。`, '确认删除', { type: 'warning' })
  try {
    await api.assertionProfiles.remove(row.id)
    ElMessage.success('成功条件集合已删除')
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
}

watch(projectId, () => {
  definitionPage.value = 1
  profilePage.value = 1
  void load()
}, { immediate: true })
watch(activeTab, (tab) => {
  if (tab === 'definitions') definitionPage.value = 1
  else profilePage.value = 1
})
</script>

<template>
  <Teleport to="#page-header-content">
    <div class="page-header-content-inner">
      <el-radio-group v-model="activeTab">
        <el-radio-button value="definitions">原子成功条件</el-radio-button>
        <el-radio-button value="profiles">成功条件集合</el-radio-button>
      </el-radio-group>
      <el-button v-if="activeTab === 'definitions'" type="primary" :disabled="!projectId" @click="openDefinitionCreate">新建成功条件</el-button>
      <el-button v-else type="primary" :disabled="!projectId" @click="openProfileCreate">新建成功集合</el-button>
    </div>
  </Teleport>
  <Teleport to="#page-footer-content">
    <div class="page-footer-content-inner">
      <PaginationBar
        v-if="activeTab === 'definitions'"
        v-model:page="definitionPage"
        v-model:page-size="definitionPageSize"
        :total="definitions.length"
      />
      <PaginationBar
        v-else
        v-model:page="profilePage"
        v-model:page-size="profilePageSize"
        :total="profiles.length"
      />
    </div>
  </Teleport>

  <el-card v-if="activeTab === 'definitions'" class="panel" shadow="never">
    <el-table class="list-table" :data="pagedDefinitions">
      <el-table-column prop="name" label="名称" fixed="left" min-width="180" align="center" show-overflow-tooltip />
      <el-table-column prop="key" label="Key" min-width="180" align="center" show-overflow-tooltip />
      <el-table-column label="引擎" width="130" align="center"><template #default="scope"><el-tag effect="plain">{{ scope.row.engine }}</el-tag></template></el-table-column>
      <el-table-column prop="description" label="用途" min-width="220" align="left" show-overflow-tooltip />
      <el-table-column label="配置" min-width="300" align="left" show-overflow-tooltip><template #default="scope"><code>{{ pretty(scope.row.config) }}</code></template></el-table-column>
      <el-table-column label="操作" fixed="right" width="140" align="center"><template #default="scope"><div class="icon-action-group"><el-button class="icon-action-button" link type="primary" :icon="Edit" aria-label="编辑" @click="openDefinitionEdit(scope.row)"><span class="icon-action-label">编辑</span></el-button><el-button class="icon-action-button" link type="danger" :icon="Delete" aria-label="删除" @click="removeDefinition(scope.row)"><span class="icon-action-label">删除</span></el-button></div></template></el-table-column>
    </el-table>
    <div v-if="projectId && !definitions.length" class="empty-state">当前项目还没有成功条件。</div>
  </el-card>

  <el-card v-else class="panel" shadow="never">
    <el-table class="list-table" :data="pagedProfiles">
      <el-table-column prop="name" label="集合名称" fixed="left" min-width="190" align="center" show-overflow-tooltip />
      <el-table-column label="协议" width="100" align="center"><template #default="scope"><el-tag>{{ scope.row.protocol.toUpperCase() }}</el-tag></template></el-table-column>
      <el-table-column label="成功条件" min-width="280" align="left"><template #default="scope"><el-space wrap><el-tag v-for="binding in scope.row.bindings" :key="String(binding.assertion_id)" effect="plain">{{ definitionName(binding.assertion_id) }}</el-tag><span v-if="!scope.row.bindings.length" class="muted">空集合</span></el-space></template></el-table-column>
      <el-table-column label="默认" width="90" align="center"><template #default="scope"><el-tag v-if="scope.row.is_default" type="success">默认</el-tag><span v-else class="muted">—</span></template></el-table-column>
      <el-table-column label="引用 API" width="100" align="center"><template #default="scope">{{ scope.row.usage_count }}</template></el-table-column>
      <el-table-column label="操作" fixed="right" width="140" align="center"><template #default="scope"><div class="icon-action-group"><el-button class="icon-action-button" link type="primary" :icon="Edit" aria-label="编辑" @click="openProfileEdit(scope.row)"><span class="icon-action-label">编辑</span></el-button><el-button class="icon-action-button" link type="danger" :icon="Delete" aria-label="删除" @click="removeProfile(scope.row)"><span class="icon-action-label">删除</span></el-button></div></template></el-table-column>
    </el-table>
    <div v-if="projectId && !profiles.length" class="empty-state">创建一个默认成功集合后，新 API 会自动绑定它。</div>
  </el-card>

  <el-dialog v-model="definitionDialog" :title="editingDefinitionId ? '编辑成功条件' : '新建成功条件'" width="720px">
    <el-form label-position="top">
      <div class="two-col">
        <el-form-item label="Key" required><el-input v-model="definitionForm.key" placeholder="例如：response.success" /></el-form-item>
        <el-form-item label="名称" required><el-input v-model="definitionForm.name" placeholder="例如：业务 code 成功" /></el-form-item>
      </div>
      <el-form-item label="引擎"><el-radio-group :model-value="definitionForm.engine" @update:model-value="switchEngine"><el-radio-button value="path">路径比较</el-radio-button><el-radio-button value="json_schema">JSON Schema</el-radio-button><el-radio-button value="expression">安全表达式</el-radio-button></el-radio-group></el-form-item>
      <el-form-item label="说明"><el-input v-model="definitionForm.description" /></el-form-item>
      <el-form-item label="条件配置"><el-input v-model="definitionForm.config" class="json-input" type="textarea" :rows="10" /></el-form-item>
      <el-form-item label="默认参数"><el-input v-model="definitionForm.default_params" class="json-input" type="textarea" :rows="4" /><div class="muted">表达式通过 <code>params</code> 读取；集合绑定可以覆盖这些参数。</div></el-form-item>
      <el-form-item label="未满足时提示"><el-input v-model="definitionForm.message" placeholder="留空时使用系统消息" /></el-form-item>
    </el-form>
    <template #footer><el-button @click="definitionDialog = false">取消</el-button><el-button type="primary" :disabled="!definitionForm.key || !definitionForm.name" @click="saveDefinition">保存</el-button></template>
  </el-dialog>

  <el-dialog v-model="profileDialog" :title="editingProfileId ? '编辑成功条件集合' : '新建成功条件集合'" width="780px">
    <el-form label-position="top">
      <div class="two-col">
        <el-form-item label="集合名称"><el-input v-model="profileForm.name" /></el-form-item>
        <el-form-item label="协议"><el-radio-group v-model="profileForm.protocol"><el-radio-button value="http">HTTP</el-radio-button><el-radio-button value="ws">WebSocket</el-radio-button></el-radio-group></el-form-item>
      </div>
      <el-form-item label="说明"><el-input v-model="profileForm.description" /></el-form-item>
      <el-form-item label="默认集合"><el-switch v-model="profileForm.is_default" active-text="新建 API 自动绑定" /></el-form-item>
      <el-form-item label="快速添加成功条件">
        <el-space wrap><el-button v-for="item in definitions" :key="item.id" size="small" @click="addBinding(item)">+ {{ item.name }}</el-button></el-space>
      </el-form-item>
      <el-form-item label="集合绑定"><el-input v-model="profileForm.bindings" class="json-input" type="textarea" :rows="11" /><div class="muted">每项包含 <code>assertion_id</code>、<code>enabled</code> 和可选的 <code>params</code>、<code>message</code>。</div></el-form-item>
    </el-form>
    <template #footer><el-button @click="profileDialog = false">取消</el-button><el-button type="primary" :disabled="!profileForm.name" @click="saveProfile">保存集合</el-button></template>
  </el-dialog>
</template>
