import axios from 'axios'
import { useUserStore } from '@/stores/user'

// 创建实例
const instance = axios.create()

// ── 刷新会话（单飞）：用 httpOnly cookie 里的 refresh_token 换新 access ──
let refreshPromise = null
export function refreshSession() {
    if (!refreshPromise) {
        refreshPromise = axios.post('/api/refresh')
            .then((r) => {
                const store = useUserStore()
                store.accessToken = r.data.access_token
                store.username = r.data.user.username
                store.role = r.data.user.role
                return true
            })
            .catch(() => false)
            .finally(() => { refreshPromise = null })
    }
    return refreshPromise
}

// 请求拦截器：附加短时效 access token
instance.interceptors.request.use(
    (config) => {
        const store = useUserStore()
        if (store.accessToken) {
            config.headers = config.headers || {}
            config.headers.Authorization = `Bearer ${store.accessToken}`
        }
        return config
    },
    (error) => Promise.reject(error)
)

// 响应拦截器：401 → 刷新 → 重放一次；刷新失败则登出
instance.interceptors.response.use(
    (response) => response,
    async (error) => {
        const { response, config } = error
        const isRefreshCall = (config?.url || '').includes('/api/refresh')
        if (response?.status === 401 && config && !config._refreshed && !isRefreshCall) {
            config._refreshed = true
            if (await refreshSession()) {
                const store = useUserStore()
                config.headers = config.headers || {}
                config.headers.Authorization = `Bearer ${store.accessToken}`
                return instance.request(config)
            }
        }
        // 无法刷新（refresh 失效/过期/不存在）→ 清空登录态并回登录页
        if (response?.status === 401) {
            try {
                const store = useUserStore()
                store.logout()
            } catch (e) {
                localStorage.removeItem('user')
            }
            if (!location.hash.startsWith('#/login')) {
                location.hash = '#/login'
            }
        }
        return Promise.reject(error)
    }
)

export default instance