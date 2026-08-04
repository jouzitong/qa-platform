<script setup lang="ts">
import { Calendar, CircleCheck, Connection, DataAnalysis, Document, EditPen, Files, Guide, Monitor, Operation, Promotion, SetUp, Tickets } from '@element-plus/icons-vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const primaryMenu = [
  { path: '/', label: '工作台', icon: Monitor },
  { path: '/projects', label: '项目', icon: Files },
]

const automationMenu = [
  { path: '/apis', label: 'API 管理', icon: Connection },
  { path: '/assertions', label: '断言管理', icon: CircleCheck },
  { path: '/flows', label: '测试流程', icon: Guide },
  { path: '/plans', label: '测试计划', icon: Calendar },
  { path: '/runs', label: '执行记录', icon: DataAnalysis },
]

const requirementMenu = [
  { path: '/requirements', label: '需求池', icon: Tickets },
  { path: '/requirements/prototypes', label: '产品原型', icon: EditPen },
  { path: '/requirements/tasks', label: '开发任务', icon: SetUp },
  { path: '/requirements/releases', label: '发布计划', icon: Promotion },
  { path: '/requirements/documents', label: '交付文档', icon: Document },
]
</script>

<template>
  <el-container class="app-shell">
    <el-aside width="240px" class="sidebar">
      <div class="brand">
        <div class="brand-mark">Q</div>
        <div><strong>qa-platform</strong><small>Automation workspace</small></div>
      </div>
      <el-menu router :default-active="route.path" :default-openeds="['/automation', '/requirements']" class="nav-menu">
        <el-menu-item v-for="item in primaryMenu" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </el-menu-item>
        <el-sub-menu index="/automation">
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
    <el-container>
      <el-main class="page"><router-view /></el-main>
    </el-container>
  </el-container>
</template>
