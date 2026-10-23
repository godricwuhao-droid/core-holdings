<script setup lang="ts">
/**
 * 登录页（独立布局，不进 MainLayout）
 *
 * 登录成功：存 token + user → 全量 refresh() → 跳回登录前记录的目标路径
 * （route.query.redirect，缺省回 /）。错误提示走后端中文 detail。
 *
 * UI：≥1024px 左右分栏（左品牌区 + 右表单列）；<1024px 回退居中卡片（ADR-045）。
 */
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { login, refresh, showError } from '@/api'
import { setSession } from '@/auth'
import { Shop, List, Tickets } from '@element-plus/icons-vue'

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
    <!-- 左侧品牌区（≥1024px 显示） -->
    <aside class="login-brand">
      <div class="brand-top">
        <img src="/brand/logo-dark.png" alt="蜂云时代" class="brand-top-logo" />
      </div>

      <div class="brand-center">
        <img src="/brand/logo-icon.png" alt="" class="brand-big-logo" />
        <h1 class="brand-name">蜂云产品及服务平台</h1>
        <p class="brand-slogan">产品服务一体化协同平台</p>
        <p class="brand-desc">覆盖产品管理、销售与交付全链路的一体化协同平台</p>
      </div>

      <!-- 底部能力功能卡（ADR-045 修订：替换原纯装饰色块） -->
      <div class="brand-cards">
        <div class="brand-card">
          <el-icon class="brand-card-icon" aria-hidden="true"><Shop /></el-icon>
          <div class="brand-card-title">产品商城</div>
          <div class="brand-card-desc">产品在线展示，可售状态清晰可见，全流程透明可见</div>
        </div>
        <div class="brand-card">
          <el-icon class="brand-card-icon" aria-hidden="true"><List /></el-icon>
          <div class="brand-card-title">订单管理</div>
          <div class="brand-card-desc">项目登记、交付与流转状态同步更新，进度一目了然</div>
        </div>
        <div class="brand-card">
          <el-icon class="brand-card-icon" aria-hidden="true"><Tickets /></el-icon>
          <div class="brand-card-title">交付协同</div>
          <div class="brand-card-desc">合同交付与操作记录可追溯</div>
        </div>
      </div>
    </aside>

    <!-- 右侧表单区 -->
    <main class="login-form-area">
      <div class="login-form">
        <h1 class="form-title">
          欢迎登录 <span class="form-title-brand">蜂云产品及服务平台</span>
        </h1>
        <p class="form-sub">请使用用户名和密码登录平台</p>

        <form class="login-fields" @submit.prevent="handleLogin">
          <div class="field">
            <label class="field-label" for="login-username">
              <span class="req">*</span>用户名
            </label>
            <input
              id="login-username"
              v-model="form.username"
              type="text"
              class="field-input"
              placeholder="请输入用户名"
              autocomplete="username"
              @keyup.enter="handleLogin"
            />
          </div>
          <div class="field">
            <label class="field-label" for="login-password">
              <span class="req">*</span>密码
            </label>
            <input
              id="login-password"
              v-model="form.password"
              type="password"
              class="field-input"
              placeholder="请输入密码"
              autocomplete="current-password"
              @keyup.enter="handleLogin"
            />
          </div>
          <button type="submit" class="login-btn" :disabled="loading">
            {{ loading ? '登录中…' : '登 录' }}
          </button>
        </form>
      </div>

      <p class="copyright">© 2026 蜂云产品及服务平台</p>
    </main>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  background: #ffffff;
}

/* ===== 左侧品牌区 ===== */
.login-brand {
  position: relative;
  width: 52%;
  max-width: 660px;
  display: flex;
  flex-direction: column;
  padding: 40px 56px 0;
  overflow: hidden;
  background: #ffffff;
}
.brand-top {
  display: flex;
  align-items: center;
  gap: 10px;
}
.brand-top-logo {
  width: auto;
  height: 30px;
  display: block;
}
.brand-center {
  margin-top: auto;
  margin-bottom: auto;
  padding: 48px 0;
}
.brand-big-logo {
  width: 88px;
  height: 88px;
  display: block;
  margin-bottom: 24px;
}
.brand-name {
  font-size: 34px;
  font-weight: 700;
  line-height: 1.25;
  color: var(--text-primary);
  margin-bottom: 12px;
}
.brand-slogan {
  font-size: 21px;
  color: var(--text-body);
  margin-bottom: 16px;
}
.brand-desc {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-secondary);
  max-width: 420px;
}
/* 底部能力功能卡（ADR-045 修订：替换原纯装饰色块） */
.brand-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  margin-top: auto;
  margin-bottom: 48px;
}
.brand-card {
  padding: 14px;
  background: var(--card-bg);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  transition: border-color 0.15s;
}
.brand-card:hover {
  border-color: var(--primary-color);
}
.brand-card-icon {
  font-size: 20px;
  color: var(--primary-color);
  margin-bottom: 8px;
}
.brand-card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 4px;
}
.brand-card-desc {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-secondary);
  display: -webkit-box;
  /* TASK-FE-LOGIN-TEXT：新文案较长，放宽至 3 行避免省略号截断（卡片尺寸不变） */
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ===== 右侧表单区 ===== */
.login-form-area {
  flex: 1;
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px;
  background: #ffffff;
}
.login-form {
  width: 400px;
  max-width: 100%;
}
.form-title {
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 8px;
}
.form-title-brand {
  color: var(--primary-color);
}
.form-sub {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 32px;
}
.field {
  margin-bottom: 20px;
}
.field-label {
  display: block;
  font-size: 13px;
  color: var(--text-body);
  margin-bottom: 8px;
}
.field-label .req {
  color: #e5484d;
  margin-right: 2px;
}
.field-input {
  width: 100%;
  height: 44px;
  padding: 0 14px;
  box-sizing: border-box;
  font-size: 14px;
  color: var(--text-primary);
  background: #ffffff;
  border: 1px solid var(--input-border);
  border-radius: 10px;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.field-input::placeholder {
  color: var(--text-secondary);
}
.field-input:hover {
  border-color: var(--primary-color);
}
.field-input:focus {
  border-color: var(--primary-color);
  box-shadow: 0 0 0 3px rgba(23, 105, 212, 0.12);
}
.login-btn {
  width: 100%;
  height: 44px;
  margin-top: 8px;
  font-size: 15px;
  letter-spacing: 4px;
  color: #ffffff;
  background: var(--primary-color);
  border: none;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.15s;
}
.login-btn:hover:not(:disabled) {
  background: #125ab4;
}
.login-btn:active:not(:disabled) {
  background: #0f4a94;
}
.login-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}
.copyright {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 20px;
  text-align: center;
  font-size: 12px;
  color: var(--text-secondary);
}

/* ===== 窄屏回退：居中卡片（<1024px） ===== */
@media (max-width: 1023px) {
  .login-page {
    align-items: center;
    justify-content: center;
    padding: 24px;
    background: var(--bg-color);
  }
  .login-brand {
    display: none;
  }
  .login-form-area {
    width: 100%;
    padding: 0;
  }
  .login-form {
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 36px 32px 32px;
    box-shadow: 0 4px 24px rgba(26, 46, 78, 0.06);
  }
  .form-title {
    text-align: center;
  }
  .form-sub {
    text-align: center;
  }
  .copyright {
    position: static;
    margin-top: 24px;
  }
}
</style>
