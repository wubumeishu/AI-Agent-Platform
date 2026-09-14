<template>
  <form @submit.prevent="handleSubmit">
    <div class="form-group">
      <label class="form-label">会话标题</label>
      <input
        v-model.trim="subject"
        class="form-input"
        placeholder="例如：客户咨询跟进（可留空自动生成）"
        :maxlength="200"
        :disabled="submitting"
      />
      <div class="form-hint">
        <span>留空时，标题将基于首条消息自动生成</span>
      </div>
    </div>

    <div class="form-group">
      <label class="form-label">沟通渠道</label>
      <select
        v-model="channel"
        class="form-input"
        :disabled="submitting"
      >
        <option v-for="opt in channelOptions" :key="opt.value" :value="opt.value">
          {{ opt.label }}
        </option>
      </select>
    </div>

    <div class="form-group">
      <label class="form-label">关联客户 ID（可选）</label>
      <input
        v-model.trim="customerId"
        class="form-input"
        placeholder="粘贴客户 UUID，留空则不关联"
        :disabled="submitting"
      />
      <div class="form-hint">
        <span>用于把会话归属到具体客户</span>
      </div>
    </div>

    <div v-if="formError" class="create-error" role="alert">
      ⚠ {{ formError }}
    </div>

    <ModalFooter>
      <button
        type="button"
        class="btn btn--ghost"
        :disabled="submitting"
        @click="cancel"
      >
        取消
      </button>
      <button
        type="submit"
        class="btn btn--primary"
        :disabled="submitting || !canSubmit"
      >
        {{ submitting ? '创建中...' : '创建会话' }}
      </button>
    </ModalFooter>
  </form>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import ModalFooter from '@/components/common/ModalFooter.vue'

defineProps<{
  submitting?: boolean
}>()

const emit = defineEmits<{
  (e: 'submit', data: { subject?: string; channel: string; customer_id: string }): void
  (e: 'cancel'): void
}>()

const subject = ref('')
const channel = ref('web')
const customerId = ref('')

const channelOptions = [
  { value: 'web', label: '网页' },
  { value: 'email', label: '邮件' },
  { value: 'phone', label: '电话' },
  { value: 'wechat', label: '微信' },
  { value: 'dingtalk', label: '钉钉' },
]

// 后端 ConversationCreate.customer_id 为必填（UUID）。
const canSubmit = computed(() => customerId.value.trim() !== '')

const formError = ref('')

function cancel() {
  emit('cancel')
}

function handleSubmit() {
  formError.value = ''
  if (!canSubmit.value) {
    formError.value = '请填写关联客户 ID，或到「客户管理」先创建客户'
    return
  }
  const data = {
    subject: subject.value.trim() || undefined,
    channel: channel.value,
    customer_id: customerId.value.trim(),
  }
  emit('submit', data)
}
</script>

<style scoped>
.form-group {
  margin-bottom: 16px;
}

.form-label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: var(--color-text-primary);
  margin-bottom: 6px;
}

.form-input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  font-size: 14px;
  color: var(--color-text-primary);
  background: var(--color-bg-primary);
  transition: border-color 150ms ease;
}

.form-input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.form-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.create-error {
  margin-bottom: 12px;
  padding: 8px 12px;
  background: var(--color-error-light);
  color: var(--color-error);
  border-radius: var(--radius-md);
  font-size: 13px;
}
</style>
