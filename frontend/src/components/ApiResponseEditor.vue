<script setup lang="ts">
import { Refresh } from '@element-plus/icons-vue'
import { computed, ref, watch } from 'vue'

import { pretty } from '../utils'

type SuccessContract = Record<string, unknown>

const props = defineProps<{ modelValue: SuccessContract }>()
const emit = defineEmits<{ 'update:modelValue': [value: SuccessContract] }>()

const schemaDraft = ref('{}')
const schemaError = ref('')
const rawDraft = ref('{}')
const rawError = ref('')
const mode = ref<'visual' | 'json'>('visual')

const statusCodes = computed<Record<string, unknown>>(() => {
  const value = props.modelValue.status_codes
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : { min: 200, max: 299 }
})
const minimumStatus = computed(() => Number(statusCodes.value.min ?? 200))
const maximumStatus = computed(() => Number(statusCodes.value.max ?? 299))
const bodySchema = computed(() => {
  const value = props.modelValue.body_schema
  return value && typeof value === 'object' ? value : {}
})
const isHttpContract = computed(() => Object.prototype.hasOwnProperty.call(props.modelValue, 'status_codes'))
const bodySchemaEnabled = computed(() => Object.keys(bodySchema.value).length > 0)
const minimumMessages = computed(() => {
  const value = props.modelValue.messages
  return value && typeof value === 'object' && !Array.isArray(value)
    ? Number((value as Record<string, unknown>).min || 1)
    : 1
})

watch(
  () => props.modelValue,
  (value) => {
    schemaDraft.value = pretty(value.body_schema || {})
    rawDraft.value = pretty(value)
  },
  { deep: true, immediate: true },
)

function update(patch: SuccessContract) {
  emit('update:modelValue', { ...props.modelValue, ...patch })
}

function updateStatus(field: 'min' | 'max', value: number | undefined) {
  update({ status_codes: { ...statusCodes.value, [field]: value || (field === 'min' ? 200 : 299) } })
}

function applySchema() {
  try {
    const schema = JSON.parse(schemaDraft.value)
    if (!schema || typeof schema !== 'object' || Array.isArray(schema))
      throw new Error('成功响应 Schema 必须是 JSON 对象')
    update({ body_schema: schema })
    schemaError.value = ''
  } catch (error) { schemaError.value = (error as Error).message }
}

function toggleBodySchema(enabled: boolean) {
  update({ body_schema: enabled ? {
    type: 'object',
    required: ['code', 'data'],
    properties: { code: { const: 0 } },
  } : {} })
}

function resetCommonContract() {
  update({
    status_codes: { min: 200, max: 299 },
    body_schema: {
      type: 'object',
      required: ['code', 'data'],
      properties: { code: { const: 0 } },
    },
  })
}

function applyRaw() {
  try {
    const value = JSON.parse(rawDraft.value)
    if (!value || typeof value !== 'object' || Array.isArray(value))
      throw new Error('成功契约必须是 JSON 对象')
    emit('update:modelValue', value as SuccessContract)
    rawError.value = ''
    mode.value = 'visual'
  } catch (error) { rawError.value = (error as Error).message }
}
</script>

<template>
  <div class="success-contract-editor">
    <div class="editor-mode-bar success-contract-toolbar">
      <div>
        <strong>成功契约</strong>
        <p class="muted">只有状态码、响应体结构和成功断言全部满足时，API 才算通过；其他结果统一判定为失败。</p>
      </div>
      <div class="success-contract-actions">
        <el-segmented v-model="mode" :options="[{ label: '可视化', value: 'visual' }, { label: '高级 JSON', value: 'json' }]" />
        <el-button text type="primary" :icon="Refresh" @click="resetCommonContract">恢复通用契约</el-button>
      </div>
    </div>

    <template v-if="mode === 'visual'">
      <div v-if="isHttpContract" class="success-contract-grid">
        <section class="success-rule-card">
          <div class="section-heading"><div><strong>HTTP 成功状态</strong><span>默认 200–299</span></div><el-tag type="success" effect="plain">必须满足</el-tag></div>
          <div class="status-range-inputs">
            <el-input-number :model-value="minimumStatus" :min="100" :max="599" controls-position="right" aria-label="成功状态码最小值" @update:model-value="updateStatus('min', $event)" />
            <span>至</span>
            <el-input-number :model-value="maximumStatus" :min="100" :max="599" controls-position="right" aria-label="成功状态码最大值" @update:model-value="updateStatus('max', $event)" />
          </div>
          <p class="muted">非此范围的 HTTP 响应直接判定为失败。</p>
        </section>
        <section class="success-rule-card">
          <div class="section-heading"><div><strong>响应体结构</strong><span>JSON Schema</span></div><el-switch :model-value="bodySchemaEnabled" active-text="启用" @update:model-value="toggleBodySchema" /></div>
          <el-input v-model="schemaDraft" class="json-input" type="textarea" :rows="7" aria-label="成功响应体 JSON Schema" @blur="applySchema" />
          <p v-if="schemaError" class="field-error">{{ schemaError }}</p>
          <p v-else class="muted">通用业务 API 默认要求 <code>code = 0</code>、存在 <code>data</code>。</p>
        </section>
      </div>
      <section v-else class="success-rule-card websocket-success-card">
        <div class="section-heading"><div><strong>WebSocket 成功消息</strong><span>至少收到指定数量的消息</span></div><el-tag type="success" effect="plain">必须满足</el-tag></div>
        <el-input-number :model-value="minimumMessages" :min="1" controls-position="right" aria-label="最少消息数" @update:model-value="update({ messages: { min: $event || 1 } })" />
      </section>
    </template>

    <div v-else class="advanced-json success-contract-json-editor">
      <el-alert title="高级模式维护完整成功契约" description="可编辑 status_codes、body_schema、messages 等字段；失败分支不需要配置。" type="info" :closable="false" show-icon />
      <el-input v-model="rawDraft" class="json-input" type="textarea" :rows="14" aria-label="成功契约 JSON" />
      <p v-if="rawError" class="field-error">{{ rawError }}</p>
      <el-button type="primary" plain @click="applyRaw">应用 JSON</el-button>
    </div>
  </div>
</template>
