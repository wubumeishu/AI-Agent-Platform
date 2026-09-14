<template>
  <form @submit.prevent="handleSubmit">
    <div class="form-group">
      <label class="form-label">渠道名称 *</label>
      <input
        v-model="formData.name"
        class="form-input"
        placeholder="请输入渠道名称"
        required
      />
    </div>

    <div class="form-group">
      <label class="form-label">渠道类型</label>
      <select v-model="formData.channel_type" class="form-select">
        <option value="wechat">微信</option>
        <option value="wechat_work">企业微信</option>
        <option value="email">邮件</option>
        <option value="sms">短信</option>
        <option value="whatsapp">WhatsApp</option>
        <option value="line">LINE</option>
        <option value="other">其他</option>
      </select>
    </div>

    <div class="form-group">
      <label class="form-label">状态</label>
      <select v-model="formData.status" class="form-select">
        <option value="active">启用</option>
        <option value="inactive">停用</option>
        <option value="pending">待审核</option>
      </select>
    </div>

    <div class="form-group">
      <label class="form-label">描述</label>
      <textarea
        v-model="formData.description"
        class="form-textarea"
        placeholder="请输入渠道描述（可选）"
      ></textarea>
    </div>

    <div class="form-group">
      <label class="form-label">头像 URL</label>
      <input
        v-model="formData.avatar_url"
        class="form-input"
        placeholder="请输入头像图片地址（可选）"
      />
    </div>

    <div class="form-group">
      <label class="form-label">标签（逗号分隔）</label>
      <input
        v-model="tagsInput"
        class="form-input"
        placeholder="例如: 营销, 客服"
      />
    </div>

    <ModalFooter>
      <button
        type="button"
        class="btn btn--ghost"
        @click="cancel"
      >
        取消
      </button>
      <button type="submit" class="btn btn--primary" :disabled="updating">
        {{ updating ? '保存中...' : '保存' }}
      </button>
    </ModalFooter>
  </form>
</template>

<script setup lang="ts">
import { ref, reactive, watch } from 'vue'
import ModalFooter from '../common/ModalFooter.vue'

const props = defineProps<{
  channel: any
  updating?: boolean
}>()

const emit = defineEmits<{
  (e: 'submit', data: any): void
  (e: 'cancel'): void
}>()

const formData = reactive({
  name: '',
  channel_type: '',
  status: '',
  description: '',
  avatar_url: '',
  tags: [] as string[],
})

const tagsInput = ref('')

watch(() => props.channel, (newChannel) => {
  if (newChannel) {
    formData.name = newChannel.name || ''
    formData.channel_type = newChannel.channel_type || ''
    formData.status = newChannel.status || 'active'
    formData.description = newChannel.description || ''
    formData.avatar_url = newChannel.avatar_url || ''
    formData.tags = newChannel.tags || []
    tagsInput.value = formData.tags.join(', ')
  }
}, { immediate: true })

watch(tagsInput, (newVal) => {
  formData.tags = newVal ? newVal.split(',').map(t => t.trim()).filter(Boolean) : []
})

function cancel() {
  emit('cancel')
}

function handleSubmit() {
  if (!formData.name) {
    return
  }
  
  const data: any = {
    name: formData.name,
    status: formData.status,
  }
  
  if (formData.description) data.description = formData.description
  if (formData.avatar_url) data.avatar_url = formData.avatar_url
  if (formData.tags.length > 0) data.tags = formData.tags
  
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

.form-input,
.form-select,
.form-textarea {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  font-size: 14px;
  color: var(--color-text-primary);
  background: var(--color-bg-primary);
  transition: border-color 150ms ease;
}

.form-input:focus,
.form-select:focus,
.form-textarea:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.form-textarea {
  resize: vertical;
  min-height: 80px;
}
</style>
