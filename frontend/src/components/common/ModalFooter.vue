<template>
  <div class="modal-footer">
    <slot />
  </div>
</template>

<style scoped>
.modal-footer {
  padding: 16px 20px;
  border-top: 1px solid var(--color-border);
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
