<template>
  <div class="rename-form">
    <div v-if="mode === 'restore'" class="restore-hint">
      恢复后会话将重新出现在「全部」列表中，状态置为「进行中」。
    </div>
    <form v-else @submit.prevent="handleSubmit">
      <div class="form-group">
        <label class="form-label">会话标题</label>
        <input
          v-model.trim="title"
          class="form-input"
          placeholder="请输入会话标题"
          :maxlength="200"
          :disabled="submitting"
          @keydown.enter="handleSubmit"
        />
        <div class="form-hint">
          <span>最多 200 个字符</span>
          <span class="form-hint__count">{{ title.length }}/200</span>
        </div>
      </div>
      <ModalFooter>
        <button
          type="button"
          class="btn btn--ghost"
          :disabled="submitting"
          @click="emit('cancel')"
        >
          取消
        </button>
        <button
          type="submit"
          class="btn btn--primary"
          :disabled="submitting || title.length === 0"
        >
          {{ submitting ? '保存中...' : '保存' }}
        </button>
      </ModalFooter>
    </form>

    <!-- restore 模式的按钮（在 Modal 内单独放） -->
    <div v-if="mode === 'restore'" class="restore-actions">
      <button
        class="btn btn--ghost"
        :disabled="submitting"
        @click="emit('cancel')"
      >
        取消
      </button>
      <button
        class="btn btn--primary"
        :disabled="submitting"
        @click="emit('submit', { restore: true })"
      >
        {{ submitting ? '恢复中...' : '恢复会话' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import ModalFooter from '@/components/common/ModalFooter.vue'
import type { Conversation } from '@/api/conversation'

const props = defineProps<{
  conversation: Conversation
  mode: 'rename' | 'restore'
  submitting?: boolean
}>()

const emit = defineEmits<{
  (e: 'submit', data: { subject?: string; restore?: boolean }): void
  (e: 'cancel'): void
}>()

const title = ref(props.conversation.subject ?? '')

function handleSubmit() {
  if (title.value.length === 0) return
  emit('submit', { subject: title.value })
}
</script>

<style scoped>
.rename-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.restore-hint {
  font-size: 13px;
  color: var(--color-text-secondary);
  line-height: 1.6;
  padding: var(--spacing-2);
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-md);
}

.restore-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.form-group {
  margin-bottom: 4px;
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
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--color-text-muted);
}
</style>
