import { createRouter, createWebHashHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { refreshSession } from '@/http/interceptor'
import Login from '@/views/Login.vue'
import Register from '@/views/Register.vue'
import Home from '@/views/Home.vue'

// admin 页面（懒加载）
const AdminLayout = () => import('@/views/admin/AdminLayout.vue')
const AdminDashboard = () => import('@/views/admin/AdminDashboard.vue')
const AdminSettings = () => import('@/views/admin/AdminSettings.vue')
const AdminMembers = () => import('@/views/admin/AdminMembers.vue')
const AdminDatabase = () => import('@/views/admin/AdminDatabase.vue')
const AdminLogs = () => import('@/views/admin/AdminLogs.vue')
const AdminTools = () => import('@/views/admin/AdminTools.vue')
const AdminPrompts = () => import('@/views/admin/AdminPrompts.vue')

// 定义路由
const routes = [
    { path: '/login', component: Login },
    { path: '/register', component: Register },
    { path: '/', redirect: '/chat' },
    { path: '/chat', component: Home, meta: { requiresAuth: true } },
    // 管理后台
    {
        path: '/admin',
        component: AdminLayout,
        meta: { requiresAuth: true, requiresAdmin: true },
        redirect: '/admin/dashboard',
        children: [
            { path: 'dashboard', component: AdminDashboard, meta: { title: '仪表盘' } },
            { path: 'database', component: AdminDatabase, meta: { title: '数据管理' } },
            { path: 'members', component: AdminMembers, meta: { title: '用户与会话' } },
            // 旧入口兼容重定向到合并页
            { path: 'sessions', redirect: '/admin/members?tab=sessions' },
            { path: 'users', redirect: '/admin/members' },
            { path: 'logs', component: AdminLogs, meta: { title: '日志管理' } },
            { path: 'tools', component: AdminTools, meta: { title: '工具管理' } },
            { path: 'prompts', component: AdminPrompts, meta: { title: 'Prompt 管理' } },
            { path: 'settings', component: AdminSettings, meta: { title: '系统设置' } },
        ],
    },
]

// 创建路由实例
const router = createRouter({
    history: createWebHashHistory(),
    routes,
})

// 路由守卫
router.beforeEach(async (to) => {
    const userStore = useUserStore()

    // 内存无 access token 时，用 httpOnly cookie 里的 refresh_token 换新 access（恢复会话）
    if (!userStore.accessToken) {
        await refreshSession()
    }

    const isAdmin = userStore.role === 'admin'

    if (to.meta.requiresAuth) {
        if (!userStore.isLoggedIn) {
            return '/login'
        }
        // 只有管理后台要求管理员权限；管理员同样可访问对话页（管理员也是用户）
        if (to.meta.requiresAdmin && !isAdmin) {
            return '/chat'
        }
    } else {
        // 已登录时访问登录/注册页：统一跳转对话页
        if ((to.path === '/login' || to.path === '/register') && userStore.isLoggedIn) {
            return '/chat'
        }
    }
})

export default router