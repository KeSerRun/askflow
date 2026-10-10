<template>
  <n-config-provider :theme="naiveTheme" :theme-overrides="themeOverrides">
    <div class="app-shell">
      <n-loading-bar-provider>
        <n-message-provider>
          <n-dialog-provider>
            <router-view />
          </n-dialog-provider>
        </n-message-provider>
      </n-loading-bar-provider>
    </div>
  </n-config-provider>
</template>

<script setup>
import { computed } from 'vue'
import {
  NConfigProvider,
  NLoadingBarProvider,
  NMessageProvider,
  NDialogProvider,
  darkTheme,
} from 'naive-ui'
import { useThemeStore } from '@/stores/theme'

const themeStore = useThemeStore()

const naiveTheme = computed(() => themeStore.isDark ? darkTheme : null)

const lightOverrides = {
  common: {
    primaryColor: '#d4734e',
    primaryColorHover: '#e08a65',
    primaryColorPressed: '#c06542',
    primaryColorSuppl: '#d4734e',
    borderRadius: '8px',
    fontWeightStrong: '600',
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Roboto, sans-serif',
    bodyColor: '#f5f2ef',
    cardColor: '#ffffff',
    modalColor: '#ffffff',
    popoverColor: '#ffffff',
    tableColor: '#ffffff',
    dividerColor: '#d4cfc8',
    borderColor: '#d4cfc8',
    textColor1: '#1a1714',
    textColor2: '#4a4440',
    textColor3: '#6e6760',
  },
  Input: {
    color: '#ffffff',
    border: '#d4cfc8',
    borderHover: '#d4734e',
    borderFocus: '#d4734e',
    textColor: '#1a1714',
    placeholderColor: '#6e6760',
    lineHeightTextarea: '1.6',
  },
  Card: { borderRadius: '12px' },
  Button: { borderRadiusMedium: '8px' },
}

const darkOverrides = {
  common: {
    primaryColor: '#d4734e',
    primaryColorHover: '#e08a65',
    primaryColorPressed: '#c06542',
    primaryColorSuppl: '#d4734e',
    borderRadius: '8px',
    fontWeightStrong: '600',
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", Roboto, sans-serif',
    bodyColor: '#1c1917',
    cardColor: '#292524',
    modalColor: '#292524',
    popoverColor: '#292524',
    tableColor: '#292524',
    dividerColor: '#57534e',
    borderColor: '#57534e',
    textColor1: '#fafaf9',
    textColor2: '#a8a29e',
    textColor3: '#78716c',
  },
  Input: {
    color: '#292524',
    border: '#57534e',
    borderHover: '#d4734e',
    borderFocus: '#d4734e',
    textColor: '#fafaf9',
    placeholderColor: '#78716c',
    lineHeightTextarea: '1.6',
  },
  Card: { borderRadius: '12px' },
  Button: { borderRadiusMedium: '8px' },
}

const themeOverrides = computed(() =>
  themeStore.isDark ? darkOverrides : lightOverrides
)
</script>

<style>
html,
body,
#app {
  margin: 0;
  padding: 0;
  width: 100%;
  height: 100%;
}

html {
  background-color: var(--color-bg-body);
}

body {
  background-color: transparent;
}

.app-shell {
  min-height: 100vh;
  background-color: var(--color-bg-body);
}

::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}
::-webkit-scrollbar-thumb {
  background-color: var(--color-scrollbar-thumb);
  border-radius: 6px;
}
::-webkit-scrollbar-thumb:hover {
  background-color: var(--color-scrollbar-thumb-hover);
}
::-webkit-scrollbar-track {
  background: var(--color-scrollbar-track);
}

/* ===== 文字选中控制 ===== */
/* 默认全局禁止选中（含所有 Naive UI 组件内部），减小 I 型光标出现范围 */
html, body, #app,
.n-select-menu,
.n-base-menu, .n-base-menu-item,
.n-dropdown, .n-dropdown-option,
.n-popover, .n-popover-content {
  user-select: none;
  cursor: default;
}

/* 下拉框强制覆盖所有内部元素 */
.n-select, .n-select *,
.n-select-menu, .n-select-menu * {
  user-select: none !important;
  cursor: default !important;
}
/* 仅搜索输入框例外 */
.n-select .n-base-selection-input,
.n-select-menu .n-base-menu-item input {
  user-select: text !important;
  cursor: text !important;
}

/* 输入框和文本区域恢复选中 */
input:not([type="button"]):not([type="submit"]):not([type="checkbox"]):not([type="radio"]),
textarea {
  user-select: text !important;
  cursor: text !important;
}

/* 消息气泡等用户应能选中文字的区域 */
.bubble, .ai-content, .user-content,
.reasoning-content,
.log-pre, .log-content,
.n-empty__description,
.n-statistic .n-statistic__value,
.n-data-table td,
.n-descriptions-item__content,
.n-modal-body p,
p, h1, h2, h3, h4, h5, h6,
pre, code, li,
.auth-card .n-text {
  user-select: text !important;
  cursor: auto !important;
}

/* 选中高亮色 */
::selection {
  background-color: var(--color-primary-selection);
}
</style>
