<script setup lang="ts">
import { View } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, reactive, ref, watch } from 'vue'

import { api, websocketUrl } from '../api/client'
import PaginationBar from '../components/PaginationBar.vue'
import { useProjectContext } from '../state/project'
import type { TestFlow, TestPlan, TestRun } from '../types'
import { parseJson, pretty, shortId } from '../utils'

const flows = ref<TestFlow[]>([])
const plans = ref<TestPlan[]>([])
const runs = ref<TestRun[]>([])
const selectedPlanId = ref('')
const launchDialog = ref(false)
const detailDialog = ref(false)
const selected = ref<TestRun | null>(null)
const liveEvents = ref<object[]>([])
const page = ref(1)
const pageSize = ref(20)
const launch = reactive({ flow_id: '', inputs: '{}' })
const { projectId } = useProjectContext()
const flowNames = computed(() => Object.fromEntries(flows.value.map((flow) => [flow.id, flow.name])))
const filteredRuns = computed(() => {
  if (!selectedPlanId.value) return runs.value

  const plan = plans.value.find((item) => item.id === selectedPlanId.value)
  if (!plan) return []

  const flowIds = new Set(
    plan.items
      .filter((item) => item.type === 'flow')
      .map((item) => item.target_id),
  )
  return runs.value.filter((run) => flowIds.has(run.flow_id))
})
const pagedRuns = computed(() => filteredRuns.value.slice(
  (page.value - 1) * pageSize.value,
  page.value * pageSize.value,
))

function totalDuration(run: TestRun): string {
  return run.step_runs.reduce((sum, step) => sum + step.duration_ms, 0).toFixed(0)
}

async function load() {
  if (!projectId.value) {
    flows.value = []
    plans.value = []
    runs.value = []
    selectedPlanId.value = ''
    return
  }
  try {
    const [nextFlows, nextPlans, nextRuns] = await Promise.all([
      api.flows.list(projectId.value),
      api.testPlans.list(projectId.value),
      api.runs.list(),
    ])
    flows.value = nextFlows
    plans.value = nextPlans
    runs.value = nextRuns
    if (selectedPlanId.value && !nextPlans.some((plan) => plan.id === selectedPlanId.value)) {
      selectedPlanId.value = ''
    }
  }
  catch (error) { ElMessage.error((error as Error).message) }
}

async function start() {
  try {
    const run = await api.runs.create(launch.flow_id, parseJson<object>(launch.inputs, '运行输入'))
    launchDialog.value = false
    ElMessage.success('流程已开始执行')
    watchRun(run.id)
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
}

function watchRun(runId: string) {
  const socket = new WebSocket(websocketUrl(`/ws/runs/${runId}`))
  socket.onmessage = async (message) => {
    const event = JSON.parse(message.data)
    liveEvents.value.unshift(event)
    if (event.type === 'step_finished' || event.type === 'run_finished') await load()
  }
}

function openLaunch(flow?: TestFlow) {
  launch.flow_id = flow?.id || flows.value[0]?.id || ''
  launch.inputs = '{}'
  liveEvents.value = []
  launchDialog.value = true
}

function openDetail(run: TestRun) {
  selected.value = run
  detailDialog.value = true
}

watch(projectId, () => {
  page.value = 1
  selectedPlanId.value = ''
  void load()
}, { immediate: true })
</script>

<template>
  <Teleport to="#page-header-content">
    <div class="page-header-content-inner">
      <el-select
        v-model="selectedPlanId"
        clearable
        filterable
        placeholder="按测试计划筛选"
        style="width: 220px"
        @change="page = 1"
      >
        <el-option
          v-for="plan in plans"
          :key="plan.id"
          :label="`${plan.version} · ${plan.name}`"
          :value="plan.id"
        />
      </el-select>
      <el-button @click="load">刷新</el-button>
      <el-button type="primary" :disabled="!flows.length" @click="openLaunch()">运行流程</el-button>
    </div>
  </Teleport>
  <Teleport to="#page-footer-content">
    <div class="page-footer-content-inner">
      <PaginationBar v-model:page="page" v-model:page-size="pageSize" :total="filteredRuns.length" />
    </div>
  </Teleport>
  <el-card class="panel" shadow="never">
    <el-table class="list-table" :data="pagedRuns" @row-click="openDetail">
      <el-table-column label="流程" fixed="left" min-width="180" align="center"><template #default="scope">{{ flowNames[scope.row.flow_id] || shortId(scope.row.flow_id) }}</template></el-table-column>
      <el-table-column label="状态" width="130" align="center"><template #default="scope"><strong :class="`status-${scope.row.status}`">● {{ scope.row.status }}</strong></template></el-table-column>
      <el-table-column label="开始时间" min-width="190" align="center"><template #default="scope">{{ new Date(scope.row.created_at).toLocaleString() }}</template></el-table-column>
      <el-table-column label="耗时" width="110" align="center"><template #default="scope">{{ totalDuration(scope.row) }} ms</template></el-table-column>
      <el-table-column label="尝试次数" width="110" align="center"><template #default="scope">{{ scope.row.step_runs.length }}</template></el-table-column>
      <el-table-column label="运行 ID" width="130" align="center"><template #default="scope"><code>{{ shortId(scope.row.id) }}</code></template></el-table-column>
      <el-table-column label="操作" fixed="right" width="130" align="center"><template #default="scope"><div class="icon-action-group"><el-button class="icon-action-button" link type="primary" :icon="View" aria-label="详情" @click.stop="openDetail(scope.row)"><span class="icon-action-label">详情</span></el-button></div></template></el-table-column>
    </el-table>
    <div v-if="!filteredRuns.length" class="empty-state">{{ selectedPlanId ? '该测试计划暂无流程执行记录。' : '还没有执行记录。' }}</div>
  </el-card>

  <el-dialog v-model="launchDialog" title="运行测试流程" width="620px">
    <el-form label-position="top">
      <el-form-item label="测试流程"><el-select v-model="launch.flow_id" style="width: 100%"><el-option v-for="flow in flows" :key="flow.id" :label="`${flow.name} (${flow.steps.length} steps)`" :value="flow.id" /></el-select></el-form-item>
      <el-form-item label="本次输入（JSON）"><el-input v-model="launch.inputs" class="json-input" type="textarea" :rows="9" /><p class="muted">优先级高于项目变量和流程变量。</p></el-form-item>
    </el-form>
    <template #footer><el-button @click="launchDialog = false">取消</el-button><el-button type="primary" :disabled="!launch.flow_id" @click="start">开始执行</el-button></template>
  </el-dialog>

  <el-dialog v-model="detailDialog" :title="`运行详情 · ${selected ? shortId(selected.id) : ''}`" width="900px" top="5vh">
    <template v-if="selected">
      <el-descriptions :column="3" border>
        <el-descriptions-item label="流程">{{ flowNames[selected.flow_id] }}</el-descriptions-item>
        <el-descriptions-item label="状态"><strong :class="`status-${selected.status}`">{{ selected.status }}</strong></el-descriptions-item>
        <el-descriptions-item label="尝试">{{ selected.step_runs.length }}</el-descriptions-item>
      </el-descriptions>
      <el-alert v-if="selected.error" :title="selected.error" type="error" :closable="false" style="margin-top: 14px" />
      <el-collapse style="margin-top: 16px">
        <el-collapse-item v-for="step in selected.step_runs" :key="step.id" :name="step.id">
          <template #title><span class="step-number" style="margin-right: 10px">{{ step.position + 1 }}</span><strong>{{ step.step_name }}</strong><el-tag :type="step.status === 'passed' ? 'success' : 'danger'" size="small" style="margin-left: 10px">attempt {{ step.attempt }} · {{ step.status }}</el-tag><span class="muted" style="margin-left: auto; margin-right: 12px">{{ step.duration_ms.toFixed(0) }} ms</span></template>
          <div class="two-col"><div><p class="muted">请求</p><pre class="code-block">{{ pretty(step.request_snapshot) }}</pre></div><div><p class="muted">响应</p><pre class="code-block">{{ pretty(step.response_snapshot || { error: step.error }) }}</pre></div></div>
          <div v-if="step.assertion_results.length" class="assertion-results">
            <p class="muted">成功条件结果</p>
            <div v-for="result in step.assertion_results" :key="result.assertion_id" class="assertion-result">
              <el-tag :type="result.passed ? 'success' : 'danger'" size="small">{{ result.passed ? '通过' : '失败' }}</el-tag>
              <strong>{{ result.name }}</strong><span class="muted">{{ result.message }}</span>
            </div>
          </div>
          <p v-if="Object.keys(step.extracted).length" class="muted" style="margin-top: 10px">提取值：<code>{{ pretty(step.extracted) }}</code></p>
        </el-collapse-item>
      </el-collapse>
      <el-tabs style="margin-top: 18px"><el-tab-pane label="最终上下文"><pre class="code-block">{{ pretty(selected.context) }}</pre></el-tab-pane><el-tab-pane label="运行输入"><pre class="code-block">{{ pretty(selected.inputs) }}</pre></el-tab-pane></el-tabs>
    </template>
  </el-dialog>
</template>
