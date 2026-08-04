<script setup lang="ts">
import { Calendar, CircleCheck, Connection, DataAnalysis, Files, Guide, Monitor, Operation } from '@element-plus/icons-vue'
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
</script>

<template>
  <el-container class="app-shell">
    <el-aside width="240px" class="sidebar">
      <div class="brand">
        <div class="brand-mark">Q</div>
        <div><strong>qa-platform</strong><small>Automation workspace</small></div>
      </div>
      <el-menu router :default-active="route.path" :default-openeds="['/automation']" class="nav-menu">
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
