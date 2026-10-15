<template>
  <div class="auth-page">
    <div class="auth-bg" aria-hidden="true" />

    <n-card class="auth-card" :bordered="false" size="huge">
      <div class="auth-brand-bar">
        <div class="brand">
          <img :src="logoSvg" :alt="app.alt" class="brand-logo" />
          <span class="brand-name">{{ app.brand }}</span>
        </div>
      </div>

      <div class="auth-header">
        <n-h2 class="auth-title">欢迎回来</n-h2>
        <n-text depth="3">登录以继续与你的知识库对话</n-text>
      </div>

      <n-form
        ref="formRef"
        :model="form"
        :rules="rules"
        size="large"
        label-placement="top"
        @submit.prevent="handleLogin"
      >
        <n-form-item label="用户名" path="username">
          <n-input
            v-model:value="form.username"
            placeholder="请输入用户名"
            :input-props="{ autocomplete: 'username' }"
          >
            <template #prefix>
              <n-icon :component="PersonOutline" />
            </template>
          </n-input>
        </n-form-item>

        <n-form-item label="密码" path="password">
          <n-input
            v-model:value="form.password"
            type="password"
            show-password-on="click"
            placeholder="请输入密码"
            :input-props="{ autocomplete: 'current-password' }"
          >
            <template #prefix>
              <n-icon :component="LockClosedOutline" />
            </template>
          </n-input>
        </n-form-item>

        <n-button
          type="primary"
          size="large"
          block
          :loading="isLoading"
          attr-type="submit"
        >
          {{ isLoading ? '登录中…' : '登 录' }}
        </n-button>
      </n-form>

      <n-divider style="margin: 24px 0 16px" />

      <div class="auth-footer">
        <n-text depth="3">还没有账号？</n-text>
        <router-link to="/register" class="auth-link">立即注册</router-link>
      </div>
    </n-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard,
  NForm,
  NFormItem,
  NInput,
  NButton,
  NIcon,
  NH2,
  NText,
  NDivider,
  useMessage,
} from 'naive-ui'
import {
  PersonOutline,
  LockClosedOutline,
} from '@vicons/ionicons5'
import { useUserStore } from '@/stores/user'
import axios from '@/http/interceptor'
import logoSvg from '@/assets/logo.svg'
import app from '@/config/app'
import '@/assets/auth.css'
import { usernameRules, passwordRules } from '@/utils/validation'

const router = useRouter()
const userStore = useUserStore()
const message = useMessage()

const formRef = ref(null)
const isLoading = ref(false)
const form = reactive({ username: '', password: '' })

const rules = {
  username: usernameRules,
  password: passwordRules,
}

const handleLogin = (e) => {
  if (e) e.preventDefault?.()
  formRef.value?.validate(async (errors) => {
    if (errors) return
    isLoading.value = true
    try {
      const response = await axios.post('/api/login', {
        username: form.username,
        password: form.password,
      })
      if (response.status === 200) {
        const { access_token, user } = response.data
        userStore.accessToken = access_token
        userStore.username = user.username
        userStore.role = user.role
        message.success('登录成功')
        // 管理员也是用户：登录后统一进入对话页，后台从对话页内进入
        router.push('/chat')
      }
    } catch (error) {
      const detail = error.response?.data?.detail || error.response?.data?.message || '网络错误'
      message.error(detail)
    } finally {
      isLoading.value = false
    }
  })
}
</script>

