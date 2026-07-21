<script setup lang="ts">
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref, watch } from 'vue'

import { api } from '../api/client'
import type { ApiDefinition, FlowStep, Project, TestFlow } from '../types'
import { parseJson, pretty } from '../utils'

interface EditableStep {
  id: string
  name: string
  api_id: string
  enabled: boolean
  request: string
  assertions: string
  extractors: string
  max_attempts: number
  interval_ms: number
  backoff_multiplier: number
}

const projects = ref<Project[]>([])
const definitions = ref<ApiDefinition[]>([])
const flows = ref<TestFlow[]>([])
const projectId = ref('')
const dialog = ref(false)
const editingId = ref('')
const form = reactive({ name: '', description: '', variables: '{}', steps: [] as EditableStep[] })

async function load() {
  if (!projectId.value) { definitions.value = []; flows.value = []; return }
  try {
    ;[definitions.value, flows.value] = await Promise.all([
      api.definitions.list(projectId.value), api.flows.list(projectId.value),
    ])
  } catch (error) { ElMessage.error((error as Error).message) }
}

function newStep(): EditableStep {
  return {
    id: `step-${crypto.randomUUID().slice(0, 8)}`, name: '', api_id: '', enabled: true,
    request: '{}', assertions: '[\n  { "source": "status_code", "operator": "equals", "expected": 200 }\n]',
    extractors: '[]', max_attempts: 1, interval_ms: 0, backoff_multiplier: 1,
  }
}

function openCreate() {
  editingId.value = ''
  Object.assign(form, { name: '', description: '', variables: '{}', steps: [] })
  dialog.value = true
}

function openEdit(row: TestFlow) {
  editingId.value = row.id
  form.name = row.name
  form.description = row.description
  form.variables = pretty(row.variables)
  form.steps = row.steps.map((step) => ({
    id: step.id, name: step.name, api_id: step.api_id, enabled: step.enabled,
    request: pretty(step.request), assertions: pretty(step.assertions), extractors: pretty(step.extractors),
    max_attempts: step.retry.max_attempts, interval_ms: step.retry.interval_ms,
    backoff_multiplier: step.retry.backoff_multiplier,
  }))
  dialog.value = true
}

function move(index: number, direction: -1 | 1) {
  const next = index + direction
  if (next < 0 || next >= form.steps.length) return
  const [step] = form.steps.splice(index, 1)
  form.steps.splice(next, 0, step)
}

function serializeStep(step: EditableStep): FlowStep {
  return {
    id: step.id, name: step.name, api_id: step.api_id, enabled: step.enabled,
    request: parseJson<Record<string, unknown>>(step.request, `${step.name} 请求覆盖`),
    assertions: parseJson<Record<string, unknown>[]>(step.assertions, `${step.name} 断言`),
    extractors: parseJson<Record<string, unknown>[]>(step.extractors, `${step.name} 提取器`),
    retry: { max_attempts: step.max_attempts, interval_ms: step.interval_ms, backoff_multiplier: step.backoff_multiplier },
  }
}

async function save() {
  try {
    if (form.steps.some((step) => !step.name || !step.api_id)) throw new Error('每个步骤都需要名称和 API')
    const payload = {
      project_id: projectId.value, name: form.name, description: form.description,
      variables: parseJson<Record<string, unknown>>(form.variables, '流程变量'), steps: form.steps.map(serializeStep),
    }
    if (editingId.value) await api.flows.update(editingId.value, payload)
    else await api.flows.create(payload)
    dialog.value = false
    ElMessage.success('测试流程已保存')
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
}

async function remove(row: TestFlow) {
  await ElMessageBox.confirm(`删除流程“${row.name}”及其运行历史？`, '确认删除', { type: 'warning' })
  await api.flows.remove(row.id)
  await load()
  ElMessage.success('流程已删除')
}

watch(projectId, load)
onMounted(async () => {
  try { projects.value = await api.projects.list(); projectId.value = projects.value[0]?.id || '' }
  catch (error) { ElMessage.error((error as Error).message) }
})
</script>

<template>
  <div class="page-head">
    <div><h2>测试流程</h2><p>按顺序组合 API，管理上下文、断言、结果提取与失败重试。</p></div>
    <el-button type="primary" :disabled="!projectId || !definitions.length" @click="openCreate">新建流程</el-button>
  </div>
  <div class="toolbar">
    <el-select v-model="projectId" placeholder="选择项目" style="width: 260px"><el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" /></el-select>
    <span v-if="projectId && !definitions.length" class="muted">请先为项目登记 API。</span>
  </div>
  <el-card class="panel" shadow="never">
    <el-table :data="flows">
      <el-table-column prop="name" label="流程" min-width="190" />
      <el-table-column prop="description" label="说明" min-width="250" show-overflow-tooltip />
      <el-table-column label="步骤" width="100"><template #default="scope"><el-tag effect="plain">{{ scope.row.steps.length }} steps</el-tag></template></el-table-column>
      <el-table-column label="变量" width="100"><template #default="scope">{{ Object.keys(scope.row.variables).length }}</template></el-table-column>
      <el-table-column label="操作" width="140" align="right"><template #default="scope"><el-button link type="primary" @click="openEdit(scope.row)">编辑</el-button><el-button link type="danger" @click="remove(scope.row)">删除</el-button></template></el-table-column>
    </el-table>
    <div v-if="projectId && !flows.length" class="empty-state">还没有测试流程。</div>
  </el-card>

  <el-dialog v-model="dialog" :title="editingId ? '编辑测试流程' : '新建测试流程'" width="940px" top="4vh">
    <el-form label-position="top">
      <div class="two-col">
        <el-form-item label="流程名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="form.description" /></el-form-item>
      </div>
      <el-form-item label="流程变量（JSON）"><el-input v-model="form.variables" class="json-input" type="textarea" :rows="4" /></el-form-item>
      <div class="page-head" style="margin: 16px 0 10px"><div><strong>流程步骤</strong><p>提取值将写入上下文，供后续步骤通过模板引用。</p></div><el-button @click="form.steps.push(newStep())">添加步骤</el-button></div>
      <div v-for="(step, index) in form.steps" :key="step.id" class="step-card">
        <div class="step-head">
          <span class="step-number">{{ index + 1 }}</span>
          <el-input v-model="step.name" placeholder="步骤名称" style="width: 220px" />
          <el-select v-model="step.api_id" placeholder="选择 API" style="flex: 1"><el-option v-for="definition in definitions" :key="definition.id" :label="`${definition.protocol.toUpperCase()} · ${definition.name}`" :value="definition.id" /></el-select>
          <el-switch v-model="step.enabled" inline-prompt active-text="启" inactive-text="停" />
          <el-button text :disabled="index === 0" @click="move(index, -1)">上移</el-button>
          <el-button text :disabled="index === form.steps.length - 1" @click="move(index, 1)">下移</el-button>
          <el-button text type="danger" @click="form.steps.splice(index, 1)">删除</el-button>
        </div>
        <el-tabs type="border-card">
          <el-tab-pane label="请求覆盖"><el-input v-model="step.request" class="json-input" type="textarea" :rows="6" /></el-tab-pane>
          <el-tab-pane label="断言"><el-input v-model="step.assertions" class="json-input" type="textarea" :rows="6" /></el-tab-pane>
          <el-tab-pane label="提取器"><el-input v-model="step.extractors" class="json-input" type="textarea" :rows="6" /><p class="muted">示例：[{ "name": "token", "source": "body.data.token" }]</p></el-tab-pane>
          <el-tab-pane label="失败重试"><div class="retry-fields"><el-form-item label="最多尝试"><el-input-number v-model="step.max_attempts" :min="1" :max="10" /></el-form-item><el-form-item label="间隔（ms）"><el-input-number v-model="step.interval_ms" :min="0" /></el-form-item><el-form-item label="退避倍数"><el-input-number v-model="step.backoff_multiplier" :min="1" :step="0.5" /></el-form-item></div></el-tab-pane>
        </el-tabs>
      </div>
      <div v-if="!form.steps.length" class="empty-state">点击“添加步骤”开始编排。</div>
    </el-form>
    <template #footer><el-button @click="dialog = false">取消</el-button><el-button type="primary" :disabled="!form.name" @click="save">保存流程</el-button></template>
  </el-dialog>
</template>
