<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, reactive, ref } from 'vue'

import { api } from '../api/client'
import type { TestFlow, TestRun } from '../types'
import { parseJson, pretty, shortId } from '../utils'

const flows = ref<TestFlow[]>([])
const runs = ref<TestRun[]>([])
const launchDialog = ref(false)
const detailDialog = ref(false)
const selected = ref<TestRun | null>(null)
const liveEvents = ref<object[]>([])
const launch = reactive({ flow_id: '', inputs: '{}' })
const flowNames = computed(() => Object.fromEntries(flows.value.map((flow) => [flow.id, flow.name])))

function totalDuration(run: TestRun): string {
  return run.step_runs.reduce((sum, step) => sum + step.duration_ms, 0).toFixed(0)
}

async function load() {
  try { ;[flows.value, runs.value] = await Promise.all([api.flows.list(), api.runs.list()]) }
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
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const socket = new WebSocket(`${protocol}//${location.host}/api/v1/ws/runs/${runId}`)
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

onMounted(load)
</script>

<template>
  <div class="page-head">
    <div><h2>执行记录</h2><p>查看流程运行状态、每次重试、请求响应和最终上下文。</p></div>
    <div><el-button @click="load">刷新</el-button><el-button type="primary" :disabled="!flows.length" @click="openLaunch()">运行流程</el-button></div>
  </div>
  <el-card class="panel" shadow="never">
    <el-table :data="runs" @row-click="openDetail">
      <el-table-column label="运行 ID" width="130"><template #default="scope"><code>{{ shortId(scope.row.id) }}</code></template></el-table-column>
      <el-table-column label="流程" min-width="180"><template #default="scope">{{ flowNames[scope.row.flow_id] || shortId(scope.row.flow_id) }}</template></el-table-column>
      <el-table-column label="状态" width="130"><template #default="scope"><strong :class="`status-${scope.row.status}`">● {{ scope.row.status }}</strong></template></el-table-column>
      <el-table-column label="尝试次数" width="110"><template #default="scope">{{ scope.row.step_runs.length }}</template></el-table-column>
      <el-table-column label="开始时间" min-width="190"><template #default="scope">{{ new Date(scope.row.created_at).toLocaleString() }}</template></el-table-column>
      <el-table-column label="耗时" width="110"><template #default="scope">{{ totalDuration(scope.row) }} ms</template></el-table-column>
      <el-table-column label="" width="90"><template #default><el-button link type="primary">详情</el-button></template></el-table-column>
    </el-table>
    <div v-if="!runs.length" class="empty-state">还没有执行记录。</div>
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
            <p class="muted">断言结果</p>
            <div v-for="result in step.assertion_results" :key="result.assertion_id" class="assertion-result">
              <el-tag :type="result.passed ? 'success' : result.severity === 'warning' ? 'warning' : 'danger'" size="small">{{ result.passed ? '通过' : result.severity === 'warning' ? '警告' : '失败' }}</el-tag>
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
