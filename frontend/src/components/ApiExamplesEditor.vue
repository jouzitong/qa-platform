<script setup lang="ts">
import { Delete, Plus } from '@element-plus/icons-vue'

import { pretty } from '../utils'

type ExampleItem = Record<string, unknown>

const props = defineProps<{ modelValue: ExampleItem[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: ExampleItem[]] }>()

function update(index: number, field: string, value: unknown) {
  emit('update:modelValue', props.modelValue.map((item, itemIndex) =>
    itemIndex === index ? { ...item, [field]: value } : item))
}

function updateJson(index: number, field: string, value: string) {
  try { update(index, field, JSON.parse(value)) }
  catch { /* Keep the last valid value; users can continue correcting the field. */ }
}

function add() {
  emit('update:modelValue', [
    ...props.modelValue,
    { name: `案例 ${props.modelValue.length + 1}`, description: '', inputs: {}, request: {}, expected_response: {} },
  ])
}

function remove(index: number) {
  emit('update:modelValue', props.modelValue.filter((_, itemIndex) => itemIndex !== index))
}
</script>

<template>
  <div class="examples-editor">
    <div class="editor-mode-bar">
      <div><strong>参考案例</strong><p class="muted">给调用者一个可复制的输入和预期响应，也可作为调试起点。</p></div>
      <el-button type="primary" plain :icon="Plus" @click="add">添加案例</el-button>
    </div>
    <el-collapse v-if="modelValue.length" accordion class="example-list">
      <el-collapse-item v-for="(item, index) in modelValue" :key="index" :name="index">
        <template #title><span class="example-index">{{ index + 1 }}</span><strong>{{ item.name || `案例 ${index + 1}` }}</strong><span class="muted example-summary">{{ item.description || '未填写说明' }}</span></template>
        <div class="example-card">
          <div class="example-header">
            <el-input :model-value="String(item.name || '')" aria-label="案例名称" placeholder="案例名称" @update:model-value="update(index, 'name', $event)" />
            <el-button text type="danger" :icon="Delete" @click.stop="remove(index)">删除案例</el-button>
          </div>
          <el-input :model-value="String(item.description || '')" aria-label="案例说明" placeholder="这个案例适用于什么场景？" @update:model-value="update(index, 'description', $event)" />
          <div class="example-grid">
            <label><span>上下文输入</span><el-input :model-value="pretty(item.inputs || {})" class="json-input" type="textarea" :rows="7" @change="updateJson(index, 'inputs', $event)" /></label>
            <label><span>请求覆盖</span><el-input :model-value="pretty(item.request || {})" class="json-input" type="textarea" :rows="7" @change="updateJson(index, 'request', $event)" /></label>
            <label><span>预期响应示例</span><el-input :model-value="pretty(item.expected_response || {})" class="json-input" type="textarea" :rows="7" @change="updateJson(index, 'expected_response', $event)" /></label>
          </div>
        </div>
      </el-collapse-item>
    </el-collapse>
    <div v-else class="editor-empty"><strong>还没有参考案例</strong><span>添加成功、失败或边界场景，使用者会更容易理解和验证 API。</span><el-button type="primary" plain :icon="Plus" @click="add">创建第一个案例</el-button></div>
  </div>
</template>
