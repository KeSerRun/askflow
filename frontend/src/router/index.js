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
const AdminUsers = () => import('@/views/admin/AdminUsers.vue')

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
            { path: 'settings', component: AdminSettings, meta: { title: '系统设置' } },
            { path: 'users', component: AdminUsers, meta: { title: '用户管理' } },
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
        // 角色分离：admin 只能进管理界面；普通用户只能进对话界面
        if (isAdmin && !to.path.startsWith('/admin')) {
            return '/admin/dashboard'
        }
        if (to.meta.requiresAdmin && !isAdmin) {
            return '/chat'
        }
    } else {
        // 已登录时访问登录/注册页：按角色跳转到各自界面
        if ((to.path === '/login' || to.path === '/register') && userStore.isLoggedIn) {
            return isAdmin ? '/admin/dashboard' : '/chat'
        }
    }
})

export default router