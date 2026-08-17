<script setup lang="ts">
import { ArrowDown, ArrowRight, Delete, Plus } from '@element-plus/icons-vue'
import { computed, ref } from 'vue'

type ParameterLocation = 'path' | 'query' | 'header' | 'body'
type ParameterItem = Record<string, unknown>
type ParameterRow = {
  item: ParameterItem
  path: number[]
  depth: number
  location: ParameterLocation
}

const props = defineProps<{
  modelValue: ParameterItem[]
  pathParams: string[]
}>()
const emit = defineEmits<{ 'update:modelValue': [value: ParameterItem[]] }>()
const filter = ref<'all' | ParameterLocation>('all')
const expanded = ref<Record<string, boolean>>({})

const filters = computed(() => [
  { label: `全部 ${props.modelValue.length}`, value: 'all' },
  ...(['path', 'query', 'header', 'body'] as ParameterLocation[]).map((location) => ({
    label: `${locationLabel(location)} ${props.modelValue.filter((item) => item.in === location).length}`,
    value: location,
  })),
])

function locationLabel(location: ParameterLocation) {
  return { path: 'Path', query: 'Query', header: 'Header', body: 'Body' }[location]
}

function isParameterItem(value: unknown): value is ParameterItem {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function childrenOf(item: ParameterItem): ParameterItem[] {
  const children = Array.isArray(item['children'])
    ? item['children']
    : item['child_params']
  return Array.isArray(children) ? children.filter(isParameterItem) : []
}

function isObjectParameter(item: ParameterItem) {
  return String(item.type || 'string') === 'object'
}

function pathKey(path: number[]) {
  return path.join('.')
}

function isExpanded(path: number[], item: ParameterItem) {
  const key = pathKey(path)
  return expanded.value[key] ?? (isObjectParameter(item) && childrenOf(item).length > 0)
}

function toggleExpanded(path: number[], item: ParameterItem) {
  const key = pathKey(path)
  expanded.value = { ...expanded.value, [key]: !isExpanded(path, item) }
}

function withChildren(item: ParameterItem, children: ParameterItem[]): ParameterItem {
  const next: ParameterItem = { ...item, children }
  delete next['child_params']
  return next
}

function flattenRows(
  items: ParameterItem[],
  parentPath: number[] = [],
  depth = 0,
  inheritedLocation: ParameterLocation = 'body',
): ParameterRow[] {
  const rows: ParameterRow[] = []
  items.forEach((item, index) => {
    const path = [...parentPath, index]
    const location = parentPath.length
      ? inheritedLocation
      : (String(item.in || 'query') as ParameterLocation)
    const row = { item, path, depth, location }
    rows.push(row)
    if (isObjectParameter(item) && isExpanded(path, item)) {
      rows.push(...flattenRows(childrenOf(item), path, depth + 1, location))
    }
  })
  return rows
}

const visibleItems = computed(() => flattenRows(props.modelValue)
  .filter(({ location }) => filter.value === 'all' || location === filter.value))

function updateAtPath(
  items: ParameterItem[],
  path: number[],
  updater: (item: ParameterItem) => ParameterItem,
): ParameterItem[] {
  if (!path.length) return items
  const [index, ...rest] = path
  if (!items[index]) return items
  if (!rest.length) {
    return items.map((item, itemIndex) => itemIndex === index ? updater(item) : item)
  }
  const parent = items[index]
  const nextChildren = updateAtPath(childrenOf(parent), rest, updater)
  return items.map((item, itemIndex) => (
    itemIndex === index ? withChildren(item, nextChildren) : item
  ))
}

function removeAtPath(items: ParameterItem[], path: number[]): ParameterItem[] {
  if (!path.length) return items
  const [index, ...rest] = path
  if (!items[index]) return items
  if (!rest.length) return items.filter((_, itemIndex) => itemIndex !== index)
  const parent = items[index]
  const nextChildren = removeAtPath(childrenOf(parent), rest)
  return items.map((item, itemIndex) => (
    itemIndex === index ? withChildren(item, nextChildren) : item
  ))
}

function update(path: number[], field: string, value: unknown) {
  const next = updateAtPath(props.modelValue, path, (item) => {
    if (field === 'default' && value === '') {
      const { default: _default, ...rest } = item
      return rest
    }
    return { ...item, [field]: value }
  })
  emit('update:modelValue', next)
}

function add(location: ParameterLocation = filter.value === 'all' ? 'query' : filter.value) {
  emit('update:modelValue', [
    ...props.modelValue,
    { name: '', in: location, type: 'string', required: location === 'path', description: '', example: '' },
  ])
}

function addChild(path: number[]) {
  const next = updateAtPath(props.modelValue, path, (item) => {
    const children = childrenOf(item)
    let index = children.length + 1
    let name = `field${index}`
    while (children.some((child) => String(child.name || '') === name)) {
      index += 1
      name = `field${index}`
    }
    return withChildren(item, [
      ...children,
      { name, type: 'string', required: false, description: '', example: '' },
    ])
  })
  expanded.value = { ...expanded.value, [pathKey(path)]: true }
  emit('update:modelValue', next)
}

function remove(path: number[]) {
  emit('update:modelValue', removeAtPath(props.modelValue, path))
}

function inputValue(value: unknown) {
  if (value === null || value === undefined) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

defineExpose({ add })
</script>

<template>
  <div class="parameters-editor">
    <el-segmented v-model="filter" :options="filters" class="parameter-filters" />
    <div v-if="visibleItems.length" class="parameter-table" role="table" aria-label="请求参数列表">
      <div class="parameter-table-head" role="row">
        <span role="columnheader">位置</span>
        <span role="columnheader">参数名</span>
        <span role="columnheader">类型</span>
        <span role="columnheader">约束</span>
        <span role="columnheader">说明</span>
        <span role="columnheader">示例</span>
        <span role="columnheader">默认值</span>
        <span role="columnheader" aria-label="操作"></span>
      </div>
      <div class="parameter-list">
        <article
          v-for="row in visibleItems"
          :key="pathKey(row.path)"
          class="parameter-card"
          :class="{ 'is-path': row.location === 'path', 'is-child': row.depth > 0, 'is-object': isObjectParameter(row.item) }"
          role="row"
        >
          <div class="parameter-field parameter-location" role="cell">
            <span class="parameter-field-label">位置</span>
            <el-select
              v-if="row.depth === 0"
              :model-value="String(row.item.in || 'query')"
              aria-label="参数位置"
              @update:model-value="update(row.path, 'in', $event)"
            >
              <el-option label="Path" value="path" /><el-option label="Query" value="query" /><el-option label="Header" value="header" /><el-option label="Body" value="body" />
            </el-select>
            <span v-else class="parameter-inherited-location"><span aria-hidden="true">↳</span> {{ locationLabel(row.location) }}</span>
          </div>
          <div class="parameter-field parameter-name" :style="{ paddingLeft: `${row.depth * 18}px` }" role="cell">
            <span class="parameter-field-label">参数名</span>
            <el-input :model-value="String(row.item.name || '')" aria-label="参数名称" placeholder="参数名称" @update:model-value="update(row.path, 'name', $event)">
              <template #suffix><el-tag v-if="pathParams.includes(String(row.item.name))" type="warning" size="small">已识别</el-tag></template>
            </el-input>
          </div>
          <div class="parameter-field parameter-type" role="cell">
            <span class="parameter-field-label">类型</span>
            <el-select :model-value="String(row.item.type || 'string')" aria-label="参数类型" @update:model-value="update(row.path, 'type', $event)">
              <el-option v-for="type in ['string', 'integer', 'number', 'boolean', 'object', 'array']" :key="type" :label="type" :value="type" />
            </el-select>
          </div>
          <div class="parameter-field parameter-required" role="cell">
            <span class="parameter-field-label">约束</span>
            <el-checkbox :model-value="Boolean(row.item.required)" :disabled="row.location === 'path'" @update:model-value="update(row.path, 'required', $event)">必填</el-checkbox>
          </div>
          <div class="parameter-field parameter-description" role="cell">
            <span class="parameter-field-label">说明</span>
            <el-input :model-value="String(row.item.description || '')" aria-label="参数说明" placeholder="说明参数用途、约束或格式" @update:model-value="update(row.path, 'description', $event)" />
          </div>
          <div class="parameter-field parameter-example" role="cell">
            <span class="parameter-field-label">示例</span>
            <el-input :model-value="inputValue(row.item.example)" aria-label="参数示例" placeholder="示例值" @update:model-value="update(row.path, 'example', $event)" />
          </div>
          <div class="parameter-field parameter-default" role="cell">
            <span class="parameter-field-label">默认值</span>
            <el-input :model-value="inputValue(row.item.default)" aria-label="参数默认值" placeholder="未设置" @update:model-value="update(row.path, 'default', $event)" />
          </div>
          <div class="parameter-actions" role="cell">
            <el-button
              v-if="isObjectParameter(row.item)"
              text
              type="primary"
              class="parameter-children-toggle"
              :icon="isExpanded(row.path, row.item) ? ArrowDown : ArrowRight"
              :aria-label="`${isExpanded(row.path, row.item) ? '收起' : '展开'}子参数`"
              @click="toggleExpanded(row.path, row.item)"
            >
              <span>{{ childrenOf(row.item).length }}</span>
            </el-button>
            <el-button v-if="isObjectParameter(row.item)" text type="primary" :icon="Plus" aria-label="添加子参数" @click="addChild(row.path)" />
            <el-button text type="danger" :icon="Delete" aria-label="删除参数" @click="remove(row.path)" />
          </div>
        </article>
      </div>
    </div>
    <div v-else class="editor-empty"><strong>还没有{{ filter === 'all' ? '' : ` ${locationLabel(filter)}` }}参数</strong><span>点击“添加参数”建立可读的 API 参数文档。</span></div>
  </div>
</template>
