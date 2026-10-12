<template>
  <div class="admin-layout">
    <!-- 移动端 overlay 遮罩 -->
    <teleport to="body">
      <div
        v-if="drawerOpen"
        class="drawer-overlay"
        @click="drawerOpen = false"
      />
    </teleport>

    <!-- 侧边栏 -->
    <aside :class="['admin-sidebar', { 'drawer-open': drawerOpen }]">
      <div class="sidebar-brand">
        <img :src="logoSvg" :alt="app.alt" class="brand-logo" />
        <span class="brand-text">{{ app.admin }}</span>
      </div>

      <n-button
        quaternary
        circle
        size="small"
        class="drawer-close-btn"
        @click="drawerOpen = false"
      >
        <template #icon>
          <n-icon :component="CloseOutline" />
        </template>
      </n-button>

      <nav class="sidebar-nav">
        <router-link
          v-for="item in menuItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: isActive(item.path) }"
          @click="drawerOpen = false"
        >
          <n-icon :size="18" :component="item.icon" />
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <a class="nav-item logout-link" @click="handleLogout">
          <n-icon :size="18" :component="LogOutOutline" />
          <span>退出登录</span>
        </a>
      </div>
    </aside>

    <!-- 主内容区 -->
    <main class="admin-main">
      <header class="admin-header">
        <div class="header-left">
          <n-button
            class="menu-btn"
            quaternary
            size="small"
            @click="drawerOpen = !drawerOpen"
            style="padding: 0 4px; font-size: 20px"
          >
            <template #icon>
              <n-icon :component="MenuOutline" />
            </template>
          </n-button>
          <n-breadcrumb>
            <n-breadcrumb-item>管理后台</n-breadcrumb-item>
            <n-breadcrumb-item>{{ currentTitle }}</n-breadcrumb-item>
          </n-breadcrumb>
        </div>
        <div class="header-right">
          <!-- 返回对话页（管理员也是用户，对话页为主页面） -->
          <n-button
            quaternary
            size="small"
            @click="router.push('/chat')"
            style="margin-right: 4px"
          >
            <template #icon>
              <n-icon :component="ChatbubblesOutline" />
            </template>
            返回对话
          </n-button>
          <!-- 主题切换 -->
          <n-button
            quaternary
            circle
            size="small"
            @click="themeStore.toggle"
            style="margin-right: 4px"
          >
            <template #icon>
              <n-icon :component="themeStore.isDark ? SunnyOutline : MoonOutline" />
            </template>
          </n-button>
          <n-tag v-if="userStore.role === 'admin'" type="warning" size="small" :bordered="false">
            Admin
          </n-tag>
        </div>
      </header>
      <div class="admin-content">
        <router-view />
      </div>
    </main>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useThemeStore } from '@/stores/theme'
import {
  NIcon, NBreadcrumb, NBreadcrumbItem, NTag, NButton
} from 'naive-ui'
import {
  SpeedometerOutline,
  SettingsOutline,
  PeopleOutline,
  LogOutOutline,
  MenuOutline,
  CloseOutline,
  SunnyOutline,
  MoonOutline,
  ChatbubblesOutline,
  ServerOutline,
  DocumentsOutline,
  ConstructOutline,
  DocumentTextOutline,
} from '@vicons/ionicons5'
import logoSvg from '@/assets/logo.svg'
import app from '@/config/app'
import axios from '@/http/interceptor'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const themeStore = useThemeStore()

const drawerOpen = ref(false)

const menuItems = [
  { path: '/admin/dashboard', label: '仪表盘', icon: SpeedometerOutline },
  { path: '/admin/members', label: '用户与会话', icon: PeopleOutline },
  { path: '/admin/database', label: '数据管理', icon: ServerOutline },
  { path: '/admin/logs', label: '日志管理', icon: DocumentsOutline },
  { path: '/admin/tools', label: '工具管理', icon: ConstructOutline },
  { path: '/admin/prompts', label: 'Prompt 管理', icon: DocumentTextOutline },
  { path: '/admin/settings', label: '系统设置', icon: SettingsOutline },
]

const currentTitle = computed(() => {
  const item = menuItems.find(m => isActive(m.path))
  return item ? item.label : ''
})

function isActive(path) {
  return route.path === path
}

async function handleLogout() {
  try {
    await axios.post('/api/logout')  // 清 httpOnly cookie
  } catch (e) { /* 忽略：本地仍然登出 */ }
  userStore.logout()
  router.push('/login')
}
</script>

<style scoped>
.admin-layout {
  display: flex;
  height: 100vh;
  background-color: var(--color-bg-body);
}

/* 移动端遮罩 */
.drawer-overlay {
  display: none;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: var(--color-overlay-dark);
  z-index: 200;
  animation: fadeIn 0.25s ease-out;
}

/* 侧边栏 */
.admin-sidebar {
  width: 220px;
  min-width: 220px;
  background: var(--color-bg-white);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 18px;
  border-bottom: 1px solid var(--color-border);
  color: var(--color-primary);
  font-size: 16px;
  font-weight: 600;
}

.brand-logo {
  height: 28px;
  width: auto;
  flex-shrink: 0;
}

.drawer-close-btn {
  display: none;
  position: absolute;
  top: 12px;
  right: 12px;
}

.brand-text {
  letter-spacing: 0.5px;
}

.sidebar-nav {
  flex: 1;
  padding: 12px 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: 8px;
  color: var(--color-text-2);
  text-decoration: none;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.15s;
}

.nav-item:hover {
  background: var(--color-bg-hover);
  color: var(--color-primary);
}

.nav-item.active {
  background: var(--color-bg-active);
  color: var(--color-primary);
  font-weight: 500;
}

.sidebar-footer {
  padding: 12px 8px;
  border-top: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.back-link {
  color: var(--color-text-3);
}

.logout-link {
  color: var(--color-danger);
}

.logout-link:hover {
  background: var(--color-bg-danger-hover);
}

/* 主内容区 */
.admin-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
}

.admin-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 28px;
  background: var(--color-bg-white);
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.menu-btn {
  display: none; /* PC端隐藏 */
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.admin-content {
  flex: 1;
  padding: 24px 28px;
  overflow: auto; /* 允许横向和纵向滚动 */
  display: flex;
  flex-direction: column;
}

/* 确保内容区有一个最小的合适阅读宽度，如果窗口比这还窄，就会出横向滚动条而不是挤压内容 */
.admin-content > :first-child {
  min-width: 900px; /* 设为900px保证多列布局不会被挤扁 */
  flex: 1; /* 让子页面组件能伸展填满高度（如果需要） */
}

/* 响应式移动端 */
@media (max-width: 768px) {
  .drawer-overlay {
    display: block;
  }

  .admin-sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 210;
    width: 250px;
    transform: translateX(-100%);
    box-shadow: none;
  }

  .admin-sidebar.drawer-open {
    transform: translateX(0);
    box-shadow: 4px 0 24px var(--color-shadow-drawer);
  }

  .drawer-close-btn {
    display: inline-flex;
  }

  .menu-btn {
    display: inline-flex; /* 移动端显示 */
  }

  .admin-header {
    padding: 14px 16px; /* 移动端减少 padding */
  }

  .admin-content {
    padding: 16px;
  }
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>
