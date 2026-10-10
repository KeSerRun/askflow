<template>
  <div class="messages-area" ref="messagesContainer">
    <!-- 欢迎屏 -->
    <div v-if="messages.length === 0" class="welcome">
      <div class="welcome-icon">
        <n-icon :size="40" :component="SparklesOutline" />
      </div>
      <n-h2 class="welcome-title">你好，我能帮你做什么？</n-h2>
      <n-text depth="3" class="welcome-sub">
        基于你上传的知识库，我可以回答相关问题。先上传文档，或直接开始提问。
      </n-text>
      <n-text depth="3" class="welcome-session" v-if="sessionIdDisplay">
        当前会话：&nbsp;<code>{{ sessionIdDisplay }}</code>
      </n-text>
    </div>

    <!-- 消息流 -->
    <div
      v-for="(msg, index) in messages"
      :key="msg._key || index"
      :class="['message', msg.role]"
    >
      <div class="avatar-wrap">
        <n-avatar
          v-if="msg.role === 'user'"
          round
          size="small"
          :style="{ backgroundColor: 'var(--color-user-avatar-bg)', color: 'var(--color-user-avatar-text)' }"
        >
          <n-icon :component="PersonOutline" />
        </n-avatar>
        <n-avatar
          v-else
          round
          size="small"
          :style="{ backgroundColor: 'var(--color-primary-glow)', color: 'var(--color-primary)' }"
        >
          <n-icon :component="SparklesOutline" />
        </n-avatar>
      </div>

      <div class="bubble">
        <div v-if="msg.role === 'user'" class="user-content">{{ msg.content }}</div>
        <div v-else>
          <!-- 推理过程（可折叠） -->
          <details v-if="msg.reasoning" class="reasoning-block">
            <summary class="reasoning-header">
              <span class="reasoning-toggle">🤔 思考过程</span>
            </summary>
            <div class="reasoning-content" v-html="renderMarkdown(msg.reasoning, userStore.accessToken)"></div>
          </details>
          <!-- 主回答 -->
          <div class="ai-content" v-html="renderMarkdown(msg.content, userStore.accessToken)"></div>
        </div>
        <!-- 中断提示 -->
        <div v-if="msg.isCancelled" class="cancelled-hint">
          <n-text depth="3" style="font-size: 12px">━━ 回答已中断 ━━</n-text>
        </div>
      </div>
    </div>

    <!-- 思考中：等待后端首段响应 -->
    <div v-if="isLoading && (!messages.length || messages[messages.length - 1]?.role !== 'ai')" class="message ai">
      <div class="avatar-wrap">
        <n-avatar
          round
          size="small"
          :style="{ backgroundColor: 'var(--color-primary-glow)', color: 'var(--color-primary)' }"
        >
          <n-icon :component="SparklesOutline" />
        </n-avatar>
      </div>
      <div class="bubble thinking">
        <div class="thinking-dots">
          <span></span><span></span><span></span>
        </div>
        <div v-if="statusText" class="status-text">{{ statusText }}</div>
      </div>
    </div>

    <!-- Agent 操作状态（独立于 thinking 气泡，AI 已经开始回复后仍可显示） -->
    <div v-if="statusText && isLoading && messages.length && messages[messages.length - 1]?.role === 'ai'" class="agent-status-bar">
      <div class="status-dot"></div>
      <span class="status-label">{{ statusText }}</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, watch } from 'vue'
import { renderMarkdown } from '@/utils/markdown'
// Using renderMarkdown directly in template (no wrapper needed)
import { NAvatar, NIcon, NH2, NText } from 'naive-ui'
import { PersonOutline, SparklesOutline } from '@vicons/ionicons5'
import { useUserStore } from '@/stores/user'

const props = defineProps({
  messages: { type: Array, required: true },
  isLoading: { type: Boolean, default: false },
  currentSessionId: { type: String, default: '' },
  statusText: { type: String, default: '' },
})

const messagesContainer = ref(null)

const userStore = useUserStore()

const sessionIdDisplay = computed(() =>
  props.currentSessionId ? `${props.currentSessionId.substring(0, 8)}...` : ''
)

// parseMarkdown wrapper removed — using renderMarkdown directly in template

const scrollToBottom = async (force = false) => {
  await nextTick()
  if (!messagesContainer.value) return
  // 用户已向上翻阅时不自动滚动（距底部超过 150px 视为主动翻阅）
  if (!force) {
    const threshold = 150
    const dist = messagesContainer.value.scrollHeight - messagesContainer.value.scrollTop - messagesContainer.value.clientHeight
    if (dist > threshold) return
  }
  messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
}

watch(() => props.messages.length, scrollToBottom, { immediate: true })
watch(() => props.isLoading, scrollToBottom)
watch(() => props.statusText, scrollToBottom)

defineExpose({ scrollToBottom })
</script>

<style scoped>
.messages-area {
  flex: 1;
  padding: 32px 24px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 24px;
  scroll-behavior: smooth;
}

.welcome {
  margin: 80px auto 0;
  max-width: 520px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  animation: fadeIn 0.4s ease-out;
}

.welcome-icon {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, var(--color-primary-glow-20), var(--color-primary-bg-subtle));
  color: var(--color-primary);
  margin-bottom: 8px;
}

.welcome-title {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
}

.welcome-sub {
  font-size: 14px;
  line-height: 1.6;
  max-width: 400px;
}

.welcome-session {
  margin-top: 8px;
  font-size: 12px;
}

.welcome-session code {
  font-family: 'Fira Code', Consolas, monospace;
  padding: 2px 6px;
  border-radius: 4px;
  background-color: var(--color-neutral-wash-code);
  font-size: 11px;
}

.message {
  display: flex;
  gap: 12px;
  max-width: 100%;
  animation: messageIn 0.25s ease-out;
}

.message.user {
  flex-direction: row-reverse;
}

.avatar-wrap {
  flex-shrink: 0;
  padding-top: 2px;
}

.bubble {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 15px;
  line-height: 1.65;
  word-break: break-word;
  max-width: min(720px, 80%);
}

.message.user .bubble {
  background-color: var(--color-primary-bg);
  border-bottom-right-radius: 4px;
}

.message.ai .bubble {
  background-color: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-bottom-left-radius: 4px;
}

.user-content {
  white-space: pre-wrap;
  color: var(--color-text-1);
}

.bubble.thinking {
  padding: 14px 18px;
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 24px;
}

.status-text {
  font-size: 13px;
  color: var(--color-text-3);
  white-space: nowrap;
}

.agent-status-bar {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 6px 0;
  animation: fadeIn 0.2s ease-out;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background-color: var(--color-primary);
  animation: thinkingBounce 1.4s infinite ease-in-out both;
}

.status-label {
  font-size: 13px;
  color: var(--color-text-3);
}

.thinking-dots {
  display: flex;
  gap: 4px;
  align-items: center;
}

.thinking-dots span {
  width: 6px;
  height: 6px;
  background-color: var(--color-primary);
  border-radius: 50%;
  display: inline-block;
  animation: thinkingBounce 1.4s infinite ease-in-out both;
}

.thinking-dots span:nth-child(1) {
  animation-delay: -0.32s;
}
.thinking-dots span:nth-child(2) {
  animation-delay: -0.16s;
}

@keyframes thinkingBounce {
  0%, 80%, 100% { transform: scale(0); opacity: 0.5; }
  40% { transform: scale(1); opacity: 1; }
}

@keyframes messageIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* AI 内容的 markdown 样式 */
.ai-content {
  color: var(--color-text-1);
}

.ai-content :deep(h1),
.ai-content :deep(h2),
.ai-content :deep(h3),
.ai-content :deep(h4) {
  margin-top: 18px;
  margin-bottom: 10px;
  font-weight: 600;
  line-height: 1.3;
}

.ai-content :deep(h1) {
  font-size: 22px;
}
.ai-content :deep(h2) {
  font-size: 18px;
}
.ai-content :deep(h3) {
  font-size: 16px;
}
.ai-content :deep(h4) {
  font-size: 15px;
}

.ai-content :deep(p) {
  margin: 8px 0;
}

.ai-content :deep(img) {
  max-width: 100%;
  height: auto;
  border-radius: 6px;
  margin: 8px 0;
  display: block;
}

.ai-content :deep(ul),
.ai-content :deep(ol) {
  padding-left: 1.5em;
  margin: 8px 0;
}

.ai-content :deep(li) {
  margin: 4px 0;
}

.ai-content :deep(pre) {
  background-color: var(--color-code-bg);
  color: var(--color-code-text);
  padding: 14px 16px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 12px 0;
  font-family: 'Fira Code', Consolas, monospace;
  font-size: 13px;
  line-height: 1.6;
}

.ai-content :deep(code) {
  font-family: 'Fira Code', Consolas, monospace;
  font-size: 0.92em;
}

.ai-content :deep(:not(pre) > code) {
  background-color: var(--color-inline-code-bg);
  color: var(--color-inline-code-text);
  padding: 2px 6px;
  border-radius: 4px;
}

.ai-content :deep(blockquote) {
  border-left: 3px solid var(--color-primary);
  padding: 4px 14px;
  margin: 12px 0;
  color: var(--color-text-2);
  background-color: var(--color-primary-bg-subtle);
  border-radius: 0 6px 6px 0;
}

.ai-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 12px 0;
  font-size: 14px;
  table-layout: fixed;
}

.ai-content :deep(th),
.ai-content :deep(td) {
  border: 1px solid var(--color-border);
  padding: 8px 12px;
  text-align: left;
  word-break: break-word;
  overflow-wrap: break-word;
  max-width: 400px;
}

.ai-content :deep(th) {
  background-color: var(--color-neutral-wash);
  font-weight: 600;
}

.ai-content :deep(a) {
  color: var(--color-primary);
  text-decoration: none;
}

.ai-content :deep(a):hover {
  text-decoration: underline;
}

/* 推理过程（思考链）折叠块 */
.reasoning-block {
  margin-bottom: 12px;
  border: 1px solid var(--color-border-light);
  border-radius: 8px;
  overflow: hidden;
  background-color: var(--color-neutral-wash-light);
}

.reasoning-header {
  padding: 8px 12px;
  cursor: pointer;
  user-select: none;
  display: flex;
  align-items: center;
  font-size: 13px;
  color: var(--color-text-3);
  transition: background-color 0.15s;
}

.reasoning-header:hover {
  background-color: var(--color-neutral-wash);
}

.reasoning-toggle {
  font-weight: 500;
}

.reasoning-content {
  padding: 4px 12px 12px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--color-text-2);
  border-top: 1px solid var(--color-border-light);
}

.reasoning-content :deep(p) {
  margin: 6px 0;
}

.ai-content :deep(hr) {
  border: none;
  border-top: 1px solid var(--color-border);
  margin: 16px 0;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .messages-area {
    padding: 20px 16px;
  }
  .bubble {
    max-width: 100%;
  }
}
</style>
