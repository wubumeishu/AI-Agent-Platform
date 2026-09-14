<template>
  <Modal
    :title="title || '新建 Agent'"
    :open="open"
    @close="$emit('close')"
  >
    <form @submit.prevent="handleSubmit">
      <div class="form-group">
        <label class="form-label">
          Agent 名称 <span class="required">*</span>
        </label>
        <input
          v-model="form.name"
          type="text"
          class="form-input"
          placeholder="请输入 Agent 名称"
          required
          autofocus
        />
        <span v-if="errors.name" class="form-error">{{ errors.name }}</span>
      </div>
      
      <div class="form-group">
        <label class="form-label">描述</label>
        <textarea
          v-model="form.description"
          class="form-textarea"
          placeholder="请输入描述（可选）"
          rows="3"
          maxlength="200"
        ></textarea>
        <span class="form-hint">{{ (form.description || '').length }}/200</span>
      </div>
      
      <div class="form-group">
        <label class="form-label">头像图标</label>
        <div class="icon-picker">
          <button
            v-for="icon in availableIcons"
            :key="icon"
            type="button"
            class="icon-btn"
            :class="{ 'icon-btn--active': form.icon === icon }"
            @click="form.icon = icon"
          >
            {{ icon }}
          </button>
        </div>
      </div>
      
      <ModalFooter>
        <button
          type="button"
          class="btn btn--ghost"
          @click="$emit('close')"
        >
          取消
        </button>
        <button 
          type="submit" 
          class="btn btn--primary"
          :disabled="submitting"
        >
          {{ submitting ? '创建中...' : '创建' }}
        </button>
      </ModalFooter>
    </form>
  </Modal>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import Modal from '@/components/common/Modal.vue'
import ModalFooter from '@/components/common/ModalFooter.vue'

const props = defineProps<{
  open: boolean
  title?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'submit', data: { name: string; description?: string; icon: string }): void
}>()

const availableIcons = ['🤖', '💬', '📊', '🎯', '⚡', '🔧', '🎨', '📝', '🎭', '👤']

const form = ref({
  name: '',
  description: '',
  icon: '🤖',
})

const errors = ref({
  name: '' as string,
})

const submitting = ref(false)

watch(() => props.open, (newValue) => {
  if (newValue) {
    resetForm()
  }
})

function resetForm(): void {
  form.value = {
    name: '',
    description: '',
    icon: '🤖',
  }
  errors.value = { name: '' }
}

function validate(): boolean {
  errors.value = { name: '' }
  
  if (!form.value.name.trim()) {
    errors.value.name = '请输入 Agent 名称'
    return false
  }
  
  if (form.value.name.trim().length < 2) {
    errors.value.name = '名称至少需要 2 个字符'
    return false
  }
  
  return true
}

function handleSubmit(): void {
  if (!validate()) return
  
  submitting.value = true
  try {
    emit('submit', {
      name: form.value.name.trim(),
      description: form.value.description.trim() || undefined,
      icon: form.value.icon,
    })
    emit('close')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.required {
  color: var(--color-error);
}

.form-hint {
  display: block;
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  margin-top: var(--spacing-1);
  text-align: right;
}

.icon-picker {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-2);
}

.icon-btn {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  border: 2px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-primary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.icon-btn:hover {
  border-color: var(--color-primary);
  transform: scale(1.1);
}

.icon-btn--active {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.form-error {
  display: block;
  font-size: var(--font-size-xs);
  color: var(--color-error);
  margin-top: var(--spacing-1);
}
</style>
