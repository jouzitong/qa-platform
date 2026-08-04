<script setup lang="ts">
import { Delete, Plus } from '@element-plus/icons-vue'
import { computed, ref, watch } from 'vue'

import { pretty } from '../utils'

const props = defineProps<{
  modelValue: string
  protocol: 'http' | 'ws'
  inheritedRequest?: Record<string, unknown>
}>()
const emit = defineEmits<{
  'update:modelValue': [value: string]
  'path-params': [names: string[]]
}>()

const mode = ref<'visual' | 'json'>('visual')
const rawDraft = ref(props.modelValue)
const messagesDraft = ref('[]')
const messagesError = ref('')

const config = computed<Record<string, unknown>>(() => {
  try { return JSON.parse(props.modelValue) as Record<string, unknown> }
  catch { return {} }
})
const endpoint = computed(() => String(
  config.value.url || config.value.path || '',
))
const usesTemplateBase = computed(() => Boolean(
  props.inheritedRequest?.base_url || props.inheritedRequest?.url,
))
const inheritedBase = computed(() => String(
  props.inheritedRequest?.base_url || props.inheritedRequest?.url || '',
))
const pathParams = computed(() => {
  const value = endpoint.value.replace(/\{\{[^}]+}}/g, '')
  const names = new Set<string>()
  for (const match of value.matchAll(/\{([A-Za-z_][A-Za-z0-9_]*)}/g)) names.add(match[1])
  for (const match of value.matchAll(/(?:^|\/)\:([A-Za-z_][A-Za-z0-9_]*)/g)) names.add(match[1])
  return [...names]
})
const effectivePreview = computed(() => {
  if (config.value.url) return String(config.value.url)
  const base = String(props.inheritedRequest?.base_url || config.value.base_url || '')
  const path = String(config.value.path || '')
  if (!base) return path || '尚未填写请求地址'
  return `${base.replace(/\/$/, '')}/${path.replace(/^\//, '')}`
})

watch(
  () => props.modelValue,
  (value) => {
    rawDraft.value = value
    messagesDraft.value = pretty(config.value.messages ?? [])
  },
  { immediate: true },
)
watch(pathParams, (value) => emit('path-params', value), { immediate: true })

function updateConfig(patch: Record<string, unknown>) {
  emit('update:modelValue', pretty({ ...config.value, ...patch }))
}

function updateEndpoint(value: string) {
  if (usesTemplateBase.value) {
    const { url: _url, ...rest } = config.value
    emit('update:modelValue', pretty({ ...rest, path: value }))
  } else {
    const { path: _path, ...rest } = config.value
    emit('update:modelValue', pretty({ ...rest, url: value }))
  }
}

function mapEntries(field: 'headers' | 'query') {
  const value = config.value[field]
  if (!value || typeof value !== 'object' || Array.isArray(value)) return []
  return Object.entries(value as Record<string, unknown>)
}

function updateMapEntry(
  field: 'headers' | 'query', oldKey: string, newKey: string, value: unknown,
) {
  const next = Object.fromEntries(mapEntries(field))
  delete next[oldKey]
  if (newKey.trim()) next[newKey] = value
  updateConfig({ [field]: next })
}

function addMapEntry(field: 'headers' | 'query') {
  const next = Object.fromEntries(mapEntries(field))
  let index = Object.keys(next).length + 1
  let key = field === 'headers' ? `X-Header-${index}` : `param${index}`
  while (key in next) {
    index += 1
    key = field === 'headers' ? `X-Header-${index}` : `param${index}`
  }
  next[key] = ''
  updateConfig({ [field]: next })
}

function applyJsonDraft(draft: string, field: 'messages', setError: (message: string) => void) {
  try {
    updateConfig({ [field]: JSON.parse(draft) })
    setError('')
  } catch { setError('消息列表不是有效的 JSON') }
}

function applyRaw() {
  try {
    const parsed = JSON.parse(rawDraft.value) as Record<string, unknown>
    emit('update:modelValue', pretty(parsed))
    mode.value = 'visual'
  } catch { /* Parent save still reports invalid JSON; keep draft available for correction. */ }
}
</script>

<template>
  <div class="request-editor">
    <div class="editor-mode-bar">
      <div>
        <strong>请求构建器</strong>
        <p class="muted">填写路径时使用 <code>{id}</code> 声明 Path 参数，参数默认值在下方 Parameters 中维护。</p>
      </div>
      <el-segmented v-model="mode" :options="[{ label: '可视化', value: 'visual' }, { label: '高级 JSON', value: 'json' }]" />
    </div>

    <template v-if="mode === 'visual'">
      <template v-if="protocol === 'http'">
        <div class="endpoint-builder">
          <el-select :model-value="String(config.method || 'GET')" aria-label="请求方法" style="width: 118px" @update:model-value="updateConfig({ method: $event })">
            <el-option v-for="method in ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD']" :key="method" :label="method" :value="method" />
          </el-select>
          <div v-if="usesTemplateBase" class="base-url-prefix" :title="inheritedBase">{{ inheritedBase }}</div>
          <el-input :model-value="endpoint" :placeholder="usesTemplateBase ? '/users/{user_id}/orders/{order_id}' : '{{ base_url }}/users/{user_id}'" aria-label="请求地址" @update:model-value="updateEndpoint" />
        </div>
        <div class="endpoint-preview">
          <span>最终地址</span><code>{{ effectivePreview }}</code>
        </div>
        <div v-if="pathParams.length" class="path-param-hint">
          <strong>已识别 Path 参数</strong>
          <el-tag v-for="name in pathParams" :key="name" type="warning" effect="plain">{{ name }}</el-tag>
          <span>运行时可通过流程上下文的同名变量渲染。</span>
        </div>

        <div class="request-grid">
          <section class="request-section">
            <div class="section-heading"><div><strong>请求头</strong><span>{{ mapEntries('headers').length }} 项</span></div><el-button text type="primary" :icon="Plus" @click="addMapEntry('headers')">添加</el-button></div>
            <div v-for="([key, value]) in mapEntries('headers')" :key="key" class="key-value-row">
              <el-input :model-value="key" aria-label="请求头名称" @update:model-value="updateMapEntry('headers', key, $event, value)" />
              <el-input :model-value="String(value ?? '')" aria-label="请求头值" placeholder="支持 {{ variable }}" @update:model-value="updateMapEntry('headers', key, key, $event)" />
              <el-button text type="danger" :icon="Delete" aria-label="删除请求头" @click="updateMapEntry('headers', key, '', value)" />
            </div>
            <div v-if="!mapEntries('headers').length" class="mini-empty">暂无 API 专属请求头，将继续继承模板配置。</div>
          </section>
          <section class="request-section">
            <div class="section-heading"><div><strong>Query 参数值</strong><span>{{ mapEntries('query').length }} 项</span></div><el-button text type="primary" :icon="Plus" @click="addMapEntry('query')">添加</el-button></div>
            <div v-for="([key, value]) in mapEntries('query')" :key="key" class="key-value-row">
              <el-input :model-value="key" aria-label="Query 名称" @update:model-value="updateMapEntry('query', key, $event, value)" />
              <el-input :model-value="String(value ?? '')" aria-label="Query 值" placeholder="例如 {{ page }}" @update:model-value="updateMapEntry('query', key, key, $event)" />
              <el-button text type="danger" :icon="Delete" aria-label="删除 Query" @click="updateMapEntry('query', key, '', value)" />
            </div>
            <div v-if="!mapEntries('query').length" class="mini-empty">暂无 Query 参数值。</div>
          </section>
        </div>

        <p class="parameter-source-notice">请求体参数请在下方 Parameters 中定义；调用时会按参数位置组装请求，并自动使用默认值。</p>
      </template>

      <template v-else>
        <el-form-item label="WebSocket 地址"><el-input :model-value="String(config.url || config.path || '')" placeholder="wss://example.com/ws/{channel}" @update:model-value="updateEndpoint" /></el-form-item>
        <el-form-item label="接收消息数量"><el-input-number :model-value="Number(config.receive_count || 1)" :min="1" @update:model-value="updateConfig({ receive_count: $event })" /></el-form-item>
        <section class="request-section body-section">
          <div class="section-heading"><div><strong>发送消息</strong><span>JSON 数组</span></div><el-button text type="primary" @click="applyJsonDraft(messagesDraft, 'messages', (value) => messagesError = value)">应用修改</el-button></div>
          <el-input v-model="messagesDraft" class="json-input" type="textarea" :rows="9" @blur="applyJsonDraft(messagesDraft, 'messages', (value) => messagesError = value)" />
          <p v-if="messagesError" class="field-error">{{ messagesError }}</p>
        </section>
      </template>
    </template>

    <div v-else class="advanced-json">
      <el-alert title="高级模式会直接编辑完整请求覆盖配置" description="适合配置超时或暂未可视化的扩展字段；HTTP 非成功状态仍由 API 成功契约判定为失败。" type="info" :closable="false" show-icon />
      <el-input v-model="rawDraft" class="json-input" type="textarea" :rows="18" aria-label="高级请求 JSON" />
      <el-button type="primary" plain @click="applyRaw">应用 JSON</el-button>
    </div>
  </div>
</template>
