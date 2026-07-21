import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: () => import('../views/Login.vue'),
      meta: { public: true },
    },
    {
      path: '/register',
      name: 'Register',
      component: () => import('../views/Register.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('../components/Layout.vue'),
      redirect: '/dashboard',
      children: [
        {
          path: 'dashboard',
          name: 'Dashboard',
          component: () => import('../views/Dashboard.vue'),
          meta: { requiredPermission: 'system:read' },
        },
        {
          path: 'tasks',
          name: 'TaskList',
          component: () => import('../views/TaskList.vue'),
          meta: { requiredPermission: 'tasks:read' },
        },
        {
          path: 'tasks/:id',
          name: 'TaskDetail',
          component: () => import('../views/TaskDetail.vue'),
          props: true,
          meta: { requiredPermission: 'tasks:read' },
        },
        {
          path: 'audit',
          name: 'AuditLog',
          component: () => import('../views/AuditLog.vue'),
          meta: { requiredPermission: 'audit:read' },
        },
        {
          path: 'memory',
          name: 'MemoryList',
          component: () => import('../views/MemoryList.vue'),
          meta: { requiredPermission: 'memory:read' },
        },
        {
          path: 'skills',
          name: 'SkillList',
          component: () => import('../views/SkillList.vue'),
          meta: { requiredPermission: 'skills:read' },
        },
        {
          path: 'skills/:id',
          name: 'SkillDetail',
          component: () => import('../views/SkillDetail.vue'),
          props: true,
          meta: { requiredPermission: 'skills:read' },
        },
        {
          path: 'cron',
          name: 'CronList',
          component: () => import('../views/CronList.vue'),
          meta: { requiredPermission: 'cron:read' },
        },
        {
          path: 'approvals',
          name: 'ApprovalList',
          component: () => import('../views/ApprovalList.vue'),
          meta: { requiredPermission: 'approvals:read' },
        },
        {
          path: 'chat',
          name: 'ChatView',
          component: () => import('../views/ChatView.vue'),
          meta: { requiredPermission: 'chat:read' },
        },
        {
          path: 'conversations',
          name: 'ConversationList',
          component: () => import('../views/ConversationList.vue'),
          meta: { requiredPermission: 'conversations:read' },
        },
        {
          path: 'export',
          name: 'ExportView',
          component: () => import('../views/ExportView.vue'),
          meta: { requiredPermission: 'export:read' },
        },
        {
          path: 'health',
          name: 'HealthView',
          component: () => import('../views/HealthView.vue'),
          meta: { requiredPermission: 'system:read' },
        },
        {
          path: 'analytics',
          name: 'AnalyticsView',
          component: () => import('../views/AnalyticsView.vue'),
          meta: { requiredPermission: 'analytics:read' },
        },
        {
          path: 'task-dag',
          name: 'TaskDAG',
          component: () => import('../views/TaskDAGView.vue'),
          meta: { requiredPermission: 'tasks:read' },
        },
        {
          path: 'templates',
          name: 'TemplateList',
          component: () => import('../views/TemplateList.vue'),
          meta: { requiredPermission: 'templates:read' },
        },
        {
          path: 'agents',
          name: 'AgentList',
          component: () => import('../views/AgentList.vue'),
          meta: { requiredPermission: 'agents:read' },
        },
        {
          path: 'agents/:id',
          name: 'AgentDetail',
          component: () => import('../views/AgentDetail.vue'),
          props: true,
          meta: { requiredPermission: 'agents:read' },
        },
        {
          path: 'scenarios',
          name: 'ScenarioList',
          component: () => import('../views/ScenarioList.vue'),
          meta: { requiredPermission: 'tasks:read' },
        },
        {
          path: 'scenarios/:id',
          name: 'ScenarioDetail',
          component: () => import('../views/ScenarioDetail.vue'),
          props: true,
          meta: { requiredPermission: 'tasks:read' },
        },
        {
          path: 'monitoring',
          name: 'MonitoringView',
          component: () => import('../views/MonitoringView.vue'),
          meta: { requiredPermission: 'system:read' },
        },
        {
          path: 'rbac',
          name: 'RbacManagement',
          component: () => import('../views/RbacManagement.vue'),
          meta: { requiredPermission: 'roles:read' },
        },
        {
          path: '/:pathMatch(.*)*',
          name: 'NotFound',
          component: () => import('../views/NotFound.vue'),
        },
      ],
    },
  ],
})

// Navigation guard — redirect to login if no token
let _tokenValidated = false

router.beforeEach(async (to) => {
  const authStore = useAuthStore()
  const token = localStorage.getItem('agent_admin_token')

  if (!to.meta.public && !token && to.path !== '/login') {
    return { path: '/login' }
  }
  if (to.path === '/login' && token) {
    return { path: '/dashboard' }
  }

  if (token && !_tokenValidated) {
    const valid = await authStore.validateToken()
    _tokenValidated = true
    if (!valid && !to.meta.public) {
      return { path: '/login' }
    }
  }

  const requiredPermission = to.meta.requiredPermission as string | undefined
  if (requiredPermission) {
    const [resource, action] = requiredPermission.split(':')
    if (!authStore.hasPermission(resource, action)) {
      return { path: '/', query: { error: 'permission_denied' } }
    }
  }
})

export default router
