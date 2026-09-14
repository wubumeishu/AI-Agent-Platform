<template>
  <form @submit.prevent="handleSubmit">
    <div class="form-group">
      <label class="form-label">工作流名称 *</label>
      <input
        v-model.trim="formData.name"
        class="form-input"
        placeholder="请输入工作流名称"
        required
        :maxlength="80"
      />
    </div>

    <div class="form-group">
      <label class="form-label">描述</label>
      <textarea
        v-model="formData.description"
        class="form-textarea"
        placeholder="请输入工作流描述（可选）"
        :maxlength="300"
      ></textarea>
      <div class="form-hint">
        <span>用于说明该工作流的用途、触发场景与动作目标</span>
        <span class="form-hint__count">{{ formData.description.length }}/300</span>
      </div>
    </div>

    <ModalFooter>
      <button
        type="button"
        class="btn btn--ghost"
        @click="cancel"
      >
        取消
      </button>
      <button
        type="submit"
        class="btn btn--primary"
        :disabled="submitting || !canSubmit"
      >
        {{ submitting ? '创建中...' : '创建' }}
      </button>
    </ModalFooter>
  </form>
</template>

<script setup lang="ts">
import { ref, reactive, computed } from 'vue'
import ModalFooter from '../common/ModalFooter.vue'

defineProps<{
  submitting?: boolean
}>()

const emit = defineEmits<{
  (e: 'submit', data: { name: string; description?: string }): void
  (e: 'cancel'): void
}>()

const formData = reactive({
  name: '',
  description: '',
})

const canSubmit = computed(() => formData.name.length > 0)

function cancel() {
  emit('cancel')
}

function handleSubmit() {
  if (!canSubmit.value) return
  const data: { name: string; description?: string } = {
    name: formData.name,
  }
  if (formData.description.trim()) {
    data.description = formData.description.trim()
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

.form-input,
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
.form-textarea:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.form-textarea {
  resize: vertical;
  min-height: 80px;
}

.form-hint {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--color-text-muted);
}

.form-hint__count {
  flex-shrink: 0;
}
</style>
