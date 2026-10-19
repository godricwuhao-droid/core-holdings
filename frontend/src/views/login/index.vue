<script setup lang="ts">
/**
 * 登录页（独立布局，不进 MainLayout）
 *
 * 登录成功：存 token + user → 全量 refresh() → 跳回登录前记录的目标路径
 * （route.query.redirect，缺省回 /）。错误提示走后端中文 detail。
 */
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Coin, Lock, User } from '@element-plus/icons-vue'
import { login, refresh, showError } from '@/api'
import { setSession } from '@/auth'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const form = reactive({ username: '', password: '' })

async function handleLogin() {
  if (!form.username.trim() || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  if (loading.value) return
  loading.value = true
  try {
    const { token, user } = await login(form.username.trim(), form.password)
    setSession(token, user)
    await refresh(true)
    ElMessage.success('登录成功')
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''
    router.replace(redirect || '/')
  } catch (e) {
    showError(e, '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="login-logo">
        <el-icon :size="34"><Coin /></el-icon>
      </div>
      <h1 class="login-title">蜂云产品及服务平台</h1>
      <p class="login-sub">登录后进入产品及服务</p>
      <el-form @submit.prevent>
        <el-form-item>
          <el-input
            v-model="form.username"
            placeholder="用户名"
            :prefix-icon="User"
            clearable
            size="large"
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            :prefix-icon="Lock"
            show-password
            size="large"
            @keyup.enter="handleLogin"
          />
        </el-form-item>
      </el-form>
      <el-button
        type="primary"
        size="large"
        class="login-btn"
        :loading="loading"
        @click="handleLogin"
      >
        登 录
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-color);
  padding: 24px;
}
.login-card {
  width: 400px;
  max-width: 100%;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  padding: 36px 32px 32px;
  box-shadow: 0 4px 24px rgba(26, 46, 78, 0.06);
}
.login-logo {
  display: flex;
  justify-content: center;
  color: var(--primary-color);
  margin-bottom: 12px;
}
.login-title {
  text-align: center;
  font-size: 20px;
  font-weight: 700;
  color: var(--primary-color);
  letter-spacing: 1px;
}
.login-sub {
  text-align: center;
  font-size: 13px;
  color: var(--text-secondary);
  margin: 6px 0 24px;
}
.login-card :deep(.el-form-item) {
  margin-bottom: 18px;
}
.login-btn {
  width: 100%;
  letter-spacing: 4px;
}
</style>
