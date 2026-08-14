<script setup lang="ts">
import { Delete, Edit } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, reactive, ref, watch } from 'vue'

import { api } from '../api/client'
import PaginationBar from '../components/PaginationBar.vue'
import { useProjectContext } from '../state/project'
import type { AssertionDefinition } from '../types'
import { parseJson, pretty } from '../utils'

const definitions = ref<AssertionDefinition[]>([])
const { projectId } = useProjectContext()
const definitionPage = ref(1)
const definitionPageSize = ref(20)
const definitionDialog = ref(false)
const editingDefinitionId = ref('')

const definitionForm = reactive({
  key: '',
  name: '',
  engine: 'expression' as 'path' | 'json_schema' | 'expression',
  description: '',
  config: '{\n  "expression": "response.status_code >= 200 and response.status_code < 300"\n}',
  default_params: '{}',
  message: '',
})

const pagedDefinitions = computed(() => definitions.value.slice(
  (definitionPage.value - 1) * definitionPageSize.value,
  definitionPage.value * definitionPageSize.value,
))

async function load() {
  if (!projectId.value) {
    definitions.value = []
    return
  }
  try {
    definitions.value = await api.assertionDefinitions.list(projectId.value)
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
    config: pretty(defaultConfig('expression')), default_params: '{}', message: '',
  })
  definitionDialog.value = true
}

function openDefinitionEdit(row: AssertionDefinition) {
  editingDefinitionId.value = row.id
  Object.assign(definitionForm, {
    key: row.key, name: row.name, engine: row.engine, description: row.description,
    config: pretty(row.config), default_params: pretty(row.default_params), message: row.message,
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
  try {
    await ElMessageBox.confirm(`删除成功条件“${row.name}”？被 API 引用时无法删除。`, '确认删除', { type: 'warning' })
    await api.assertionDefinitions.remove(row.id)
    ElMessage.success('成功条件已删除')
    await load()
  } catch (error) {
    if ((error as Error).message !== 'cancel') ElMessage.error((error as Error).message)
  }
}

watch(projectId, () => {
  definitionPage.value = 1
  void load()
}, { immediate: true })
</script>

<template>
  <Teleport to="#page-header-content">
    <div class="page-header-content-inner">
      <el-tag type="success" effect="plain">成功条件</el-tag>
      <el-button type="primary" :disabled="!projectId" @click="openDefinitionCreate">新建成功条件</el-button>
    </div>
  </Teleport>
  <Teleport to="#page-footer-content">
    <div class="page-footer-content-inner">
      <PaginationBar
        v-model:page="definitionPage"
        v-model:page-size="definitionPageSize"
        :total="definitions.length"
      />
    </div>
  </Teleport>

  <el-card class="panel" shadow="never">
    <div class="section-intro">
      <div>
        <span class="eyebrow">SUCCESS CHECKS</span>
        <h2>成功条件</h2>
        <p>每个 API 直接选择一个成功条件，执行结果由该条件独立判定。</p>
      </div>
      <el-tag effect="plain">{{ definitions.length }} 个条件</el-tag>
    </div>
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

  <el-dialog v-model="definitionDialog" :title="editingDefinitionId ? '编辑成功条件' : '新建成功条件'" width="720px">
    <el-form label-position="top">
      <div class="two-col">
        <el-form-item label="Key" required><el-input v-model="definitionForm.key" placeholder="例如：response.success" /></el-form-item>
        <el-form-item label="名称" required><el-input v-model="definitionForm.name" placeholder="例如：业务 code 成功" /></el-form-item>
      </div>
      <el-form-item label="引擎"><el-radio-group :model-value="definitionForm.engine" @update:model-value="switchEngine"><el-radio-button value="path">路径比较</el-radio-button><el-radio-button value="json_schema">JSON Schema</el-radio-button><el-radio-button value="expression">安全表达式</el-radio-button></el-radio-group></el-form-item>
      <el-form-item label="说明"><el-input v-model="definitionForm.description" /></el-form-item>
      <el-form-item label="条件配置"><el-input v-model="definitionForm.config" class="json-input" type="textarea" :rows="10" /></el-form-item>
      <el-form-item label="默认参数"><el-input v-model="definitionForm.default_params" class="json-input" type="textarea" :rows="4" /><div class="muted">表达式通过 <code>params</code> 读取。</div></el-form-item>
      <el-form-item label="未满足时提示"><el-input v-model="definitionForm.message" placeholder="留空时使用系统消息" /></el-form-item>
    </el-form>
    <template #footer><el-button @click="definitionDialog = false">取消</el-button><el-button type="primary" :disabled="!definitionForm.key || !definitionForm.name" @click="saveDefinition">保存成功条件</el-button></template>
  </el-dialog>
</template>
