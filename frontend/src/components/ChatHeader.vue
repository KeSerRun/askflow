<template>
  <header class="chat-header">
    <div class="header-left">
      <n-button
        class="menu-btn"
        quaternary
        size="small"
        @click="$emit('toggle-sidebar')"
        style="padding: 0 4px; font-size: 20px"
      >
        <template #icon>
          <n-icon :component="MenuOutline" />
        </template>
      </n-button>
      <n-h3 class="title">{{ title }}</n-h3>
    </div>

    <n-space :size="4" align="center" class="header-actions" :wrap="false">
      <!-- 主题切换 -->
      <n-tooltip placement="bottom">
        <template #trigger>
          <n-button quaternary circle size="small" @click="themeStore.toggle">
            <template #icon>
              <n-icon :component="themeStore.isDark ? SunnyOutline : MoonOutline" />
            </template>
          </n-button>
        </template>
        {{ themeStore.isDark ? '亮色模式' : '暗色模式' }}
      </n-tooltip>

      <n-button quaternary @click="$emit('open-doc-manager')" class="doc-btn" size="small">
        <template #icon>
          <n-icon :component="LibraryOutline" />
        </template>
        <span class="doc-btn-text">管理文档</span>
        <n-tag
          v-if="documentCount > 0"
          round
          size="small"
          :bordered="false"
          style="margin-left: 2px; padding: 0 4px"
        >
          {{ documentCount }}
        </n-tag>
      </n-button>

      <n-tooltip placement="bottom">
        <template #trigger>
          <n-button quaternary circle size="small" @click="$emit('logout')">
            <template #icon>
              <n-icon :component="LogOutOutline" />
            </template>
          </n-button>
        </template>
        退出登录
      </n-tooltip>
    </n-space>
  </header>
</template>

<script setup>
import {
  NButton,
  NIcon,
  NSpace,
  NTag,
  NTooltip,
  NH3,
} from 'naive-ui'
import {
  LibraryOutline,
  LogOutOutline,
  MenuOutline,
  SunnyOutline,
  MoonOutline,
} from '@vicons/ionicons5'
import { useUserStore } from '@/stores/user'
import { useThemeStore } from '@/stores/theme'

const userStore = useUserStore()
const themeStore = useThemeStore()

const props = defineProps({
  title: { type: String, default: '新会话' },
  documentCount: { type: Number, default: 0 },
})

defineEmits(['open-doc-manager', 'logout', 'toggle-sidebar'])
</script>

<style scoped>
.chat-header {
  padding: 14px 24px;
  border-bottom: 1px solid var(--color-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
  background-color: var(--color-bg-card);
  z-index: 10;
  flex-shrink: 0;
  -webkit-user-select: none !important;
  user-select: none !important;
}

.header-left {
  display: flex;
  align-items: center;
  min-width: 0;
  flex: 1 1 auto;
  gap: 2px;
}

/* 汉堡菜单按钮 */
.menu-btn {
  flex-shrink: 0;
}

.title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 0 1 auto;
  min-width: 0;
  padding-left: 10px;
  -webkit-user-select: none !important;
  user-select: none !important;
}

/* 右侧操作区保持固定宽度 */
.header-actions {
  flex-shrink: 0;
  display: flex;
  flex-wrap: nowrap !important;
}

/* 移动端/窄屏响应式 */
@media (max-width: 600px) {
  .chat-header {
    padding: 10px 8px;
    gap: 4px;
  }

  .doc-btn-text {
    display: none;
  }

  .doc-btn {
    padding: 0 !important;
    min-width: 32px;
  }

  .header-actions {
    gap: 4px !important;
  }
}
</style>
