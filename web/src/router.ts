import { createRouter, createWebHistory } from 'vue-router'
import AppLayout from './layouts/AppLayout.vue'
import ChannelsPage from './pages/ChannelsPage.vue'
import ConversationsPage from './pages/ConversationsPage.vue'
import LoginPage from './pages/LoginPage.vue'
import QuickRepliesPage from './pages/QuickRepliesPage.vue'
import UsersPage from './pages/UsersPage.vue'

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
        { path: 'quick-replies', component: QuickRepliesPage },
        { path: 'settings/channels', component: ChannelsPage },
        { path: 'settings/users', component: UsersPage },
      ],
    },
  ],
})

router.beforeEach((to) => {
  const token = localStorage.getItem('fluvius_token')
  if (!to.meta.public && !token) return '/login'
  if (to.path === '/login' && token) return '/app/conversations'
})
