<template>
  <form @submit.prevent="handleSubmit">
    <div class="form-group">
      <label class="form-label">计划名称 *</label>
      <input
        v-model="formData.name"
        class="form-input"
        placeholder="请输入培育计划名称"
        required
      />
    </div>

    <div class="form-group">
      <label class="form-label">关联渠道 *</label>
      <select v-model="formData.channel_id" class="form-select" required>
        <option value="">请选择渠道</option>
        <option v-for="ch in channels" :key="ch.id" :value="ch.id">
          {{ ch.name }} ({{ getChannelTypeLabel(ch.channel_type) }})
        </option>
      </select>
    </div>

    <div class="form-group">
      <label class="form-label">触发方式</label>
      <select v-model="formData.schedule_type" class="form-select">
        <option value="fixed">固定时间</option>
        <option value="drip">滴灌序列</option>
        <option value="triggered">触发式</option>
      </select>
    </div>

    <div class="form-group">
      <label class="form-label">目标客户群</label>
      <select v-model="formData.target_segment_id" class="form-select">
        <option value="">不限定客户群</option>
        <option v-for="seg in segments" :key="seg.id" :value="seg.id">
          {{ seg.name }} ({{ seg.member_count }} 人)
        </option>
      </select>
    </div>

    <div class="form-group">
      <label class="form-label">描述</label>
      <textarea
        v-model="formData.description"
        class="form-textarea"
        placeholder="请输入培育计划描述（可选）"
      ></textarea>
    </div>

    <ModalFooter>
      <button
        type="button"
        class="btn btn--ghost"
        @click="cancel"
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
import { ref, reactive, onMounted } from 'vue'
import { useSegmentStore } from '@/stores/segment'
import ModalFooter from '../common/ModalFooter.vue'

const props = defineProps<{
  channels: any[]
  creating?: boolean
}>()

const emit = defineEmits<{
  (e: 'submit', data: any): void
  (e: 'cancel'): void
}>()

const segmentStore = useSegmentStore()
const segments = ref<any[]>([])

const formData = reactive({
  name: '',
  channel_id: '',
  description: '',
  schedule_type: 'fixed',
  target_segment_id: '',
})

// 获取客户群列表
async function fetchSegments() {
  try {
    const data = await segmentStore.fetchSegments({ account_id: '1', page_size: 100 })
    segments.value = data.items
  } catch (error) {
    console.error('Failed to fetch segments:', error)
  }
}

onMounted(fetchSegments)

function getChannelTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    wechat: '微信',
    wechat_work: '企业微信',
    email: '邮件',
    sms: '短信',
    whatsapp: 'WhatsApp',
    line: 'LINE',
    other: '其他',
  }
  return labels[type] || type
}

function cancel() {
  emit('cancel')
}

function handleSubmit() {
  if (!formData.name || !formData.channel_id) {
    return
  }
  
  const data: any = {
    name: formData.name,
    channel_id: formData.channel_id,
    schedule_type: formData.schedule_type,
  }
  
  if (formData.description) data.description = formData.description
  if (formData.target_segment_id) data.target_segment_id = formData.target_segment_id
  
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
