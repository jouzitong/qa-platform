<script setup lang="ts">
import {
  ArrowRight,
  CircleCheck,
  Clock,
  Document,
  EditPen,
  List,
  Plus,
  Promotion,
  Search,
  SetUp,
  Tickets,
  View,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

type RequirementStatus = '待评审' | '开发中' | '待验收' | '已完成' | '已延期'

interface RequirementRow {
  id: string
  title: string
  type: string
  priority: '高' | '中' | '低'
  status: RequirementStatus
  owner: string
  release: string
  progress: number
  updatedAt: string
  description: string
  acceptance: string[]
}

const route = useRoute()
const router = useRouter()

const sections = [
  { key: 'requirements', path: '/requirements', label: '需求池', icon: Tickets },
  { key: 'prototypes', path: '/requirements/prototypes', label: '产品原型', icon: EditPen },
  { key: 'tasks', path: '/requirements/tasks', label: '开发任务', icon: SetUp },
  { key: 'releases', path: '/requirements/releases', label: '发布计划', icon: Promotion },
  { key: 'documents', path: '/requirements/documents', label: '交付文档', icon: Document },
]

const activeSection = computed(() => (
  sections.find((section) => section.path === route.path) || sections[0]
))

const requirements = ref<RequirementRow[]>([
  {
    id: 'REQ-001',
    title: '支持项目资产导入审批',
    type: '平台能力',
    priority: '高',
    status: '开发中',
    owner: '张三',
    release: '2026.08 平台迭代',
    progress: 68,
    updatedAt: '今天 10:24',
    description: '导入项目、API、断言和测试计划时，先生成差异预览，再由人工审批后生效。',
    acceptance: ['预览阶段不修改业务数据', '支持新增、更新、不变和错误分类', '审批通过后事务性生效'],
  },
  {
    id: 'REQ-002',
    title: '测试计划关联发布流程',
    type: '测试管理',
    priority: '高',
    status: '待验收',
    owner: '李四',
    release: '2026.08 平台迭代',
    progress: 92,
    updatedAt: '昨天 17:40',
    description: '发布计划可以关联多个需求，并在发布前执行对应的测试计划。',
    acceptance: ['发布计划展示测试结果', '需求延期时阻止直接发布', '支持生成升级和回退手册'],
  },
  {
    id: 'REQ-003',
    title: '执行记录增加失败分析',
    type: '质量保障',
    priority: '中',
    status: '已完成',
    owner: '王五',
    release: '2026.07 稳定版',
    progress: 100,
    updatedAt: '2026/07/28',
    description: '将断言失败、请求快照和响应快照集中展示，帮助快速定位问题。',
    acceptance: ['展示失败断言', '保留请求和响应快照', '支持查看单步执行详情'],
  },
])

const taskRows = [
  { id: 'TASK-104', title: '设计导入包差异模型', requirement: 'REQ-001', type: '设计', owner: '张三', status: '已完成', progress: 100, due: '08/02' },
  { id: 'TASK-105', title: '实现审批确认接口', requirement: 'REQ-001', type: '后端', owner: '张三', status: '开发中', progress: 68, due: '08/06' },
  { id: 'TASK-106', title: '补充发布前测试检查', requirement: 'REQ-002', type: '前端', owner: '李四', status: '待验收', progress: 92, due: '08/05' },
  { id: 'TASK-107', title: '更新回退操作手册', requirement: 'REQ-002', type: '文档', owner: '王五', status: '未开始', progress: 0, due: '08/07' },
]

const prototypeCards = [
  { id: 'PRO-001', title: '导入审批工作台', requirement: 'REQ-001', status: '评审中', owner: '产品组', updatedAt: '今天 09:30', sections: ['上传导入包', '差异预览', '人工确认'] },
  { id: 'PRO-002', title: '发布计划详情', requirement: 'REQ-002', status: '已确认', owner: '产品组', updatedAt: '昨天 16:12', sections: ['关联需求', '发布前检查', '升级/回退文档'] },
  { id: 'PRO-003', title: '失败分析详情', requirement: 'REQ-003', status: '已归档', owner: '产品组', updatedAt: '07/26', sections: ['执行概览', '断言结果', '原始快照'] },
]

const releasePlans = [
  { id: 'REL-2026-08', name: '2026.08 平台迭代', version: 'v0.2.0', status: '准备中', owner: '项目组', window: '08/12 20:00 - 21:00', requirements: 2, done: 1, test: '待执行', readiness: 76 },
  { id: 'REL-2026-07', name: '2026.07 稳定版', version: 'v0.1.1', status: '已发布', owner: '项目组', window: '07/30 20:00 - 21:00', requirements: 1, done: 1, test: '通过', readiness: 100 },
]

const documents = [
  { name: '2026.08 平台迭代升级计划', type: '升级计划', release: '2026.08 平台迭代', status: '草稿', updatedAt: '今天 11:05', format: 'Markdown' },
  { name: '2026.08 平台迭代操作手册', type: '操作手册', release: '2026.08 平台迭代', status: '待生成', updatedAt: '-', format: 'Markdown' },
  { name: '2026.08 平台迭代回退手册', type: '回退手册', release: '2026.08 平台迭代', status: '待生成', updatedAt: '-', format: 'Markdown' },
  { name: '稳定版发布脚本', type: '发布脚本', release: '2026.07 稳定版', status: '已归档', updatedAt: '07/30 18:20', format: 'Shell' },
]

const requirementStatus = ref<'全部' | RequirementStatus>('全部')
const requirementKeyword = ref('')
const selectedRequirement = ref<RequirementRow | null>(null)
const createDialogVisible = ref(false)
const createForm = reactive({ title: '', type: '平台能力', priority: '中' as RequirementRow['priority'], owner: '我', description: '' })

const filteredRequirements = computed(() => requirements.value.filter((item) => {
  const matchesStatus = requirementStatus.value === '全部' || item.status === requirementStatus.value
  const keyword = requirementKeyword.value.trim().toLowerCase()
  const matchesKeyword = !keyword || `${item.id} ${item.title} ${item.owner}`.toLowerCase().includes(keyword)
  return matchesStatus && matchesKeyword
}))

const openCreateDialog = () => {
  Object.assign(createForm, { title: '', type: '平台能力', priority: '中', owner: '我', description: '' })
  createDialogVisible.value = true
}

const createRequirement = () => {
  if (!createForm.title.trim()) {
    ElMessage.warning('请填写需求名称')
    return
  }
  requirements.value.unshift({
    id: `REQ-${String(requirements.value.length + 1).padStart(3, '0')}`,
    title: createForm.title.trim(), type: createForm.type, priority: createForm.priority,
    status: '待评审', owner: createForm.owner || '未分配', release: '未关联发布计划', progress: 0,
    updatedAt: '刚刚', description: createForm.description || '暂无需求描述',
    acceptance: ['待补充验收标准'],
  })
  createDialogVisible.value = false
  ElMessage.success('需求已加入原型列表（当前为前端演示数据）')
}

const navigate = (path: string) => { void router.push(path) }
const selectRequirement = (row: RequirementRow) => { selectedRequirement.value = row }
const statusType = (status: string) => {
  if (['已完成', '已发布', '已确认', '通过'].includes(status)) return 'success'
  if (['开发中', '准备中', '评审中', '待验收', '草稿'].includes(status)) return 'warning'
  if (['已延期', '阻塞'].includes(status)) return 'danger'
  return 'info'
}
</script>

<template>
  <div class="requirement-page">
    <div class="page-head requirement-page-head">
      <div>
        <p class="eyebrow">PRODUCT DELIVERY</p>
        <h2>{{ activeSection.label }}</h2>
        <p>围绕需求、开发、测试、验收和发布，建立一条可追踪的项目交付链路。</p>
      </div>
      <div class="requirement-head-actions">
        <el-tag type="info" effect="plain">前端原型</el-tag>
        <el-button v-if="activeSection.key === 'requirements'" type="primary" :icon="Plus" @click="openCreateDialog">新建需求</el-button>
        <el-button v-else-if="activeSection.key === 'releases'" type="primary" :icon="Plus" @click="ElMessage.info('发布计划页面暂为原型')">新建发布计划</el-button>
        <el-button v-else :icon="View" @click="navigate('/requirements')">查看需求池</el-button>
      </div>
    </div>

    <el-card class="panel requirement-flow-card" shadow="never">
      <div class="requirement-flow-heading">
        <div>
          <strong>项目交付流程</strong>
          <span>需求状态决定是否可以进入发布计划，发布计划统一承载上线动作。</span>
        </div>
        <el-tag type="success" effect="plain">流程原型</el-tag>
      </div>
      <div class="requirement-flow">
        <div v-for="(step, index) in ['需求', '原型', '开发', '测试', '验收', '发布']" :key="step" class="requirement-flow-step">
          <span class="requirement-flow-index">{{ index + 1 }}</span>
          <strong>{{ step }}</strong>
          <el-icon v-if="index < 5"><ArrowRight /></el-icon>
        </div>
      </div>
    </el-card>

    <div class="requirement-metrics">
      <div class="stat-card"><span class="stat-label">需求总数</span><strong class="stat-value">{{ requirements.length }}</strong><small>持续跟踪</small></div>
      <div class="stat-card"><span class="stat-label">开发中</span><strong class="stat-value stat-warning">{{ requirements.filter((item) => item.status === '开发中').length }}</strong><small>需要关注进度</small></div>
      <div class="stat-card"><span class="stat-label">待验收</span><strong class="stat-value stat-info">{{ requirements.filter((item) => item.status === '待验收').length }}</strong><small>准备验证结果</small></div>
      <div class="stat-card"><span class="stat-label">准备中发布</span><strong class="stat-value stat-accent">{{ releasePlans.filter((item) => item.status === '准备中').length }}</strong><small>发布计划驱动</small></div>
    </div>

    <template v-if="activeSection.key === 'requirements'">
      <el-card class="panel" shadow="never">
        <template #header>
          <div class="requirement-card-heading"><div><strong>需求池</strong><span>统一管理需求定义、优先级、负责人和交付状态</span></div><el-tag type="info" effect="plain">{{ filteredRequirements.length }} 条</el-tag></div>
        </template>
        <div class="requirement-toolbar">
          <el-input v-model="requirementKeyword" clearable placeholder="搜索需求编号、名称或负责人" :prefix-icon="Search" />
          <el-radio-group v-model="requirementStatus" size="small">
            <el-radio-button v-for="status in ['全部', '待评审', '开发中', '待验收', '已完成', '已延期']" :key="status" :label="status">{{ status }}</el-radio-button>
          </el-radio-group>
        </div>
        <el-table class="list-table requirement-table" :data="filteredRequirements" row-key="id" @row-click="selectRequirement">
          <el-table-column prop="id" label="编号" width="110" align="center" />
          <el-table-column label="需求名称" min-width="260"><template #default="scope"><div class="requirement-name-cell"><strong>{{ scope.row.title }}</strong><small>{{ scope.row.type }}</small></div></template></el-table-column>
          <el-table-column prop="priority" label="优先级" width="90" align="center"><template #default="scope"><el-tag :type="scope.row.priority === '高' ? 'danger' : scope.row.priority === '中' ? 'warning' : 'info'" size="small" effect="plain">{{ scope.row.priority }}</el-tag></template></el-table-column>
          <el-table-column prop="status" label="状态" width="110" align="center"><template #default="scope"><el-tag :type="statusType(scope.row.status)" size="small" effect="plain">{{ scope.row.status }}</el-tag></template></el-table-column>
          <el-table-column prop="owner" label="负责人" width="100" align="center" />
          <el-table-column label="完成度" width="150" align="center"><template #default="scope"><el-progress :percentage="scope.row.progress" :stroke-width="7" :show-text="false" /><small class="progress-text">{{ scope.row.progress }}%</small></template></el-table-column>
          <el-table-column prop="release" label="发布计划" min-width="180" />
          <el-table-column label="操作" width="90" fixed="right" align="center"><template #default="scope"><el-button link type="primary" :icon="View" @click.stop="selectedRequirement = scope.row">详情</el-button></template></el-table-column>
        </el-table>
      </el-card>
    </template>

    <template v-else-if="activeSection.key === 'prototypes'">
      <div class="prototype-grid">
        <el-card v-for="prototype in prototypeCards" :key="prototype.id" class="panel prototype-card" shadow="never">
          <div class="prototype-card-head"><div class="prototype-icon"><el-icon><EditPen /></el-icon></div><el-tag :type="statusType(prototype.status)" size="small" effect="plain">{{ prototype.status }}</el-tag></div>
          <h3>{{ prototype.title }}</h3><p>{{ prototype.id }} · {{ prototype.requirement }}</p>
          <div class="prototype-canvas"><div class="prototype-canvas-bar" /><div class="prototype-canvas-line short" /><div class="prototype-canvas-line" /><div class="prototype-canvas-blocks"><i /><i /><i /></div></div>
          <div class="prototype-meta"><span>{{ prototype.owner }}</span><span>{{ prototype.updatedAt }}</span></div>
          <div class="prototype-sections"><el-tag v-for="item in prototype.sections" :key="item" size="small" effect="plain">{{ item }}</el-tag></div>
          <el-button class="prototype-action" text type="primary" :icon="View" @click="ElMessage.info('原型详情将在后端接入后开放')">查看原型</el-button>
        </el-card>
      </div>
    </template>

    <template v-else-if="activeSection.key === 'tasks'">
      <el-card class="panel" shadow="never">
        <template #header><div class="requirement-card-heading"><div><strong>开发任务</strong><span>需求拆解后的开发、测试和文档任务</span></div><el-button :icon="Plus" @click="ElMessage.info('任务创建将在后端接入后开放')">新建任务</el-button></div></template>
        <el-table class="list-table" :data="taskRows">
          <el-table-column prop="id" label="任务编号" width="120" align="center" /><el-table-column prop="title" label="任务名称" min-width="260" />
          <el-table-column prop="requirement" label="关联需求" width="120" align="center" /><el-table-column prop="type" label="类型" width="90" align="center" />
          <el-table-column prop="owner" label="负责人" width="100" align="center" /><el-table-column prop="status" label="状态" width="110" align="center"><template #default="scope"><el-tag :type="statusType(scope.row.status)" size="small" effect="plain">{{ scope.row.status }}</el-tag></template></el-table-column>
          <el-table-column label="进度" width="150" align="center"><template #default="scope"><el-progress :percentage="scope.row.progress" :stroke-width="7" :show-text="false" /><small class="progress-text">{{ scope.row.progress }}%</small></template></el-table-column>
          <el-table-column prop="due" label="截止日期" width="120" align="center" /><el-table-column label="操作" fixed="right" width="90" align="center"><template #default><el-button link type="primary" :icon="View" @click="ElMessage.info('任务详情将在后端接入后开放')">详情</el-button></template></el-table-column>
        </el-table>
      </el-card>
    </template>

    <template v-else-if="activeSection.key === 'releases'">
      <div class="release-grid">
        <el-card v-for="release in releasePlans" :key="release.id" class="panel release-card" shadow="never">
          <div class="release-card-head"><div><p class="eyebrow">{{ release.id }}</p><h3>{{ release.name }}</h3><span>{{ release.version }} · {{ release.window }}</span></div><el-tag :type="statusType(release.status)" effect="plain">{{ release.status }}</el-tag></div>
          <div class="release-readiness"><div><span>发布就绪度</span><strong>{{ release.readiness }}%</strong></div><el-progress :percentage="release.readiness" :stroke-width="8" :show-text="false" status="success" /></div>
          <div class="release-facts"><div><small>关联需求</small><strong>{{ release.done }} / {{ release.requirements }} 已完成</strong></div><div><small>发布前测试</small><strong>{{ release.test }}</strong></div><div><small>负责人</small><strong>{{ release.owner }}</strong></div></div>
          <div class="release-card-actions"><el-button text type="primary" :icon="View" @click="ElMessage.info('发布计划详情将在后端接入后开放')">查看详情</el-button><el-button text :icon="Document" @click="navigate('/requirements/documents')">交付文档</el-button></div>
        </el-card>
      </div>
    </template>

    <template v-else>
      <el-card class="panel" shadow="never">
        <template #header><div class="requirement-card-heading"><div><strong>交付文档与脚本</strong><span>发布前生成并审核升级、操作和回退材料</span></div><el-button type="primary" :icon="Document" @click="ElMessage.info('文档生成将在后端接入后开放')">生成文档</el-button></div></template>
        <el-table class="list-table" :data="documents">
          <el-table-column label="文档名称" min-width="280"><template #default="scope"><div class="document-name-cell"><div class="document-icon"><el-icon><Document /></el-icon></div><div><strong>{{ scope.row.name }}</strong><small>{{ scope.row.format }}</small></div></div></template></el-table-column>
          <el-table-column prop="type" label="类型" width="120" align="center" /><el-table-column prop="release" label="发布计划" min-width="180" /><el-table-column prop="status" label="状态" width="110" align="center"><template #default="scope"><el-tag :type="statusType(scope.row.status)" size="small" effect="plain">{{ scope.row.status }}</el-tag></template></el-table-column>
          <el-table-column prop="updatedAt" label="更新时间" width="140" align="center" /><el-table-column label="操作" fixed="right" width="120" align="center"><template #default><el-button link type="primary" :icon="View" @click="ElMessage.info('文档预览将在后端接入后开放')">预览</el-button></template></el-table-column>
        </el-table>
      </el-card>
      <el-alert class="document-notice" title="发布计划是上线的唯一入口" type="info" :closable="false" show-icon>
        需求完成、延期或明确豁免后，才能进入发布计划的发布前检查；升级计划、操作手册、回退手册和脚本都应绑定到具体发布计划。
      </el-alert>
    </template>

    <el-drawer v-model="selectedRequirement" title="需求详情" size="520px">
      <template v-if="selectedRequirement">
        <div class="requirement-drawer-head"><div><p class="eyebrow">{{ selectedRequirement.id }}</p><h3>{{ selectedRequirement.title }}</h3><p>{{ selectedRequirement.description }}</p></div><el-tag :type="statusType(selectedRequirement.status)" effect="plain">{{ selectedRequirement.status }}</el-tag></div>
        <el-descriptions :column="1" border size="small"><el-descriptions-item label="需求类型">{{ selectedRequirement.type }}</el-descriptions-item><el-descriptions-item label="优先级">{{ selectedRequirement.priority }}</el-descriptions-item><el-descriptions-item label="负责人">{{ selectedRequirement.owner }}</el-descriptions-item><el-descriptions-item label="发布计划">{{ selectedRequirement.release }}</el-descriptions-item></el-descriptions>
        <div class="drawer-section"><div class="drawer-section-heading"><strong>交付状态</strong><span>{{ selectedRequirement.progress }}%</span></div><el-progress :percentage="selectedRequirement.progress" status="success" /></div>
        <div class="drawer-section"><div class="drawer-section-heading"><strong>验收标准</strong><el-tag size="small" effect="plain">{{ selectedRequirement.acceptance.length }} 项</el-tag></div><ul class="acceptance-list"><li v-for="item in selectedRequirement.acceptance" :key="item"><el-icon><CircleCheck /></el-icon>{{ item }}</li></ul></div>
        <div class="drawer-section"><div class="drawer-section-heading"><strong>推荐后续动作</strong></div><div class="drawer-next-actions"><el-button :icon="EditPen" @click="navigate('/requirements/prototypes')">查看产品原型</el-button><el-button :icon="List" @click="navigate('/requirements/tasks')">查看开发任务</el-button><el-button :icon="Promotion" @click="navigate('/requirements/releases')">关联发布计划</el-button></div></div>
      </template>
    </el-drawer>

    <el-dialog v-model="createDialogVisible" title="新建需求（原型）" width="560px">
      <el-form :model="createForm" label-position="top"><el-form-item label="需求名称" required><el-input v-model="createForm.title" maxlength="120" show-word-limit placeholder="例如：支持发布前自动执行测试计划" /></el-form-item><div class="create-form-grid"><el-form-item label="需求类型"><el-select v-model="createForm.type"><el-option label="平台能力" value="平台能力" /><el-option label="业务需求" value="业务需求" /><el-option label="质量保障" value="质量保障" /></el-select></el-form-item><el-form-item label="优先级"><el-select v-model="createForm.priority"><el-option label="高" value="高" /><el-option label="中" value="中" /><el-option label="低" value="低" /></el-select></el-form-item></div><el-form-item label="负责人"><el-input v-model="createForm.owner" placeholder="填写负责人" /></el-form-item><el-form-item label="需求描述"><el-input v-model="createForm.description" type="textarea" :rows="4" placeholder="描述背景、目标和范围" /></el-form-item></el-form>
      <template #footer><el-button @click="createDialogVisible = false">取消</el-button><el-button type="primary" @click="createRequirement">加入需求池</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.requirement-page { display: flex; flex-direction: column; gap: 18px; }
.requirement-page-head { margin-bottom: 0; }
.requirement-head-actions { display: flex; align-items: center; gap: 8px; }
.requirement-flow-card { padding: 18px 20px; }
.requirement-flow-heading, .requirement-card-heading, .release-card-head, .prototype-card-head, .drawer-section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.requirement-flow-heading strong, .requirement-card-heading strong { display: block; color: #101828; font-size: 14px; }
.requirement-flow-heading span, .requirement-card-heading span { display: block; margin-top: 4px; color: #667085; font-size: 12px; }
.requirement-flow { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: 22px; }
.requirement-flow-step { display: flex; flex: 1; align-items: center; gap: 8px; color: #344054; font-size: 12px; }
.requirement-flow-step .el-icon { margin-left: auto; color: #98a2b3; }
.requirement-flow-index { display: inline-grid; place-items: center; width: 25px; height: 25px; border-radius: 7px; background: #ecfdf3; color: #067647; font: 700 11px monospace; }
.requirement-metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
.requirement-metrics .stat-card { padding: 18px; }
.requirement-metrics .stat-value { margin: 10px 0 7px; font-size: 28px; }
.requirement-metrics small { color: #98a2b3; font-size: 11px; }
.stat-warning { color: #b54708; }.stat-info { color: #175cd3; }
.requirement-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.requirement-toolbar .el-input { width: 280px; }
.requirement-name-cell, .document-name-cell { display: flex; align-items: center; gap: 10px; min-width: 0; }
.requirement-name-cell { flex-direction: column; align-items: flex-start; gap: 3px; }
.requirement-name-cell strong, .document-name-cell strong { overflow: hidden; color: #344054; text-overflow: ellipsis; white-space: nowrap; }
.requirement-name-cell small, .document-name-cell small { color: #98a2b3; font-size: 11px; }
.progress-text { display: block; margin-top: 3px; color: #667085; font-size: 11px; }
.prototype-grid, .release-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.prototype-card { position: relative; padding: 18px; }
.prototype-card-head { align-items: center; }
.prototype-icon, .document-icon { display: inline-grid; place-items: center; width: 34px; height: 34px; border-radius: 9px; background: #eff8ff; color: #175cd3; }
.prototype-card h3 { margin: 18px 0 5px; color: #101828; font-size: 16px; }
.prototype-card > p { margin: 0; color: #667085; font: 11px monospace; }
.prototype-canvas { height: 142px; padding: 16px; margin: 16px 0; border: 1px solid #eaecf0; border-radius: 8px; background: #f8fafc; }
.prototype-canvas-bar { width: 45%; height: 10px; border-radius: 4px; background: #b2ddff; }.prototype-canvas-line { width: 86%; height: 7px; margin-top: 12px; border-radius: 4px; background: #eaecf0; }.prototype-canvas-line.short { width: 65%; margin-top: 16px; }
.prototype-canvas-blocks { display: flex; gap: 8px; margin-top: 16px; }.prototype-canvas-blocks i { display: block; flex: 1; height: 37px; border-radius: 5px; background: #d1fadf; }
.prototype-meta { display: flex; justify-content: space-between; color: #98a2b3; font-size: 11px; }.prototype-sections { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 12px; }.prototype-action { width: 100%; margin-top: 14px; }
.release-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.release-card { padding: 20px; }.release-card h3 { margin: 5px 0 5px; color: #101828; font-size: 17px; }.release-card-head span { color: #667085; font-size: 11px; }.release-readiness { padding: 16px 0; margin: 18px 0; border-top: 1px solid #f2f4f7; border-bottom: 1px solid #f2f4f7; }.release-readiness > div { display: flex; justify-content: space-between; margin-bottom: 9px; color: #667085; font-size: 12px; }.release-readiness strong { color: #067647; font-size: 15px; }.release-facts { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }.release-facts div { min-width: 0; }.release-facts small, .release-facts strong { display: block; }.release-facts small { color: #98a2b3; font-size: 11px; }.release-facts strong { overflow: hidden; margin-top: 5px; color: #344054; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }.release-card-actions { display: flex; justify-content: flex-end; margin-top: 16px; }
.document-name-cell { justify-content: flex-start; }.document-name-cell > div:last-child { min-width: 0; }.document-name-cell strong, .document-name-cell small { display: block; }.document-notice { margin-top: 0; }
.requirement-drawer-head { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 20px; }.requirement-drawer-head > div { min-width: 0; flex: 1; }.requirement-drawer-head h3 { margin: 5px 0 7px; color: #101828; font-size: 18px; }.requirement-drawer-head p:last-child { margin: 0; color: #667085; font-size: 12px; line-height: 1.6; }
.drawer-section { padding-top: 22px; margin-top: 22px; border-top: 1px solid #eaecf0; }.drawer-section-heading { align-items: center; margin-bottom: 11px; color: #344054; font-size: 13px; }.drawer-section-heading > span { color: #667085; font-size: 12px; }.acceptance-list { display: flex; flex-direction: column; gap: 10px; padding: 0; margin: 0; list-style: none; color: #475467; font-size: 12px; }.acceptance-list li { display: flex; align-items: flex-start; gap: 7px; line-height: 1.5; }.acceptance-list .el-icon { flex: 0 0 auto; margin-top: 2px; color: #12b76a; }.drawer-next-actions { display: flex; flex-direction: column; align-items: stretch; gap: 8px; }.create-form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 1050px) { .requirement-metrics { grid-template-columns: repeat(2, 1fr); }.prototype-grid { grid-template-columns: 1fr 1fr; }.requirement-toolbar { align-items: flex-start; flex-direction: column; }.requirement-toolbar .el-input { width: 100%; } }
@media (max-width: 720px) { .requirement-flow { align-items: flex-start; flex-direction: column; }.requirement-flow-step { width: 100%; }.requirement-flow-step .el-icon { display: none; }.prototype-grid, .release-grid { grid-template-columns: 1fr; }.requirement-head-actions { align-items: flex-end; flex-direction: column; }.create-form-grid { grid-template-columns: 1fr; gap: 0; } }
</style>
