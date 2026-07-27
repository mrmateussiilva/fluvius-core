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
  const auth = useAuthStore()
  if (to.meta.public) {
    if (to.path === '/login' && !auth.user) {
      try {
        await auth.restore()
      } catch {
        auth.clearSession()
      }
    }
    if (to.path === '/login' && auth.user) return '/app/conversations'
    return
  }
  try {
    await auth.restore()
  } catch {
    auth.clearSession()
    return '/login'
  }
  if (to.meta.admin) {
    if (auth.user?.role !== 'admin') return '/app/conversations'
  }
})
