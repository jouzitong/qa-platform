<script setup lang="ts">
import { Delete, Plus } from '@element-plus/icons-vue'
import { computed, ref, watch } from 'vue'

import { pretty } from '../utils'

const props = defineProps<{
  modelValue: string
  protocol: 'http' | 'ws'
}>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()

const fixedValuesOpen = ref<string[]>([])
const messagesDraft = ref('[]')
const messagesError = ref('')

const config = computed<Record<string, unknown>>(() => {
  try { return JSON.parse(props.modelValue) as Record<string, unknown> }
  catch { return {} }
})
watch(
  () => props.modelValue,
  () => { messagesDraft.value = pretty(config.value.messages ?? []) },
  { immediate: true },
)

function updateConfig(patch: Record<string, unknown>) {
  emit('update:modelValue', pretty({ ...config.value, ...patch }))
}

function mapEntries(field: 'headers' | 'query') {
  const value = config.value[field]
  if (!value || typeof value !== 'object' || Array.isArray(value)) return []
  return Object.entries(value as Record<string, unknown>)
}

const fixedHeaderCount = computed(() => mapEntries('headers').length)
const fixedQueryCount = computed(() => mapEntries('query').length)

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

</script>

<template>
  <div class="request-editor">
    <div v-if="protocol === 'ws'" class="editor-mode-bar api-request-toolbar">
      <div>
        <strong>消息配置</strong>
        <p class="muted">设置连接后的接收数量与发送消息；连接地址在上方“接口信息”中维护。</p>
      </div>
    </div>

    <template v-if="protocol === 'http'">
        <el-collapse v-model="fixedValuesOpen" class="fixed-values-collapse">
          <el-collapse-item name="fixed-values">
            <template #title>
              <div class="fixed-values-title">
                <strong>固定请求值</strong>
                <span>Headers {{ fixedHeaderCount }} · Query {{ fixedQueryCount }}</span>
                <small>每次请求保持不变的字段，可选</small>
              </div>
            </template>
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
          </el-collapse-item>
        </el-collapse>
        <p class="request-values-hint">动态 Query、Header 和 Body 参数请在下方“运行参数契约”维护；这里仅保留固定值。</p>
    </template>

    <template v-else>
      <el-form-item label="接收消息数量"><el-input-number :model-value="Number(config.receive_count || 1)" :min="1" @update:model-value="updateConfig({ receive_count: $event })" /></el-form-item>
      <section class="request-section body-section">
        <div class="section-heading"><div><strong>发送消息</strong><span>JSON 数组</span></div><el-button text type="primary" @click="applyJsonDraft(messagesDraft, 'messages', (value) => messagesError = value)">应用修改</el-button></div>
        <el-input v-model="messagesDraft" class="json-input" type="textarea" :rows="9" @blur="applyJsonDraft(messagesDraft, 'messages', (value) => messagesError = value)" />
        <p v-if="messagesError" class="field-error">{{ messagesError }}</p>
      </section>
    </template>
  </div>
</template>
