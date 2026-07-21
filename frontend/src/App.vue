<script setup lang="ts">
import { Connection, DataAnalysis, Files, Guide, Monitor } from '@element-plus/icons-vue'
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const title = computed(() => route.meta.title as string)

const menu = [
  { path: '/', label: '工作台', icon: Monitor },
  { path: '/projects', label: '项目', icon: Files },
  { path: '/apis', label: 'API 管理', icon: Connection },
  { path: '/flows', label: '测试流程', icon: Guide },
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
      <el-menu router :default-active="route.path" class="nav-menu">
        <el-menu-item v-for="item in menu" :key="item.path" :index="item.path">
          <el-icon><component :is="item.icon" /></el-icon>
          <span>{{ item.label }}</span>
        </el-menu-item>
      </el-menu>
      <div class="sidebar-foot"><span class="online-dot" />Local workspace</div>
    </el-aside>
    <el-container>
      <el-header class="topbar">
        <div>
          <p class="eyebrow">QUALITY ENGINEERING</p>
          <h1>{{ title }}</h1>
        </div>
        <el-tag effect="plain" round>v0.1 MVP</el-tag>
      </el-header>
      <el-main class="page"><router-view /></el-main>
    </el-container>
  </el-container>
</template>
