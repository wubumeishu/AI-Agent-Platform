import { createRouter, createWebHistory } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'
import HomeView from '@/views/HomeView.vue'
import AboutView from '@/views/AboutView.vue'
import DashboardView from '@/views/DashboardView.vue'
import SettingsView from '@/views/SettingsView.vue'
import NotFoundView from '@/views/NotFoundView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      component: AppLayout,
      children: [
        {
          path: '',
          name: 'home',
          component: HomeView,
        },
        {
          path: 'about',
          name: 'about',
          component: AboutView,
        },
        {
          path: 'dashboard',
          name: 'dashboard',
          component: DashboardView,
        },
        // Phase 1: Resource Layer Routes
        {
          path: 'agents',
          name: 'agents',
          component: () => import('@/views/AgentsView.vue'),
        },
        {
          path: 'agents/:id',
          name: 'agent-detail',
          component: () => import('@/views/AgentDetailView.vue'),
        },
        {
          path: 'personas',
          name: 'personas',
          component: () => import('@/views/PersonasView.vue'),
        },
        {
          path: 'personas/:id',
          name: 'persona-detail',
          component: () => import('@/views/PersonaDetailView.vue'),
        },
        {
          path: 'accounts',
          name: 'accounts',
          component: () => import('@/views/AccountsView.vue'),
        },
        {
          path: 'accounts/:id',
          name: 'account-detail',
          component: () => import('@/views/AccountsDetailView.vue'),
        },
        {
          path: 'platforms',
          name: 'platforms',
          component: () => import('@/views/PlatformsView.vue'),
        },
        {
          path: 'browsers',
          name: 'browsers',
          component: () => import('@/views/BrowsersView.vue'),
        },
        {
          path: 'proxies',
          name: 'proxies',
          component: () => import('@/views/ProxyView.vue'),
        },
        {
          path: 'settings',
          name: 'settings',
          component: SettingsView,
        },
        // Phase 3: Conversation / Message System Routes
        {
          path: 'chats',
          name: 'chats',
          component: () => import('@/views/ChatsView.vue'),
        },
        {
          path: 'chats/:id',
          name: 'chat-detail',
          component: () => import('@/views/ChatsView.vue'),
        },
        // P5MSG-06: Channel-message conversations (列表 + 详情 + 实时)
        {
          path: 'conversations',
          name: 'conversations',
          component: () => import('@/views/conversations/ConversationsView.vue'),
        },
        {
          path: 'conversations/:id',
          name: 'conversation-detail',
          component: () => import('@/views/conversations/ConversationDetailView.vue'),
        },
        // Phase 5: Private Domain Routes
        {
          path: 'private-domain',
          redirect: '/private-domain/channels',
        },
        {
          path: 'private-domain/channels',
          name: 'private-domain-channels',
          component: () => import('@/views/private_domain/ChannelsView.vue'),
        },
        {
          path: 'private-domain/channels/:id',
          name: 'private-domain-channel-detail',
          component: () => import('@/views/private_domain/ChannelDetailView.vue'),
        },
        {
          path: 'private-domain/nurture',
          name: 'private-domain-nurture',
          component: () => import('@/views/private_domain/NurtureView.vue'),
        },
        {
          path: 'private-domain/nurture/:id',
          name: 'private-domain-nurture-detail',
          component: () => import('@/views/private_domain/NurtureDetailView.vue'),
        },
        {
          path: 'private-domain/segments',
          name: 'private-domain-segments',
          component: () => import('@/views/private_domain/SegmentsView.vue'),
        },
        {
          path: 'private-domain/deals',
          name: 'private-domain-deals',
          component: () => import('@/views/private_domain/DealsView.vue'),
        },
        {
          path: 'private-domain/content',
          name: 'private-domain-content',
          component: () => import('@/views/private_domain/ContentView.vue'),
        },
        // Phase 4: CRM Routes
        {
          path: 'crm',
          redirect: '/crm/customers',
        },
        {
          path: 'crm/customers',
          name: 'crm-customers',
          component: () => import('@/views/CustomerListView.vue'),
        },
        {
          path: 'crm/customers/:id',
          name: 'crm-customer-detail',
          component: () => import('@/views/CustomerDetailView.vue'),
        },
        {
          path: 'crm/leads',
          name: 'crm-leads',
          component: () => import('@/views/LeadListView.vue'),
        },
        {
          path: 'crm/leads/:id',
          name: 'crm-lead-detail',
          component: () => import('@/views/LeadDetailView.vue'),
        },
        {
          path: 'crm/tags',
          name: 'crm-tags',
          component: () => import('@/views/TagsView.vue'),
        },
        // P1-002: Prompt 模板管理（P1-002-F 列表页 UI）
        {
          path: 'prompts',
          redirect: '/prompts/templates',
        },
        {
          path: 'prompts/templates',
          name: 'prompt-templates',
          component: () => import('@/views/prompts/PromptTemplatesView.vue'),
        },
        // P1-002: Prompt 模板管理（Demo：版本历史组件视觉验收）
        {
          path: 'prompts/version-history-demo',
          name: 'prompt-version-demo',
          component: () => import('@/views/prompts/PromptVersionDemoView.vue'),
        },
        // P1-002: Prompt 预览弹窗（Demo：变量替换预览组件视觉验收）
        {
          path: 'prompts/preview-demo',
          name: 'prompt-preview-demo',
          component: () => import('@/views/prompts/PromptPreviewDemoView.vue'),
        },
        // Phase 4: Workflow / Scheduler Routes
        {
          path: 'workflows',
          name: 'workflows',
          component: () => import('@/views/workflows/WorkflowsView.vue'),
        },
        {
          path: 'workflows/:id',
          name: 'workflow-detail',
          component: () => import('@/views/workflows/WorkflowDetailView.vue'),
        },
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: NotFoundView,
    },
  ],
})

export default router
