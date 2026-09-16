<template>
  <Modal
    title="删除模板"
    width="440px"
    @close="$emit('cancel')"
  >
    <div class="pt-confirm">
      <div class="pt-confirm__icon">🗑</div>
      <p class="pt-confirm__text">
        确定要删除模板
        <strong>「{{ item?.name }}」</strong>吗？
        <span v-if="item && item.version > 1">
          （当前版本 v{{ item.version }}）
        </span>
        <br />
        删除后该模板的基线版本将被移除，已派生的版本历史将保留但不可再用。
      </p>
      <div class="pt-confirm__warn">此操作不可恢复，请谨慎操作。</div>

      <div class="pt-confirm__footer">
        <button class="btn btn--ghost" @click="$emit('cancel')">取消</button>
        <button
          class="pt-confirm__danger"
          :disabled="busy"
          @click="$emit('confirm')"
        >
          {{ busy ? '删除中…' : '确认删除' }}
        </button>
      </div>
    </div>
  </Modal>
</template>

<script setup lang="ts">
import Modal from '@/components/common/Modal.vue'
import type { PromptTemplateListItem } from '@/api/types'

defineProps<{
  item: PromptTemplateListItem | null
  busy?: boolean
}>()

defineEmits<{
  (e: 'cancel'): void
  (e: 'confirm'): void
}>()
</script>

<style scoped>
.pt-confirm {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.pt-confirm__icon {
  font-size: 34px;
  text-align: center;
}

.pt-confirm__text {
  margin: 0;
  font-size: 14px;
  color: var(--pt-text, #3a2f2a);
  line-height: 1.7;
  text-align: center;
}

.pt-confirm__warn {
  font-size: 13px;
  color: #b91c1c;
  background: #fee2e2;
  border: 1px solid #fecaca;
  border-radius: var(--pt-radius, 8px);
  padding: 8px 12px;
  text-align: center;
}

.pt-confirm__footer {
  display: flex;
  justify-content: center;
  gap: 10px;
}

.pt-confirm__danger {
  padding: 8px 20px;
  font-size: 14px;
  color: #fff;
  background: #dc2626;
  border: none;
  border-radius: var(--pt-radius, 8px);
  cursor: pointer;
  transition: background 0.15s ease;
}

.pt-confirm__danger:hover:not(:disabled) {
  background: #b91c1c;
}

.pt-confirm__danger:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
