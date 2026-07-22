<script setup lang="ts">
import { Delete, Plus } from '@element-plus/icons-vue'
import { computed, ref } from 'vue'

type ParameterLocation = 'path' | 'query' | 'header' | 'body'
type ParameterItem = Record<string, unknown>

const props = defineProps<{
  modelValue: ParameterItem[]
  pathParams: string[]
}>()
const emit = defineEmits<{ 'update:modelValue': [value: ParameterItem[]] }>()
const filter = ref<'all' | ParameterLocation>('all')

const filters = computed(() => [
  { label: `全部 ${props.modelValue.length}`, value: 'all' },
  ...(['path', 'query', 'header', 'body'] as ParameterLocation[]).map((location) => ({
    label: `${locationLabel(location)} ${props.modelValue.filter((item) => item.in === location).length}`,
    value: location,
  })),
])
const visibleItems = computed(() => props.modelValue
  .map((item, index) => ({ item, index }))
  .filter(({ item }) => filter.value === 'all' || item.in === filter.value))

function locationLabel(location: ParameterLocation) {
  return { path: 'Path', query: 'Query', header: 'Header', body: 'Body' }[location]
}

function update(index: number, field: string, value: unknown) {
  const next = props.modelValue.map((item, itemIndex) =>
    itemIndex === index ? { ...item, [field]: value } : item)
  emit('update:modelValue', next)
}

function add(location: ParameterLocation = filter.value === 'all' ? 'query' : filter.value) {
  emit('update:modelValue', [
    ...props.modelValue,
    { name: '', in: location, type: 'string', required: location === 'path', description: '', example: '' },
  ])
}

function remove(index: number) {
  emit('update:modelValue', props.modelValue.filter((_, itemIndex) => itemIndex !== index))
}
</script>

<template>
  <div class="parameters-editor">
    <div class="editor-mode-bar">
      <div><strong>参数说明</strong><p class="muted">这里描述 API 的参数契约；实际发送值在“请求配置”中填写。</p></div>
      <el-button type="primary" plain :icon="Plus" @click="add()">添加参数</el-button>
    </div>
    <el-segmented v-model="filter" :options="filters" class="parameter-filters" />
    <div v-if="visibleItems.length" class="parameter-list">
      <article v-for="({ item, index }) in visibleItems" :key="index" class="parameter-card" :class="{ 'is-path': item.in === 'path' }">
        <div class="parameter-main">
          <el-select :model-value="String(item.in || 'query')" aria-label="参数位置" @update:model-value="update(index, 'in', $event)">
            <el-option label="Path" value="path" /><el-option label="Query" value="query" /><el-option label="Header" value="header" /><el-option label="Body" value="body" />
          </el-select>
          <el-input :model-value="String(item.name || '')" aria-label="参数名称" placeholder="参数名称" @update:model-value="update(index, 'name', $event)">
            <template #suffix><el-tag v-if="pathParams.includes(String(item.name))" type="warning" size="small">已识别</el-tag></template>
          </el-input>
          <el-select :model-value="String(item.type || 'string')" aria-label="参数类型" @update:model-value="update(index, 'type', $event)">
            <el-option v-for="type in ['string', 'integer', 'number', 'boolean', 'object', 'array']" :key="type" :label="type" :value="type" />
          </el-select>
          <el-checkbox :model-value="Boolean(item.required)" :disabled="item.in === 'path'" @update:model-value="update(index, 'required', $event)">必填</el-checkbox>
          <el-button text type="danger" :icon="Delete" aria-label="删除参数" @click="remove(index)" />
        </div>
        <div class="parameter-detail">
          <el-input :model-value="String(item.description || '')" aria-label="参数说明" placeholder="说明参数用途、约束或格式" @update:model-value="update(index, 'description', $event)" />
          <el-input :model-value="String(item.example ?? '')" aria-label="参数示例" placeholder="示例值" @update:model-value="update(index, 'example', $event)" />
        </div>
      </article>
    </div>
    <div v-else class="editor-empty"><strong>还没有{{ filter === 'all' ? '' : ` ${locationLabel(filter)}` }}参数</strong><span>点击“添加参数”建立可读的 API 参数文档。</span></div>
  </div>
</template>
