<script setup lang="ts">
import { ref } from 'vue'
import { NModal, NCard, NForm, NFormItem, NInput, NButton, NSpace, useMessage } from 'naive-ui'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const message = useMessage()
const username = ref('')
const password = ref('')
const loading = ref(false)

async function submit() {
  loading.value = true
  try {
    await auth.login(username.value, password.value)
    message.success(`欢迎，${username.value}`)
  } catch {
    message.error('用户名或密码错误')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <NModal v-model:show="auth.showLogin" :mask-closable="false" :close-on-esc="false" preset="card"
    style="width: 380px" title="登录 Quant Lite">
    <NForm @submit.prevent="submit">
      <NFormItem label="用户名">
        <NInput v-model:value="username" placeholder="username" autofocus />
      </NFormItem>
      <NFormItem label="密码">
        <NInput v-model:value="password" type="password" placeholder="password"
          show-password-on="click" @keydown.enter="submit" />
      </NFormItem>
      <NSpace justify="end">
        <NButton type="primary" :loading="loading" :disabled="!username || !password" @click="submit">
          登录
        </NButton>
      </NSpace>
    </NForm>
  </NModal>
</template>
