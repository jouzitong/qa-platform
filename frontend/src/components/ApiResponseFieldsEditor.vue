<script setup lang="ts">
import { Delete, Plus } from '@element-plus/icons-vue'
import { computed } from 'vue'

type JsonSchema = Record<string, unknown>

const props = defineProps<{ modelValue: JsonSchema }>()
const emit = defineEmits<{ 'update:modelValue': [value: JsonSchema] }>()

const schema = computed<JsonSchema>(() => (
  props.modelValue && typeof props.modelValue === 'object' && !Array.isArray(props.modelValue)
    ? props.modelValue
    : { type: 'object', properties: {}, required: [] }
))
const properties = computed<JsonSchema>(() => (
  schema.value.properties && typeof schema.value.properties === 'object'
    && !Array.isArray(schema.value.properties)
    ? schema.value.properties as JsonSchema
    : {}
))
const required = computed(() => (
  Array.isArray(schema.value.required)
    ? schema.value.required.map((value) => String(value))
    : []
))
const fields = computed(() => Object.entries(properties.value))

function updateSchema(patch: JsonSchema) {
  emit('update:modelValue', { ...schema.value, type: 'object', properties: properties.value, ...patch })
}

function updateField(oldName: string, patch: JsonSchema) {
  const nextProperties = { ...properties.value }
  const nextName = String(patch.name || oldName).trim()
  delete patch.name
  delete nextProperties[oldName]
  if (nextName) nextProperties[nextName] = { ...properties.value[oldName] as JsonSchema, ...patch }

  const nextRequired = required.value
    .filter((name) => name !== oldName)
  if (Boolean(patch.required)) nextRequired.push(nextName)
  else if (required.value.includes(oldName) && nextName !== oldName) nextRequired.push(nextName)

  updateSchema({ properties: nextProperties, required: [...new Set(nextRequired)] })
}

function setField(oldName: string, field: string, value: unknown) {
  const current = properties.value[oldName]
  const property: JsonSchema = current && typeof current === 'object' && !Array.isArray(current)
    ? { ...(current as JsonSchema) }
    : { type: 'string' }
  if (field === 'required') {
    const nextRequired = new Set(required.value)
    if (value) nextRequired.add(oldName)
    else nextRequired.delete(oldName)
    updateSchema({ required: [...nextRequired] })
    return
  }
  if (field === 'name') {
    updateField(oldName, { name: value, required: required.value.includes(oldName) })
    return
  }
  if (field === 'example' && value === '') delete property.example
  else property[field] = value
  updateSchema({ properties: { ...properties.value, [oldName]: property } })
}

function addField() {
  let index = fields.value.length + 1
  let name = `field${index}`
  while (Object.prototype.hasOwnProperty.call(properties.value, name)) {
    index += 1
    name = `field${index}`
  }
  updateSchema({
    properties: { ...properties.value, [name]: { type: 'string', description: '' } },
  })
}

function removeField(name: string) {
  const nextProperties = { ...properties.value }
  delete nextProperties[name]
  updateSchema({
    properties: nextProperties,
    required: required.value.filter((item) => item !== name),
  })
}

function fieldValue(field: JsonSchema, key: string) {
  const value = field[key]
  return value === null || value === undefined ? '' : String(value)
}
</script>

<template>
  <div class="response-fields-editor">
    <div class="editor-mode-bar response-fields-toolbar">
      <div>
        <strong>响应字段</strong>
        <p class="muted">独立维护响应体字段的类型、必填约束、说明和示例；结构会同步到成功响应 Schema。</p>
      </div>
      <el-button type="primary" plain :icon="Plus" @click="addField">添加字段</el-button>
    </div>
    <div v-if="fields.length" class="response-field-list">
      <article v-for="([name, field]) in fields" :key="name" class="response-field-card">
        <div class="response-field-main">
          <label class="response-field-control response-field-name">
            <span>字段名</span>
            <el-input :model-value="name" placeholder="例如：id" @update:model-value="setField(name, 'name', $event)" />
          </label>
          <label class="response-field-control response-field-type">
            <span>类型</span>
            <el-select :model-value="fieldValue((field || {}) as JsonSchema, 'type') || 'string'" @update:model-value="setField(name, 'type', $event)">
              <el-option v-for="type in ['string', 'integer', 'number', 'boolean', 'object', 'array']" :key="type" :label="type" :value="type" />
            </el-select>
          </label>
          <label class="response-field-control response-field-example">
            <span>示例</span>
            <el-input :model-value="fieldValue((field || {}) as JsonSchema, 'example')" placeholder="示例值" @update:model-value="setField(name, 'example', $event)" />
          </label>
          <label class="response-field-required">
            <span>约束</span>
            <el-checkbox :model-value="required.includes(name)" @update:model-value="setField(name, 'required', $event)">必填</el-checkbox>
          </label>
          <el-button text type="danger" :icon="Delete" aria-label="删除响应字段" @click="removeField(name)" />
        </div>
        <label class="response-field-control response-field-description">
          <span>字段说明</span>
          <el-input :model-value="fieldValue((field || {}) as JsonSchema, 'description')" placeholder="说明字段用途、格式或业务含义" @update:model-value="setField(name, 'description', $event)" />
        </label>
      </article>
    </div>
    <div v-else class="response-fields-empty">
      <strong>还没有响应字段</strong>
      <span>添加字段后，系统会生成对应的 JSON Schema。</span>
      <el-button type="primary" plain :icon="Plus" @click="addField">添加第一个字段</el-button>
    </div>
  </div>
</template>
