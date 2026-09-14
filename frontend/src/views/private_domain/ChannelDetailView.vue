<template>
  <div class="page-container">
    <PageHeader title="渠道详情" :show-back="true">
      <template #actions>
        <button class="btn btn--primary" @click="showEditDialog = true">
          编辑渠道
        </button>
      </template>
    </PageHeader>

    <!-- Loading State -->
    <LoadingState v-if="loading" full-screen />

    <!-- Error State -->
    <div v-else-if="error" class="error-state">
      <p>{{ error }}</p>
      <button class="btn btn--ghost" @click="fetchChannel()">重试</button>
    </div>

    <!-- Channel Detail -->
    <div v-else-if="channel" class="detail-container">
      <!-- 基本信息 -->
      <div class="detail-card">
        <h3 class="detail-card__title">基本信息</h3>
        <div class="detail-grid">
          <div class="detail-item">
            <span class="detail-item__label">渠道名称</span>
            <span class="detail-item__value">{{ channel.name }}</span>
          </div>
          <div class="detail-item">
            <span class="detail-item__label">渠道类型</span>
            <span class="detail-item__value">
              <span class="type-badge" :class="getTypeClass(channel.channel_type)">
                {{ getTypeLabel(channel.channel_type) }}
              </span>
            </span>
          </div>
          <div class="detail-item">
            <span class="detail-item__label">状态</span>
            <span class="detail-item__value">
              <StatusBadge :status="channel.status" :label="getStatusLabel(channel.status)" />
            </span>
          </div>
          <div class="detail-item">
            <span class="detail-item__label">连接状态</span>
            <span class="detail-item__value">
              <span v-if="channel.connection_status" class="connection-badge" :class="`connection-${channel.connection_status}`">
                {{ getConnectionLabel(channel.connection_status) }}
              </span>
              <span v-else class="text-muted">-</span>
            </span>
          </div>
          <div class="detail-item">
            <span class="detail-item__label">平台 ID</span>
            <span class="detail-item__value text-muted">{{ channel.platform_id }}</span>
          </div>
          <div class="detail-item">
            <span class="detail-item__label">创建时间</span>
            <span class="detail-item__value">{{ formatDateTime(channel.created_at) }}</span>
          </div>
          <div class="detail-item">
            <span class="detail-item__label">更新时间</span>
            <span class="detail-item__value">{{ formatDateTime(channel.updated_at) }}</span>
          </div>
          <div class="detail-item full-width" v-if="channel.description">
            <span class="detail-item__label">描述</span>
            <span class="detail-item__value">{{ channel.description }}</span>
          </div>
          <div class="detail-item full-width" v-if="channel.tags && channel.tags.length > 0">
            <span class="detail-item__label">标签</span>
            <span class="detail-item__value">
              <span v-for="tag in channel.tags" :key="tag" class="tag-badge">{{ tag }}</span>
            </span>
          </div>
        </div>
      </div>

      <!-- 统计数据 -->
      <div class="detail-card">
        <h3 class="detail-card__title">统计数据</h3>
        <div class="stats-grid">
          <div class="stat-item">
            <span class="stat-item__number">{{ channel.contact_count || 0 }}</span>
            <span class="stat-item__label">客户数量</span>
          </div>
          <div class="stat-item">
            <span class="stat-item__number">{{ channel.message_count || 0 }}</span>
            <span class="stat-item__label">消息数量</span>
          </div>
          <div class="stat-item">
            <span class="stat-item__number">{{ formatDateTime(channel.last_connection) }}</span>
            <span class="stat-item__label">最后连接时间</span>
          </div>
        </div>
      </div>

      <!-- 联系方式 -->
      <div class="detail-card" v-if="channel.contact_info && Object.keys(channel.contact_info).length > 0">
        <h3 class="detail-card__title">联系方式</h3>
        <div class="contact-info-grid">
          <div v-for="(value, key) in channel.contact_info" :key="key" class="contact-info-item">
            <span class="contact-info-item__label">{{ formatLabel(String(key)) }}</span>
            <span class="contact-info-item__value">{{ value }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Edit Dialog -->
    <Modal v-if="showEditDialog" title="编辑渠道" @close="showEditDialog = false">
      <ChannelEditDialog
        v-if="channel"
        :channel="channel"
        @submit="handleUpdate"
        @cancel="showEditDialog = false"
        :updating="updating"
      />
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useChannelStore } from '@/stores/channel'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import Modal from '@/components/common/Modal.vue'
import ChannelEditDialog from '@/components/private_domain/ChannelEditDialog.vue'

const router = useRouter()
const route = useRoute()
const channelStore = useChannelStore()

const channelId = String(route.params.id)
const channel = ref<any>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const showEditDialog = ref(false)
const updating = ref(false)

onMounted(async () => {
  await fetchChannel()
})

async function fetchChannel() {
  loading.value = true
  error.value = null
  try {
    const data = await channelStore.fetchChannel(channelId)
    channel.value = data
  } catch (err: any) {
    error.value = err.message || '加载渠道详情失败'
    console.error('Failed to fetch channel:', err)
  } finally {
    loading.value = false
  }
}

function getTypeLabel(type: string) {
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

function getTypeClass(type: string) {
  return `type-${type}`
}

function getStatusLabel(status: string) {
  const labels: Record<string, string> = {
    active: '启用',
    inactive: '停用',
    pending: '待审核',
    online: '在线',
    offline: '离线',
    error: '错误',
  }
  return labels[status] || status
}

function getConnectionLabel(status: string) {
  const labels: Record<string, string> = {
    online: '在线',
    offline: '离线',
    error: '错误',
  }
  return labels[status] || status
}

function formatDateTime(dateStr?: string): string {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatLabel(key: string): string {
  const labels: Record<string, string> = {
    phone: '电话号码',
    email: '邮箱',
    username: '用户名',
    account_id: '账号 ID',
  }
  return labels[key] || key
}

async function handleUpdate(data: any) {
  if (!channel.value) return
  updating.value = true
  try {
    await channelStore.updateChannel(channel.value.id, data)
    showEditDialog.value = false
    await fetchChannel()
  } catch (error) {
    console.error('Failed to update channel:', error)
  } finally {
    updating.value = false
  }
}
</script>

<style scoped>
.page-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.error-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px;
  background: var(--color-bg-primary);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
}

.error-state p {
  color: var(--color-error);
  margin-bottom: 16px;
}

.detail-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.detail-card {
  background: var(--color-bg-primary);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  padding: 20px;
}

.detail-card__title {
  font-size: 16px;
  font-weight: 600;
  color: var(--color-text-primary);
  margin-bottom: 20px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--color-border);
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.detail-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.detail-item.full-width {
  grid-column: span 3;
}

.detail-item__label {
  font-size: 12px;
  color: var(--color-text-secondary);
  font-weight: 500;
}

.detail-item__value {
  font-size: 14px;
  color: var(--color-text-primary);
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 20px;
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
}

.stat-item__number {
  font-size: 28px;
  font-weight: 700;
  color: var(--color-primary);
}

.stat-item__label {
  font-size: 13px;
  color: var(--color-text-secondary);
  margin-top: 4px;
}

.contact-info-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.contact-info-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px;
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
}

.contact-info-item__label {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.contact-info-item__value {
  font-size: 14px;
  color: var(--color-text-primary);
  word-break: break-all;
}

.type-badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.type-wechat { background: #dcfce7; color: #166534; }
.type-wechat-work { background: #dbeafe; color: #1e40af; }
.type-email { background: #fef9c3; color: #854d0e; }
.type-sms { background: #f3f4f6; color: #374151; }
.type-whatsapp { background: #d1fae5; color: #065f46; }
.type-line { background: #ede9fe; color: #5b21b6; }
.type-other { background: #fee2e2; color: #991b1b; }

.connection-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
}

.connection-online { background: #d1fae5; color: #065f46; }
.connection-offline { background: #f3f4f6; color: #6b7280; }
.connection-error { background: #fee2e2; color: #991b1b; }

.tag-badge {
  display: inline-block;
  padding: 2px 8px;
  background: var(--color-bg-tertiary);
  border-radius: 4px;
  font-size: 12px;
  color: var(--color-text-secondary);
  margin-right: 4px;
  margin-bottom: 4px;
}

@media (max-width: 768px) {
  .detail-grid {
    grid-template-columns: 1fr;
  }

  .detail-item.full-width {
    grid-column: span 1;
  }

  .stats-grid {
    grid-template-columns: 1fr;
  }

  .contact-info-grid {
    grid-template-columns: 1fr;
  }
}
</style>
