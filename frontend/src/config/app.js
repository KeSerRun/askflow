/**
 * 应用品牌配置 —— 统一管理所有展示名称，避免硬编码
 *
 * 修改后需重新 `npm run build` 生效
 */
const app = {
  // 应用名称
  name: import.meta.env.VITE_APP_NAME,
  // HTML 标题
  title: import.meta.env.VITE_APP_TITLE,
  // logo alt 文本
  alt: import.meta.env.VITE_APP_NAME,
  // 登录/注册页品牌名
  brand: import.meta.env.VITE_APP_TITLE,
  // 会话侧边栏标题
  sidebar: '会话管理',
  // 管理后台侧边栏标题
  admin: '管理后台',
}

export default app
