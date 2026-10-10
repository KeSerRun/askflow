<template>
  <!-- 移动端 overlay 遮罩 -->
  <teleport to="body">
    <div
      v-if="drawerOpen"
      class="drawer-overlay"
      @click="$emit('close')"
    />
  </teleport>

  <aside :class="['session-sidebar', { 'drawer-open': drawerOpen }]">
    <div class="sidebar-header">
      <div class="brand">
        <img :src="logoSvg" :alt="app.alt" class="brand-logo" />
        <span class="brand-name">{{ app.sidebar }}</span>
      </div>
      <n-button
        quaternary
        circle
        size="small"
        class="drawer-close-btn"
        @click="$emit('close')"
      >
        <template #icon>
          <n-icon :component="CloseOutline" />
        </template>
      </n-button>
      <n-button
        block
        type="primary"
        secondary
        @click="$emit('create')"
        class="new-session-btn"
      >
        <template #icon>
          <n-icon :component="AddOutline" />
        </template>
        新建会话
      </n-button>
    </div>

    <n-scrollbar class="session-scroll">
      <div class="session-list">
        <div
          v-for="session in sessions"
          :key="session.id"
          :class="['session-item', { active: currentSessionId === session.id }]"
          @click="selectSession(session.id)"
        >
          <n-icon :size="16" class="session-icon" :component="ChatbubbleEllipsesOutline" />
          <span class="session-title">{{ session.title || '新会话' }}</span>

          <n-popconfirm
            placement="right"
            :show-icon="false"
            @positive-click="$emit('delete', session.id)"
          >
            <template #trigger>
              <n-button
                quaternary
                circle
                size="tiny"
                class="delete-btn"
                @click.stop
                aria-label="删除会话"
              >
                <template #icon>
                  <n-icon :component="CloseOutline" />
                </template>
              </n-button>
            </template>
            <span>确定删除该会话吗？</span>
          </n-popconfirm>
        </div>

        <n-empty
          v-if="!isLoading && sessions.length === 0"
          description="暂无会话"
          size="small"
          class="empty"
        />
      </div>
    </n-scrollbar>
  </aside>
</template>

<script setup>
import {
  NButton,
  NIcon,
  NScrollbar,
  NPopconfirm,
  NEmpty,
} from 'naive-ui'
import {
  ChatbubbleEllipsesOutline,
  AddOutline,
  CloseOutline,
} from '@vicons/ionicons5'
import logoSvg from '@/assets/logo.svg'
import app from '@/config/app'

const props = defineProps({
  sessions: { type: Array, required: true },
  currentSessionId: { type: String, default: '' },
  isLoading: { type: Boolean, default: false },
  drawerOpen: { type: Boolean, default: true },
})

const emit = defineEmits(['create', 'switch', 'delete', 'close'])

// 选会话（不自动关闭，切换会话不应隐藏侧边栏）
const selectSession = (id) => {
  emit('switch', id)
}
</script>

<style scoped>
.session-sidebar {
  width: 280px;
  margin-left: 0;
  flex-shrink: 0;
  background-color: var(--color-bg-card);
  border-right: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  height: 100%;
  z-index: 100;
  transition: margin-left 0.25s cubic-bezier(0.4, 0, 0.2, 1),
              transform 0.25s cubic-bezier(0.4, 0, 0.2, 1),
              box-shadow 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  -webkit-user-select: none !important;
  user-select: none !important;
}

/* ─── 桌面端：滑出屏幕（保持 280px 不变，避免内部布局重排） ─── */
@media (min-width: 769px) {
  .session-sidebar:not(.drawer-open) {
    margin-left: -280px;
    border-right: none;
  }
}

/* ─── overlay 遮罩（仅移动端生效） ─── */
.drawer-overlay {
  display: none;
}

/* ─── 移动端抽屉模式 ─── */
@media (max-width: 768px) {
  .drawer-overlay {
    display: block;
    position: fixed;
    inset: 0;
    background-color: var(--color-overlay);
    z-index: 200;
    animation: fadeIn 0.2s ease-out;
  }

  .session-sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 210;
    width: 280px;
    transform: translateX(-100%);
    transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1),
                box-shadow 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  }

  .session-sidebar.drawer-open {
    transform: translateX(0);
    box-shadow: 4px 0 24px var(--color-shadow-drawer);
  }

  /* 移动端不需要宽度过渡 */
  .session-sidebar:not(.drawer-open) {
    width: 280px;
  }
}

.sidebar-header {
  padding: 20px 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  position: relative;
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--color-primary-brand);
  padding: 0 4px;
}

.brand-logo {
  height: 24px;
  width: auto;
}

.brand-name {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.3px;
}

.drawer-close-btn {
  position: absolute;
  top: 12px;
  right: 12px;
}

.new-session-btn {
  font-weight: 500;
}

.session-scroll {
  flex: 1;
  min-height: 0;
}

.session-list {
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session-item {
  display: flex;
  align-items: center;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  color: var(--color-text-2);
  font-size: 14px;
  transition: background-color 0.15s ease, color 0.15s ease;
  position: relative;
  user-select: none;
}

.session-item:hover {
  background-color: var(--color-neutral-wash-hover);
}

.session-item.active {
  background-color: var(--color-primary-bg);
  color: var(--color-primary);
  font-weight: 500;
}

.session-icon {
  margin-right: 10px;
  flex-shrink: 0;
  opacity: 0.7;
}

.session-item.active .session-icon {
  opacity: 1;
}

.session-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  user-select: none;
}

.delete-btn {
  opacity: 0;
  transition: opacity 0.15s ease;
}

.session-item:hover .delete-btn,
.session-item.active .delete-btn {
  opacity: 0.7;
}

.session-item .delete-btn:hover {
  opacity: 1;
}

.empty {
  margin: 32px 0;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}
</style>
