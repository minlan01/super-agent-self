<template>
  <div class="login-container">
    <el-card class="login-card" shadow="always">
      <template #header>
        <div style="text-align: center">
          <h2 style="margin: 0; color: var(--theme-text-primary)">{{ t('app.title') }}</h2>
          <p style="margin: 4px 0 0; color: var(--theme-text-secondary); font-size: 13px">{{ t('auth.createNewAccount') }}</p>
        </div>
      </template>

      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-position="top"
        @submit.prevent="handleRegister"
      >
        <el-form-item :label="t('auth.username')" prop="username">
          <el-input
            v-model="form.username"
            :placeholder="t('auth.chooseUsername')"
            size="large"
          />
        </el-form-item>

        <el-form-item :label="t('auth.email')" prop="email">
          <el-input
            v-model="form.email"
            :placeholder="t('auth.enterEmail')"
            size="large"
          />
        </el-form-item>

        <el-form-item :label="t('auth.password')" prop="password">
          <el-input
            v-model="form.password"
            type="password"
            :placeholder="t('auth.choosePassword')"
            size="large"
            show-password
          />
        </el-form-item>

        <el-form-item :label="t('auth.confirmPassword')" prop="confirmPassword">
          <el-input
            v-model="form.confirmPassword"
            type="password"
            :placeholder="t('auth.confirmPasswordPlaceholder')"
            size="large"
            show-password
            @keyup.enter="handleRegister"
          />
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            size="large"
            style="width: 100%"
            :loading="loading"
            @click="handleRegister"
          >
            {{ t('auth.register') }}
          </el-button>
        </el-form-item>
      </el-form>

      <div v-if="error" style="text-align: center; color: var(--theme-color-danger); font-size: 13px; margin-top: 8px">
        {{ error }}
      </div>

      <div style="text-align: center; margin-top: 12px">
        <router-link to="/login" style="color: var(--theme-color-primary); font-size: 13px">
          {{ t('auth.hasAccount') }}
        </router-link>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { authApi } from '../api'

const { t } = useI18n()
const router = useRouter()
const formRef = ref<FormInstance>()
const loading = ref(false)
const error = ref('')

const form = reactive({
  username: '',
  email: '',
  password: '',
  confirmPassword: '',
})

const validateConfirm = (_rule: any, value: string, callback: (err?: Error) => void) => {
  if (value !== form.password) {
    callback(new Error(t('auth.passwordMismatch')))
  } else {
    callback()
  }
}

const rules = computed<FormRules>(() => ({
  username: [
    { required: true, message: t('auth.pleaseEnterUsername'), trigger: 'blur' },
    { min: 3, max: 50, message: t('auth.usernameLength'), trigger: 'blur' },
  ],
  password: [
    { required: true, message: t('auth.pleaseEnterPassword'), trigger: 'blur' },
    { min: 6, message: t('auth.passwordLength'), trigger: 'blur' },
  ],
  confirmPassword: [
    { required: true, message: t('auth.pleaseConfirmPassword'), trigger: 'blur' },
    { validator: validateConfirm, trigger: 'blur' },
  ],
}))

async function handleRegister() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  error.value = ''

  try {
    await authApi.register({
      username: form.username,
      password: form.password,
      email: form.email || undefined,
    })
    ElMessage.success(t('auth.accountCreated'))
    router.push('/login')
  } catch (e: any) {
    const detail = e?.response?.data?.detail || e?.response?.data?.message || t('auth.registrationFailed')
    error.value = detail
  } finally {
    loading.value = false
  }
}
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
</style>
