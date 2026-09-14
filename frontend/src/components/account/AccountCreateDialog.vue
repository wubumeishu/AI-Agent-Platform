<template>
  <form @submit.prevent="$emit('submit', formData)">
    <div class="form-group">
      <label class="form-label">平台</label>
      <select v-model="formData.platform_id" class="form-select" required>
        <option value="" disabled>请选择平台</option>
        <option v-for="platform in platforms" :key="platform.id" :value="platform.code">
          {{ platform.name }}
        </option>
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">账号名称</label>
      <input
        v-model="formData.name"
        class="form-input"
        placeholder="请输入账号名称"
        required
      />
    </div>
    <div class="form-group">
      <label class="form-label">用户名</label>
      <input
        v-model="formData.username"
        class="form-input"
        placeholder="请输入用户名（可选）"
      />
    </div>
    <div class="form-group">
      <label class="form-label">密码</label>
      <input
        v-model="formData.password"
        type="password"
        class="form-input"
        placeholder="请输入密码"
      />
    </div>
    <ModalFooter>
      <button
        type="button"
        class="btn btn--ghost"
        @click="$emit('cancel')"
      >
        取消
      </button>
      <button type="submit" class="btn btn--primary" :disabled="creating">
        {{ creating ? '创建中...' : '创建' }}
      </button>
    </ModalFooter>
  </form>
</template>

<script setup lang="ts">
import { reactive } from 'vue'
import type { Platform } from '@/api/types'
import ModalFooter from '../common/ModalFooter.vue'

defineProps<{
  platforms: Platform[]
  creating?: boolean
}>()

defineEmits<{
  (e: 'submit', data: any): void
  (e: 'cancel'): void
}>()

const formData = reactive({
  platform_id: '',
  name: '',
  username: '',
  password: '',
})
</script>
