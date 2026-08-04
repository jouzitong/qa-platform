<script setup lang="ts">
import { Calendar, CircleCheck, Connection, DataAnalysis, Document, EditPen, Files, Guide, Monitor, Operation, Promotion, SetUp, Tickets } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'
import { onMounted } from 'vue'

import { useProjectContext } from './state/project'

const route = useRoute()
const { projects, projectId, loadProjects } = useProjectContext()

const primaryMenu = [
  { path: '/', label: '工作台', icon: Monitor },
  { path: '/projects', label: '项目', icon: Files },
]

const automationMenu = [
  { path: '/test/apis', label: 'API 管理', icon: Connection },
  { path: '/test/assertions', label: '断言管理', icon: CircleCheck },
  { path: '/test/flows', label: '测试流程', icon: Guide },
  { path: '/test/plans', label: '测试计划', icon: Calendar },
  { path: '/test/runs', label: '执行记录', icon: DataAnalysis },
]

const requirementMenu = [
  { path: '/requirements', label: '需求池', icon: Tickets },
  { path: '/requirements/prototypes', label: '产品原型', icon: EditPen },
  { path: '/requirements/tasks', label: '开发任务', icon: SetUp },
  { path: '/requirements/releases', label: '发布计划', icon: Promotion },
  { path: '/requirements/documents', label: '文档中心', icon: Document },
]

onMounted(() => { void loadProjects() })
</script>

<template>
  <el-container class="app-shell">
    <el-aside width="240px" class="sidebar">
      <div class="brand">
        <div class="brand-mark">Q</div>
        <div class="brand-content">
          <strong>qa-platform</strong>
          <el-select v-model="projectId" class="brand-project-select" size="small" filterable placeholder="选择项目">
            <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
          </el-select>
        </div>
      </div>
      <el-menu router :default-active="route.path" :default-openeds="['/test', '/requirements']" class="nav-menu">
        <el-menu-item v-for="item in primaryMenu" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </el-menu-item>
        <el-sub-menu index="/test">
          <template #title>
            <el-icon><Operation /></el-icon>
            <span>自动化测试</span>
          </template>
          <el-menu-item v-for="item in automationMenu" :key="item.path" :index="item.path">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </el-menu-item>
        </el-sub-menu>
        <el-sub-menu index="/requirements">
          <template #title>
            <el-icon><Tickets /></el-icon>
            <span>需求管理</span>
          </template>
          <el-menu-item v-for="item in requirementMenu" :key="item.path" :index="item.path">
            <el-icon><component :is="item.icon" /></el-icon>
            <span>{{ item.label }}</span>
          </el-menu-item>
        </el-sub-menu>
      </el-menu>
      <div class="sidebar-foot">
        <el-avatar :size="32" class="user-avatar">ZT</el-avatar>
        <div class="sidebar-user">
          <strong>Zhou Zhitong</strong>
          <small>Local workspace</small>
        </div>
        <span class="sidebar-version">v0.1 MVP</span>
      </div>
  </el-aside>
    <el-container class="workspace-container">
      <el-header class="topbar">
        <div id="page-header-content" class="page-header-content" />
      </el-header>
      <el-main class="page"><router-view /></el-main>
      <el-footer class="app-footer">
        <div id="page-footer-content" class="page-footer-content" />
      </el-footer>
    </el-container>
  </el-container>
</template>
