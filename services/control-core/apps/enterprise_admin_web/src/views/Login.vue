<template>
  <div class="login-container">
    <el-card class="login-card" shadow="always">
      <template #header>
        <div style="text-align: center">
          <h2 style="margin: 0; color: var(--theme-text-primary)">{{ t('app.title') }}</h2>
          <p style="margin: 4px 0 0; color: var(--theme-text-secondary); font-size: 13px">{{ t('auth.signInToAccount') }}</p>
        </div>
      </template>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        @submit.prevent="handleLogin"
      >
        <el-form-item :label="t('auth.username')" prop="username">
          <el-input
            v-model="form.username"
            :placeholder="t('auth.enterUsername')"
            prefix-icon="User"
            size="large"
          />
        </el-form-item>

        <el-form-item :label="t('auth.password')" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            :placeholder="t('auth.enterPassword')"
            prefix-icon="Lock"
            size="large"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            size="large"
            style="width: 100%"
            :loading="loading"
            @click="handleLogin"
          >
            {{ t('auth.login') }}
          </el-button>
        </el-form-item>
      </el-form>

      <el-divider v-if="ssoProviders.length > 0">{{ t('auth.or') }}</el-divider>
      <div v-if="ssoProviders.length > 0" class="sso-section">
        <el-button
          v-for="provider in ssoProviders"
          :key="provider.provider"
          type="primary"
          plain
          @click="ssoLogin(provider)"
          style="width: 100%"
        >
          {{ t('auth.signInWith', { provider: provider.display_name }) }}
        </el-button>
      </div>

      <div v-if="error" style="text-align: center; color: var(--theme-color-danger); font-size: 13px; margin-top: 8px">
        {{ error }}
      </div>

      <div style="text-align: center; margin-top: 12px">
        <router-link to="/register" style="color: var(--theme-color-primary); font-size: 13px">
          {{ t('auth.noAccount') }}
        </router-link>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const formRef = ref<FormInstance>()
const loading = ref(false)
const error = ref('')
const ssoProviders = ref<any[]>([])

const form = reactive({
  username: '',
  password: '',
})

const rules = computed<FormRules>(() => ({
  username: [{ required: true, message: t('auth.pleaseEnterUsername'), trigger: 'blur' }],
  password: [{ required: true, message: t('auth.pleaseEnterPassword'), trigger: 'blur' }],
}))

async function handleLogin() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  error.value = ''

  try {
    await authStore.login(form.username, form.password)
    ElMessage.success(t('auth.loginSuccessful'))
    router.push('/dashboard')
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.response?.data?.message || t('auth.loginFailed')
    error.value = detail
  } finally {
    loading.value = false
  }
}

const ssoLogin = (provider: any) => {
  window.location.href = provider.login_url
}

onMounted(async () => {
  await authStore.fetchSSOProviders()
  ssoProviders.value = authStore.ssoProviders

  // Handle SSO callback: if URL has a `code` param, exchange it for a token
  const code = route.query.code as string | undefined
  if (code) {
    loading.value = true
    try {
      await authStore.handleSsoCallback(code)
      // Clean the code param from URL
      router.replace({ path: '/login', query: {} })
      ElMessage.success(t('auth.loginSuccessful'))
      router.push('/dashboard')
    } catch (e: any) {
      const detail = e?.response?.data?.detail || t('auth.loginFailed')
      error.value = detail
    } finally {
      loading.value = false
    }
  }
})
</script>

<style scoped>
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  height: 100vh;
  background: var(--theme-bg-page);
}

.login-card {
  width: 400px;
}

.sso-section {
  margin-top: 16px;
}
</style>
