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
    </div>

    <div class="form-group">
      <label class="form-label">状态</label>
      <select v-model="formData.status" class="form-select">
        <option value="draft">草稿</option>
        <option value="active">启用</option>
        <option value="paused">暂停</option>
        <option value="archived">已归档</option>
      </select>
      <div class="form-hint">
        <span>「启用」为可运行状态；草稿为未发布，暂停会暂缓调度，归档表示不再使用</span>
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
        :disabled="updating || !canSubmit"
      >
        {{ updating ? '保存中...' : '保存' }}
      </button>
    </ModalFooter>
  </form>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import ModalFooter from '../common/ModalFooter.vue'
import type { Workflow, WorkflowStatus } from '@/api/types'

const props = defineProps<{
  workflow: Workflow
  updating?: boolean
}>()

const emit = defineEmits<{
  (
    e: 'submit',
    data: { name: string; description?: string; status?: WorkflowStatus }
  ): void
  (e: 'cancel'): void
}>()

const formData = reactive<{
  name: string
  description: string
  status: WorkflowStatus
}>({
  name: '',
  description: '',
  status: 'active',
})

const canSubmit = computed(() => formData.name.length > 0)

watch(
  () => props.workflow,
  (wf) => {
    if (wf) {
      formData.name = wf.name || ''
      formData.description = wf.description || ''
      formData.status = wf.status || 'draft'
    }
  },
  { immediate: true }
)

function cancel() {
  emit('cancel')
}

function handleSubmit() {
  if (!canSubmit.value) return
  const data: { name: string; description?: string; status?: WorkflowStatus } = {
    name: formData.name,
    status: formData.status,
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
.form-textarea,
.form-select {
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
.form-textarea:focus,
.form-select:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px var(--color-primary-light);
}

.form-textarea {
  resize: vertical;
  min-height: 80px;
}

.form-hint {
  margin-top: 4px;
  font-size: 12px;
  color: var(--color-text-muted);
}
</style>
