<script setup lang="ts">
const pageSizes = [10, 20, 50, 100, 200, 500]

defineProps<{
  total: number
  page: number
  pageSize: number
}>()

const emit = defineEmits<{
  'update:page': [value: number]
  'update:pageSize': [value: number]
}>()

function changePageSize(value: number) {
  emit('update:pageSize', value)
  emit('update:page', 1)
}
</script>

<template>
  <div v-if="total" class="pagination-bar">
    <span class="pagination-total">共 {{ total }} 条</span>
    <el-pagination
      background
      layout="prev, pager, next, sizes"
      :current-page="page"
      :page-size="pageSize"
      :page-sizes="pageSizes"
      :total="total"
      @current-change="emit('update:page', $event)"
      @size-change="changePageSize"
    />
  </div>
</template>
