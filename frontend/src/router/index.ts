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
