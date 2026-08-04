<script setup lang="ts">
import { Delete, Edit, View } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { api } from '../api/client'
import type {
  ApiDefinition,
  Project,
  TestFlow,
  TestPlan,
  TestPlanItem,
  TestPlanItemType,
  TestPlanRun,
} from '../types'
import { parseJson, pretty } from '../utils'

interface PlanResult {
  item_id: string
  type: TestPlanItemType
  target_id: string
  target_key?: string | null
  target_name?: string | null
  status: string
  duration_ms: number
  error?: string | null
  details: Record<string, unknown>
}

const projects = ref<Project[]>([])
const plans = ref<TestPlan[]>([])
const definitions = ref<ApiDefinition[]>([])
const flows = ref<TestFlow[]>([])
const projectId = ref('')
const selectedPlan = ref<TestPlan | null>(null)
const planRuns = ref<TestPlanRun[]>([])
const selectedRun = ref<TestPlanRun | null>(null)
const planDialog = ref(false)
const runDetailVisible = ref(false)
const editingId = ref('')
const running = ref(false)
const runInputs = ref('{}')
const form = reactive({
  key: '', version: 'v1.0.0', name: '', description: '', items: [] as TestPlanItem[],
})

const selectedResults = computed(() => (selectedRun.value?.results || []) as unknown as PlanResult[])

function statusType(status: string) {
  if (status === 'passed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

function statusLabel(status: string) {
  return { passed: '通过', failed: '不通过', running: '执行中', pending: '等待中' }[status] || status
}

function formatTime(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString() : '—'
}

function resourcesFor(type: TestPlanItemType) {
  return type === 'api' ? definitions.value : flows.value
}

function resourceLabel(type: TestPlanItemType, targetId: string) {
  const resource = resourcesFor(type).find((item) => item.id === targetId)
  return resource ? `${resource.key} · ${resource.name}` : '资源不存在'
}

function newItem(type: TestPlanItemType = 'flow'): TestPlanItem {
  return {
    id: `plan-item-${crypto.randomUUID().slice(0, 8)}`,
    type,
    target_id: resourcesFor(type)[0]?.id || '',
    enabled: true,
  }
}

async function loadRuns(plan: TestPlan | null = selectedPlan.value) {
  if (!plan) { planRuns.value = []; return }
  try {
    planRuns.value = await api.testPlans.runs(plan.id)
  } catch (error) { ElMessage.error((error as Error).message) }
}

async function load() {
  if (!projectId.value) {
    plans.value = []; definitions.value = []; flows.value = []; selectedPlan.value = null
    return
  }
  try {
    ;[plans.value, definitions.value, flows.value] = await Promise.all([
      api.testPlans.list(projectId.value),
      api.definitions.list(projectId.value),
      api.flows.list(projectId.value),
    ])
    const current = plans.value.find((plan) => plan.id === selectedPlan.value?.id)
    selectedPlan.value = current || plans.value[0] || null
    await loadRuns()
  } catch (error) { ElMessage.error((error as Error).message) }
}

function selectPlan(plan: TestPlan) {
  selectedPlan.value = plan
  selectedRun.value = null
  void loadRuns(plan)
}

function openCreate() {
  editingId.value = ''
  Object.assign(form, { key: '', version: 'v1.0.0', name: '', description: '', items: [] })
  planDialog.value = true
}

function openEdit(plan: TestPlan) {
  editingId.value = plan.id
  Object.assign(form, {
    key: plan.key,
    version: plan.version,
    name: plan.name,
    description: plan.description,
    items: plan.items.map((item) => ({ ...item })),
  })
  planDialog.value = true
}

function addItem(type: TestPlanItemType) {
  form.items.push(newItem(type))
}

function resetTarget(item: TestPlanItem) {
  item.target_id = resourcesFor(item.type)[0]?.id || ''
}

async function save() {
  try {
    if (!form.key || !form.version || !form.name) throw new Error('测试计划需要 Key、版本和名称')
    if (form.items.some((item) => !item.target_id)) throw new Error('每个计划项都需要选择 API 或测试流程')
    const payload = {
      project_id: projectId.value,
      key: form.key,
      version: form.version,
      name: form.name,
      description: form.description,
      items: form.items,
    }
    const saved = editingId.value
      ? await api.testPlans.update(editingId.value, payload)
      : await api.testPlans.create(payload)
    planDialog.value = false
    selectedPlan.value = saved
    ElMessage.success('测试计划已保存')
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
}

async function remove(plan: TestPlan) {
  await ElMessageBox.confirm(`删除测试计划“${plan.name}”？执行记录也会被删除。`, '确认删除', { type: 'warning' })
  try {
    await api.testPlans.remove(plan.id)
    if (selectedPlan.value?.id === plan.id) selectedPlan.value = null
    await load()
    ElMessage.success('测试计划已删除')
  } catch (error) { ElMessage.error((error as Error).message) }
}

async function executePlan() {
  if (!selectedPlan.value) return
  try {
    running.value = true
    const run = await api.testPlans.run(
      selectedPlan.value.id,
      parseJson<object>(runInputs.value, '计划运行输入'),
    )
    selectedRun.value = run
    await watchRun(run.id)
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { running.value = false }
}

async function watchRun(runId: string) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const latest = await api.testPlans.getRun(runId)
    selectedRun.value = latest
    await loadRuns()
    if (['passed', 'failed', 'cancelled'].includes(latest.status)) return
    await new Promise((resolve) => window.setTimeout(resolve, 500))
  }
}

async function openRunDetail(run: TestPlanRun) {
  selectedRun.value = await api.testPlans.getRun(run.id)
  runDetailVisible.value = true
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
    <div><h2>测试计划</h2><p>按版本组合重点 API 与测试流程，集中执行并追踪结果。</p></div>
    <el-button type="primary" :disabled="!projectId" @click="openCreate">新建测试计划</el-button>
  </div>

  <div class="toolbar">
    <el-select v-model="projectId" placeholder="选择项目" style="width: 260px">
      <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
    </el-select>
  </div>

  <div class="plan-layout">
    <el-card class="panel plan-list" shadow="never">
      <template #header><div class="section-heading"><strong>计划列表</strong><span class="muted">{{ plans.length }} 个版本计划</span></div></template>
      <el-table :data="plans" highlight-current-row @row-click="selectPlan">
        <el-table-column prop="version" label="版本" width="100" />
        <el-table-column label="计划" min-width="170"><template #default="scope"><strong>{{ scope.row.name }}</strong><p class="muted plan-key">{{ scope.row.key }}</p></template></el-table-column>
        <el-table-column label="范围" width="80"><template #default="scope">{{ scope.row.items.length }}</template></el-table-column>
        <el-table-column label="操作" width="120" align="right"><template #default="scope"><el-button class="icon-action-button" link type="primary" :icon="Edit" aria-label="编辑" @click.stop="openEdit(scope.row)"><span class="icon-action-label">编辑</span></el-button><el-button class="icon-action-button" link type="danger" :icon="Delete" aria-label="删除" @click.stop="remove(scope.row)"><span class="icon-action-label">删除</span></el-button></template></el-table-column>
      </el-table>
      <div v-if="projectId && !plans.length" class="empty-state">还没有测试计划，请按版本创建第一份计划。</div>
    </el-card>

    <div v-if="selectedPlan" class="plan-detail">
      <el-card class="panel" shadow="never">
        <div class="page-head plan-detail-head">
          <div><p class="eyebrow">{{ selectedPlan.version }} · {{ selectedPlan.key }}</p><h2>{{ selectedPlan.name }}</h2><p>{{ selectedPlan.description || '暂无计划说明' }}</p></div>
          <div class="plan-actions"><el-button @click="openEdit(selectedPlan)">编辑计划</el-button><el-button type="primary" :loading="running" :disabled="!selectedPlan.items.some((item) => item.enabled)" @click="executePlan">执行计划</el-button></div>
        </div>
        <div class="plan-summary">
          <div class="stat-card"><span class="stat-label">计划项</span><strong class="stat-value">{{ selectedPlan.items.length }}</strong></div>
          <div class="stat-card"><span class="stat-label">启用项</span><strong class="stat-value">{{ selectedPlan.items.filter((item) => item.enabled).length }}</strong></div>
          <div class="stat-card"><span class="stat-label">最近执行</span><strong class="stat-value">{{ planRuns.length ? statusLabel(planRuns[0].status) : '—' }}</strong></div>
        </div>
      </el-card>

      <el-card class="panel" shadow="never">
        <template #header><div class="section-heading"><strong>测试范围</strong><span class="muted">API 与测试流程</span></div></template>
        <div v-if="!selectedPlan.items.length" class="empty-state">这个计划还没有配置测试项。</div>
        <div v-for="(item, index) in selectedPlan.items" :key="item.id" class="plan-item-row">
          <span class="step-number">{{ index + 1 }}</span>
          <el-tag :type="item.type === 'flow' ? 'success' : 'warning'" effect="plain">{{ item.type === 'flow' ? '流程' : 'API' }}</el-tag>
          <div class="plan-item-name"><strong>{{ resourceLabel(item.type, item.target_id) }}</strong><small>{{ item.enabled ? '执行时启用' : '执行时跳过' }}</small></div>
          <el-tag v-if="!item.enabled" type="info">已禁用</el-tag>
        </div>
      </el-card>

      <el-card class="panel" shadow="never">
        <template #header><div class="section-heading"><strong>执行记录</strong><span class="muted">绿色通过，红色不通过</span></div></template>
        <el-table :data="planRuns">
          <el-table-column label="状态" width="100"><template #default="scope"><el-tag :type="statusType(scope.row.status)">{{ statusLabel(scope.row.status) }}</el-tag></template></el-table-column>
          <el-table-column label="结果" width="130"><template #default="scope"><span class="status-passed">{{ scope.row.passed_count }} 通过</span><span v-if="scope.row.failed_count" class="status-failed"> / {{ scope.row.failed_count }} 不通过</span></template></el-table-column>
          <el-table-column prop="created_at" label="执行时间" min-width="170"><template #default="scope">{{ formatTime(scope.row.created_at) }}</template></el-table-column>
          <el-table-column label="操作" width="90" align="right"><template #default="scope"><el-button class="icon-action-button" link type="primary" :icon="View" aria-label="详情" @click="openRunDetail(scope.row)"><span class="icon-action-label">详情</span></el-button></template></el-table-column>
        </el-table>
        <div v-if="!planRuns.length" class="empty-state">还没有执行记录。</div>
      </el-card>
    </div>
    <el-card v-else class="panel empty-plan-detail" shadow="never"><el-empty description="选择左侧测试计划查看范围和执行结果" /></el-card>
  </div>

  <el-dialog v-model="planDialog" :title="editingId ? '编辑测试计划' : '新建测试计划'" width="900px">
    <el-form label-position="top">
      <div class="two-col">
        <el-form-item label="计划 Key" required><el-input v-model="form.key" placeholder="例如：release.order.v1" /></el-form-item>
        <el-form-item label="版本" required><el-input v-model="form.version" placeholder="例如：v1.0.0" /></el-form-item>
      </div>
      <el-form-item label="计划名称" required><el-input v-model="form.name" placeholder="例如：订单服务发布回归" /></el-form-item>
      <el-form-item label="计划说明"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
      <div class="section-heading"><div><strong>测试范围</strong><p class="muted">选择本版本需要关注的 API 和测试流程，执行时按当前顺序运行。</p></div><el-space><el-button size="small" @click="addItem('api')">添加 API</el-button><el-button size="small" @click="addItem('flow')">添加流程</el-button></el-space></div>
      <div v-for="(item, index) in form.items" :key="item.id" class="plan-item-editor">
        <span class="step-number">{{ index + 1 }}</span>
        <el-select v-model="item.type" style="width: 120px" @change="resetTarget(item)"><el-option label="API" value="api" /><el-option label="测试流程" value="flow" /></el-select>
        <el-select v-model="item.target_id" filterable placeholder="选择测试资源" style="flex: 1"><el-option v-for="resource in resourcesFor(item.type)" :key="resource.id" :label="`${resource.key} · ${resource.name}`" :value="resource.id" /></el-select>
        <el-switch v-model="item.enabled" inline-prompt active-text="启" inactive-text="停" />
        <el-button text type="danger" @click="form.items.splice(index, 1)">删除</el-button>
      </div>
      <div v-if="!form.items.length" class="editor-empty"><strong>还没有测试范围</strong><span>点击上方按钮添加 API 或测试流程。</span></div>
    </el-form>
    <template #footer><el-button @click="planDialog = false">取消</el-button><el-button type="primary" :disabled="!form.key || !form.version || !form.name" @click="save">保存计划</el-button></template>
  </el-dialog>

  <el-drawer v-model="runDetailVisible" title="测试计划执行详情" size="720px">
    <template v-if="selectedRun">
      <div class="plan-run-summary"><el-tag :type="statusType(selectedRun.status)" size="large">{{ statusLabel(selectedRun.status) }}</el-tag><span>{{ selectedRun.passed_count }} 通过</span><span>{{ selectedRun.failed_count }} 不通过</span><span>{{ formatTime(selectedRun.created_at) }}</span></div>
      <p v-if="selectedRun.error" class="field-error">{{ selectedRun.error }}</p>
      <div v-for="result in selectedResults" :key="result.item_id" class="plan-result-card">
        <div class="section-heading"><div><el-tag :type="result.type === 'flow' ? 'success' : 'warning'" effect="plain">{{ result.type === 'flow' ? '流程' : 'API' }}</el-tag><strong>{{ result.target_key || result.target_name || result.target_id }}</strong></div><el-tag :type="statusType(result.status)">{{ statusLabel(result.status) }}</el-tag></div>
        <p class="muted">{{ result.target_name || result.target_id }} · {{ Math.round(result.duration_ms) }} ms</p>
        <p v-if="result.error" class="field-error">{{ result.error }}</p>
        <pre class="code-block">{{ pretty(result.details) }}</pre>
      </div>
      <div v-if="!selectedResults.length" class="empty-state">暂无执行详情。</div>
    </template>
  </el-drawer>
</template>
