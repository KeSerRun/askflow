<template>
  <div class="auth-page">
    <n-card class="auth-card" :bordered="false" size="huge">
      <div class="auth-header">
        <div class="brand">
          <img :src="logoSvg" :alt="app.alt" class="brand-logo" />
          <span class="brand-name">{{ app.brand }}</span>
        </div>
        <n-h2 class="auth-title">创建账号</n-h2>
        <n-text depth="3">注册一个新账号开始使用</n-text>
      </div>

      <n-form
        ref="formRef"
        :model="form"
        :rules="rules"
        size="large"
        label-placement="top"
        @submit.prevent="handleRegister"
      >
        <n-form-item label="用户名" path="username">
          <n-input v-model:value="form.username" placeholder="6 位以上的英文字母或数字">
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
            placeholder="至少 6 位，含大小写字母与数字"
          >
            <template #prefix>
              <n-icon :component="LockClosedOutline" />
            </template>
          </n-input>
        </n-form-item>

        <n-form-item label="确认密码" path="confirmPassword">
          <n-input
            v-model:value="form.confirmPassword"
            type="password"
            show-password-on="click"
            placeholder="再次输入密码"
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
          {{ isLoading ? '注册中…' : '创建账号' }}
        </n-button>
      </n-form>

      <n-divider style="margin: 24px 0 16px" />

      <div class="auth-footer">
        <n-text depth="3">已有账号？</n-text>
        <router-link to="/login" class="auth-link">返回登录</router-link>
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
import axios from '@/http/interceptor'
import logoSvg from '@/assets/logo.svg'
import app from '@/config/app'
import '@/assets/auth.css'
import { usernameRules, passwordRules } from '@/utils/validation'

const router = useRouter()
const message = useMessage()

const formRef = ref(null)
const isLoading = ref(false)
const form = reactive({ username: '', password: '', confirmPassword: '' })

const rules = {
  username: usernameRules,
  password: passwordRules,
  confirmPassword: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    {
      validator: (rule, value) => value === form.password,
      message: '两次输入的密码不一致',
      trigger: 'blur',
    },
  ],
}

const handleRegister = (e) => {
  if (e) e.preventDefault?.()
  formRef.value?.validate(async (errors) => {
    if (errors) return
    isLoading.value = true
    try {
      const response = await axios.post('/api/register', {
        username: form.username,
        password: form.password,
      })
      if (response.status === 200 || response.status === 201) {
        message.success('注册成功，即将跳转登录')
        setTimeout(() => router.push('/login'), 800)
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

