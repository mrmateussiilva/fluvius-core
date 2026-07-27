import { createRouter, createWebHistory } from 'vue-router'
import AppLayout from './layouts/AppLayout.vue'
import AdminSyncPage from './pages/AdminSyncPage.vue'
import ChannelsPage from './pages/ChannelsPage.vue'
import ConversationsPage from './pages/ConversationsPage.vue'
import LoginPage from './pages/LoginPage.vue'
import QuickRepliesPage from './pages/QuickRepliesPage.vue'
import TeamBoardPage from './pages/TeamBoardPage.vue'
import UsersPage from './pages/UsersPage.vue'
import { useAuthStore } from './stores/authStore'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/app/conversations' },
    { path: '/login', component: LoginPage, meta: { public: true } },
    {
      path: '/app',
      component: AppLayout,
      children: [
        { path: 'conversations', component: ConversationsPage },
        {
          path: 'team-board',
          component: TeamBoardPage,
          meta: { admin: true },
        },
        { path: 'quick-replies', component: QuickRepliesPage },
        {
          path: 'settings/channels',
          component: ChannelsPage,
          meta: { admin: true },
        },
        {
          path: 'settings/sync',
          component: AdminSyncPage,
          meta: { admin: true },
        },
        { path: 'settings/users', component: UsersPage },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  const token = localStorage.getItem('fluvius_token')
  if (!to.meta.public && !token) return '/login'
  if (to.path === '/login' && token) return '/app/conversations'
  if (to.meta.admin) {
    const auth = useAuthStore()
    try {
      await auth.restore()
    } catch {
      return '/login'
    }
    if (auth.user?.role !== 'admin') return '/app/conversations'
  }
})
