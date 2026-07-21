<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { computed, onMounted, ref } from 'vue'

import { api } from '../api/client'
import type { ApiDefinition, Project, TestFlow, TestRun } from '../types'

const projects = ref<Project[]>([])
const definitions = ref<ApiDefinition[]>([])
const flows = ref<TestFlow[]>([])
const runs = ref<TestRun[]>([])
const passed = computed(() => runs.value.filter((run) => run.status === 'passed').length)

onMounted(async () => {
  try {
    ;[projects.value, definitions.value, flows.value, runs.value] = await Promise.all([
      api.projects.list(), api.definitions.list(), api.flows.list(), api.runs.list(),
    ])
  } catch (error) { ElMessage.error((error as Error).message) }
})
</script>

<template>
  <div class="page-head">
    <div><h2>自动化测试概览</h2><p>从 API 资产到流程执行，一处维护完整测试上下文。</p></div>
    <el-button type="primary" @click="$router.push('/flows')">创建测试流程</el-button>
  </div>
  <div class="stats">
    <div class="stat-card"><span class="stat-label">项目</span><strong class="stat-value">{{ projects.length }}</strong></div>
    <div class="stat-card"><span class="stat-label">API 资产</span><strong class="stat-value">{{ definitions.length }}</strong></div>
    <div class="stat-card"><span class="stat-label">测试流程</span><strong class="stat-value">{{ flows.length }}</strong></div>
    <div class="stat-card"><span class="stat-label">通过运行</span><strong class="stat-value stat-accent">{{ passed }}</strong></div>
  </div>
  <div class="two-col">
    <el-card class="panel" shadow="never">
      <template #header><strong>最近执行</strong></template>
      <el-table :data="runs.slice(0, 6)">
        <el-table-column label="运行" width="120"><template #default="scope">{{ scope.row.id.slice(0, 8) }}</template></el-table-column>
        <el-table-column prop="status" label="状态"><template #default="scope"><span :class="`status-${scope.row.status}`">● {{ scope.row.status }}</span></template></el-table-column>
        <el-table-column prop="created_at" label="创建时间"><template #default="scope">{{ new Date(scope.row.created_at).toLocaleString() }}</template></el-table-column>
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
</template>
