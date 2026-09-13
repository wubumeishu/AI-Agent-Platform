<template>
  <div class="modal-overlay" @click.self="$emit('close')">
    <div class="modal">
      <div class="modal__header">
        <h3 class="modal__title">{{ title }}</h3>
        <button class="modal__close" @click="$emit('close')">×</button>
      </div>
      <div class="modal__body">
        <slot />
      </div>
      <div v-if="$slots.footer" class="modal__footer">
        <slot name="footer" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title: string
}>()

defineEmits<{
  (e: 'close'): void
}>()
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: var(--spacing-4);
}

.modal {
  background: var(--color-bg-primary);
  border-radius: var(--radius-lg);
  width: 100%;
  max-width: 560px;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-lg);
}

.modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-5);
  border-bottom: 1px solid var(--color-border);
}

.modal__title {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  margin: 0;
}

.modal__close {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--color-text-secondary);
  cursor: pointer;
  font-size: var(--font-size-xl);
  line-height: 1;
}

.modal__close:hover {
  background: var(--color-bg-tertiary);
  color: var(--color-text-primary);
}

.modal__body {
  padding: var(--spacing-5);
  overflow-y: auto;
  flex: 1;
}

.modal__footer {
  padding: var(--spacing-4) var(--spacing-5);
  border-top: 1px solid var(--color-border);
  display: flex;
  justify-content: flex-end;
  gap: var(--spacing-2);
}
</style>
