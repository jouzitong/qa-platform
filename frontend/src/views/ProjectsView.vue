<script setup lang="ts">
import { Delete, Edit } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { onMounted, reactive, ref } from 'vue'

import { api } from '../api/client'
import type { Project } from '../types'
import { parseJson, pretty } from '../utils'

const loading = ref(false)
const projects = ref<Project[]>([])
const dialog = ref(false)
const editingId = ref('')
const form = reactive({ name: '', description: '', variables: '{\n  "base_url": "https://api.example.com"\n}' })

async function load() {
  loading.value = true
  try { projects.value = await api.projects.list() }
  catch (error) { ElMessage.error((error as Error).message) }
  finally { loading.value = false }
}

function openCreate() {
  editingId.value = ''
  Object.assign(form, { name: '', description: '', variables: '{\n  "base_url": "https://api.example.com"\n}' })
  dialog.value = true
}

function openEdit(row: Project) {
  editingId.value = row.id
  Object.assign(form, { name: row.name, description: row.description, variables: pretty(row.variables) })
  dialog.value = true
}

async function save() {
  try {
    const payload = { name: form.name, description: form.description, variables: parseJson<Record<string, unknown>>(form.variables, '项目变量') }
    if (editingId.value) await api.projects.update(editingId.value, payload)
    else await api.projects.create(payload)
    dialog.value = false
    ElMessage.success('项目已保存')
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
}

async function remove(row: Project) {
  await ElMessageBox.confirm(`删除项目“${row.name}”及其 API、流程和运行记录？`, '确认删除', { type: 'warning' })
  await api.projects.remove(row.id)
  ElMessage.success('项目已删除')
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page-head">
    <div><h2>项目空间</h2><p>每个项目拥有独立的 API 资产、环境变量和测试流程。</p></div>
    <el-button type="primary" @click="openCreate">新建项目</el-button>
  </div>
  <el-card class="panel" shadow="never">
    <el-table v-loading="loading" :data="projects">
      <el-table-column prop="name" label="名称" min-width="180" />
      <el-table-column prop="description" label="说明" min-width="260" show-overflow-tooltip />
      <el-table-column label="变量" min-width="260"><template #default="scope"><el-tag v-for="(_, key) in scope.row.variables" :key="key" size="small" effect="plain" style="margin-right: 6px">{{ key }}</el-tag></template></el-table-column>
      <el-table-column label="操作" width="150" align="right"><template #default="scope"><el-button class="icon-action-button" link type="primary" :icon="Edit" aria-label="编辑" @click="openEdit(scope.row)"><span class="icon-action-label">编辑</span></el-button><el-button class="icon-action-button" link type="danger" :icon="Delete" aria-label="删除" @click="remove(scope.row)"><span class="icon-action-label">删除</span></el-button></template></el-table-column>
    </el-table>
    <div v-if="!loading && !projects.length" class="empty-state">创建第一个项目，开始沉淀测试资产。</div>
  </el-card>

  <el-dialog v-model="dialog" :title="editingId ? '编辑项目' : '新建项目'" width="620px">
    <el-form label-position="top">
      <el-form-item label="项目名称"><el-input v-model="form.name" placeholder="例如：交易服务" /></el-form-item>
      <el-form-item label="项目说明"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
      <el-form-item label="项目变量（JSON）"><el-input v-model="form.variables" class="json-input" type="textarea" :rows="8" /><div class="muted">流程中可通过 <code v-pre>{{ base_url }}</code> 引用。</div></el-form-item>
    </el-form>
    <template #footer><el-button @click="dialog = false">取消</el-button><el-button type="primary" :disabled="!form.name" @click="save">保存</el-button></template>
  </el-dialog>
</template>
