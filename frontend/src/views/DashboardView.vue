<script setup lang="ts">
import { Upload } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, ref, watch } from 'vue'

import { api } from '../api/client'
import { useProjectContext } from '../state/project'
import type { ApiDefinition, ImportPreviewItem, ImportSession, TestFlow, TestRun } from '../types'

const { projects, projectId, refreshProjects } = useProjectContext()
const definitions = ref<ApiDefinition[]>([])
const flows = ref<TestFlow[]>([])
const runs = ref<TestRun[]>([])
const passed = computed(() => runs.value.filter((run) => run.status === 'passed').length)
const importDialog = ref(false)
const importFileInput = ref<HTMLInputElement | null>(null)
const importFile = ref<File | null>(null)
const importSession = ref<ImportSession | null>(null)
const importTarget = ref<'package' | 'current'>('package')
const importLoading = ref(false)
const importApplying = ref(false)
const importItems = computed<ImportPreviewItem[]>(() => importSession.value?.preview.items || [])
const importSummary = computed(() => importSession.value?.preview.summary || {})

function openImport() {
  importDialog.value = true
  importFile.value = null
  importSession.value = null
  importTarget.value = 'package'
}

function chooseImportFile() {
  importFileInput.value?.click()
}

function onImportFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  importFile.value = input.files?.[0] || null
  importSession.value = null
}

async function previewImport() {
  if (!importFile.value) return
  importLoading.value = true
  try {
    const targetProjectId = importTarget.value === 'current' ? projectId.value || undefined : undefined
    importSession.value = await api.imports.preview(importFile.value, targetProjectId)
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { importLoading.value = false }
}

async function approveImport() {
  if (!importSession.value) return
  importApplying.value = true
  try {
    importSession.value = await api.imports.approve(importSession.value.id)
    await refreshProjects()
    ElMessage.success('导入已确认并生效')
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { importApplying.value = false }
}

async function rejectImport() {
  if (!importSession.value) return
  try {
    importSession.value = await api.imports.reject(importSession.value.id)
    ElMessage.success('已拒绝本次导入')
  } catch (error) { ElMessage.error((error as Error).message) }
}

function importActionLabel(action: string) {
  return { create: '新增', update: '更新', unchanged: '不变' }[action] || action
}

function importActionType(action: string) {
  return action === 'create' ? 'success' : action === 'update' ? 'warning' : 'info'
}

function importTypeLabel(type: string) {
  return {
    project: '项目', api_templates: 'API 模板', apis: 'API',
    assertion_definitions: '成功条件',
    flows: '测试流程', test_plans: '测试计划',
  }[type] || type
}

async function load() {
  try {
    if (!projectId.value) {
      definitions.value = []
      flows.value = []
    } else {
      ;[definitions.value, flows.value] = await Promise.all([
        api.definitions.list(projectId.value), api.flows.list(projectId.value),
      ])
    }
    runs.value = await api.runs.list()
  } catch (error) { ElMessage.error((error as Error).message) }
}

watch(projectId, load, { immediate: true })
</script>

<template>
  <Teleport to="#page-header-content">
    <div class="page-header-content-inner">
      <el-tag type="success" effect="plain">资产与执行概览</el-tag>
      <el-button :icon="Upload" @click="openImport">导入项目 / 测试资产</el-button>
      <el-button type="primary" @click="$router.push('/test/flows')">创建测试流程</el-button>
    </div>
  </Teleport>
  <div class="stats">
    <div class="stat-card"><span class="stat-label">项目</span><strong class="stat-value">{{ projects.length }}</strong></div>
    <div class="stat-card"><span class="stat-label">API 资产</span><strong class="stat-value">{{ definitions.length }}</strong></div>
    <div class="stat-card"><span class="stat-label">测试流程</span><strong class="stat-value">{{ flows.length }}</strong></div>
    <div class="stat-card"><span class="stat-label">通过运行</span><strong class="stat-value stat-accent">{{ passed }}</strong></div>
  </div>
  <div class="two-col">
    <el-card class="panel" shadow="never">
      <template #header><strong>最近执行</strong></template>
      <el-table class="list-table" :data="runs.slice(0, 6)">
        <el-table-column label="运行" width="120" align="center"><template #default="scope">{{ scope.row.id.slice(0, 8) }}</template></el-table-column>
        <el-table-column prop="status" label="状态" align="center"><template #default="scope"><span :class="`status-${scope.row.status}`">● {{ scope.row.status }}</span></template></el-table-column>
        <el-table-column prop="created_at" label="创建时间" align="center"><template #default="scope">{{ new Date(scope.row.created_at).toLocaleString() }}</template></el-table-column>
      </el-table>
      <div v-if="!runs.length" class="empty-state">还没有执行记录</div>
    </el-card>
    <el-card class="panel" shadow="never">
      <template #header><strong>快速开始</strong></template>
      <el-steps direction="vertical" :active="projects.length ? (definitions.length ? (flows.length ? 3 : 2) : 1) : 0" finish-status="success">
        <el-step title="创建项目" description="设置 base_url、token 等项目变量" />
        <el-step title="登记 API" description="维护协议、参数说明和调用案例" />
        <el-step title="编排流程" description="配置断言、变量提取和重试规则" />
      </el-steps>
    </el-card>
  </div>

  <el-dialog v-model="importDialog" title="导入项目 / 测试资产" width="820px" destroy-on-close>
    <div class="import-dialog">
      <el-alert
        title="导入不会立即修改项目。解析完成后请检查变更，并点击“确认导入”后才会生效。"
        type="info" :closable="false" show-icon
      />
      <div class="import-file-picker">
        <input ref="importFileInput" class="import-file-input" type="file" accept=".zip,.rar" @change="onImportFileChange" />
        <div>
          <strong>{{ importFile?.name || '请选择导入压缩包' }}</strong>
          <p>支持 ZIP；RAR 当前会被明确拦截。包内可按 v1.0.0/api.json、flow.json 等版本目录组织。</p>
        </div>
        <el-button @click="chooseImportFile">选择文件</el-button>
        <el-button type="primary" :loading="importLoading" :disabled="!importFile" @click="previewImport">开始解析</el-button>
      </div>
      <div class="import-target-picker">
        <span>导入目标</span>
        <el-radio-group v-model="importTarget" size="small">
          <el-radio-button label="package">按压缩包项目新增 / 更新</el-radio-button>
          <el-radio-button label="current" :disabled="!projectId">导入到当前项目</el-radio-button>
        </el-radio-group>
      </div>

      <template v-if="importSession">
        <el-steps class="import-steps" :active="importSession.status === 'pending' ? 1 : 2" finish-status="success" simple>
          <el-step title="解析预览" />
          <el-step title="人工确认" />
          <el-step title="导入生效" />
        </el-steps>
        <div class="import-summary">
          <el-tag effect="plain">包版本 {{ importSession.package_version }}</el-tag>
          <el-tag type="success" effect="plain">新增 {{ importSummary.create || 0 }}</el-tag>
          <el-tag type="warning" effect="plain">更新 {{ importSummary.update || 0 }}</el-tag>
          <el-tag type="info" effect="plain">不变 {{ importSummary.unchanged || 0 }}</el-tag>
          <el-tag v-if="importSession.status !== 'pending'" type="success" effect="plain">{{ importSession.status === 'applied' ? '已生效' : importSession.status }}</el-tag>
        </div>
        <el-alert v-if="importSession.errors.length" class="import-alert" title="存在校验错误，不能确认导入" type="error" :closable="false">
          <ul><li v-for="error in importSession.errors" :key="error">{{ error }}</li></ul>
        </el-alert>
        <el-alert v-if="importSession.warnings.length" class="import-alert" title="导入提示" type="warning" :closable="false">
          <ul><li v-for="warning in importSession.warnings" :key="warning">{{ warning }}</li></ul>
        </el-alert>
        <el-table class="import-preview-table list-table" :data="importItems" max-height="360">
          <el-table-column prop="type" label="类型" width="120" align="center"><template #default="scope">{{ importTypeLabel(scope.row.type) }}</template></el-table-column>
          <el-table-column prop="name" label="名称" min-width="180" show-overflow-tooltip />
          <el-table-column prop="key" label="唯一标识" min-width="180" show-overflow-tooltip />
          <el-table-column prop="action" label="变更" width="90" align="center"><template #default="scope"><el-tag size="small" :type="importActionType(scope.row.action)" effect="plain">{{ importActionLabel(scope.row.action) }}</el-tag></template></el-table-column>
          <el-table-column prop="changes" label="变化字段" min-width="180" show-overflow-tooltip><template #default="scope">{{ scope.row.changes.join('、') || '—' }}</template></el-table-column>
        </el-table>
      </template>
    </div>
    <template #footer>
      <el-button @click="importDialog = false">关闭</el-button>
      <el-button v-if="importSession?.status === 'pending'" @click="rejectImport">拒绝导入</el-button>
      <el-button v-if="importSession?.status === 'pending'" type="primary" :loading="importApplying" :disabled="!!importSession.errors.length" @click="approveImport">确认导入</el-button>
    </template>
  </el-dialog>
</template>
