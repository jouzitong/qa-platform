import { createRouter, createWebHistory } from 'vue-router'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: () => import('./views/DashboardView.vue'), meta: { title: '工作台' } },
    { path: '/projects', component: () => import('./views/ProjectsView.vue'), meta: { title: '项目' } },
    { path: '/apis', component: () => import('./views/ApiDefinitionsView.vue'), meta: { title: 'API 管理' } },
    { path: '/assertions', component: () => import('./views/AssertionsView.vue'), meta: { title: '断言管理' } },
    { path: '/flows', component: () => import('./views/FlowsView.vue'), meta: { title: '测试流程' } },
    { path: '/runs', component: () => import('./views/RunsView.vue'), meta: { title: '执行记录' } },
  ],
})
