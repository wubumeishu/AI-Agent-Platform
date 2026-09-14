<template>
  <div class="page-container">
    <PageHeader
      title="渠道管理"
      description="管理私域运营渠道，包括微信、邮件、短信等"
      :loading="loading"
    >
      <template #actions>
        <button class="btn btn--primary" @click="showCreateDialog = true">
          + 新建渠道
        </button>
      </template>
    </PageHeader>

    <!-- 筛选栏 -->
    <div class="filters-bar">
      <div class="filters-bar__left">
        <select v-model="filterChannelType" class="form-select form-select--sm" @change="handleFilter">
          <option value="">全部类型</option>
          <option value="wechat">微信</option>
          <option value="wechat_work">企业微信</option>
          <option value="email">邮件</option>
          <option value="sms">短信</option>
          <option value="whatsapp">WhatsApp</option>
          <option value="line">LINE</option>
          <option value="other">其他</option>
        </select>
        <select v-model="filterStatus" class="form-select form-select--sm" @change="handleFilter">
          <option value="">全部状态</option>
          <option value="active">启用</option>
          <option value="inactive">停用</option>
          <option value="pending">待审核</option>
          <option value="online">在线</option>
          <option value="offline">离线</option>
          <option value="error">错误</option>
        </select>
        <select v-model="filterConnectionStatus" class="form-select form-select--sm" @change="handleFilter">
          <option value="">全部连接状态</option>
          <option value="online">在线</option>
          <option value="offline">离线</option>
          <option value="error">错误</option>
        </select>
      </div>
      <div class="filters-bar__right">
        <span class="text-muted">{{ filteredChannels.length }} 个渠道</span>
      </div>
    </div>

    <!-- Loading State -->
    <LoadingState v-if="loading" />

    <!-- Empty State -->
    <EmptyState
      v-else-if="!loading && filteredChannels.length === 0"
      icon="📱"
      title="暂无渠道"
      description="还没有任何渠道，点击创建第一个渠道"
      :show-action="true"
      action-text="创建渠道"
      @action="showCreateDialog = true"
    />

    <!-- Channel List -->
    <div v-else class="channel-list">
      <table class="data-table">
        <thead>
          <tr>
            <th class="col-name">渠道名称</th>
            <th class="col-type">类型</th>
            <th class="col-status">状态</th>
            <th class="col-connection">连接状态</th>
            <th class="col-stats">客户数</th>
            <th class="col-stats">消息数</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="channel in filteredChannels" :key="channel.id">
            <td class="col-name">
              <div class="channel-name">
                <span v-if="channel.avatar_url" class="channel-avatar">
                  <img :src="channel.avatar_url" :alt="channel.name" />
                </span>
                <span>{{ channel.name }}</span>
              </div>
            </td>
            <td class="col-type">
              <span class="type-badge" :class="getTypeClass(channel.channel_type)">
                {{ getTypeLabel(channel.channel_type) }}
              </span>
            </td>
            <td class="col-status">
              <StatusBadge :status="channel.status" :label="getStatusLabel(channel.status)" />
            </td>
            <td class="col-connection">
              <span v-if="channel.connection_status" class="connection-badge" :class="`connection-${channel.connection_status}`">
                {{ getConnectionLabel(channel.connection_status) }}
              </span>
              <span v-else class="text-muted">-</span>
            </td>
            <td class="col-stats">{{ channel.contact_count || 0 }}</td>
            <td class="col-stats">{{ channel.message_count || 0 }}</td>
            <td class="col-actions">
              <button class="btn btn--ghost btn--sm" @click="handleEdit(channel)">编辑</button>
              <button class="btn btn--danger btn--sm" @click="handleDelete(channel)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Pagination -->
      <div v-if="total > 0" class="pagination">
        <span class="pagination-info">共 {{ total }} 条</span>
        <button class="btn btn--ghost" :disabled="currentPage === 1" @click="handlePageChange(currentPage - 1)">
          上一页
        </button>
        <span class="pagination-current">{{ currentPage }}</span>
        <button class="btn btn--ghost" :disabled="currentPage * pageSize >= total" @click="handlePageChange(currentPage + 1)">
          下一页
        </button>
      </div>
    </div>

    <!-- Create Dialog -->
    <Modal v-if="showCreateDialog" title="新建渠道" @close="showCreateDialog = false">
      <ChannelCreateDialog
        @submit="handleCreate"
        @cancel="showCreateDialog = false"
        :creating="creating"
      />
    </Modal>

    <!-- Edit Dialog -->
    <Modal v-if="showEditDialog" title="编辑渠道" @close="showEditDialog = false">
      <ChannelEditDialog
        v-if="editingChannel"
        :channel="editingChannel"
        @submit="handleUpdate"
        @cancel="showEditDialog = false"
        :updating="updating"
      />
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useChannelStore } from '@/stores/channel'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import Modal from '@/components/common/Modal.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import ChannelCreateDialog from '@/components/private_domain/ChannelCreateDialog.vue'
import ChannelEditDialog from '@/components/private_domain/ChannelEditDialog.vue'

const channelStore = useChannelStore()
const { channelList, total, loading } = storeToRefs(channelStore)

// 筛选状态
const filterChannelType = ref('')
const filterStatus = ref('')
const filterConnectionStatus = ref('')

// 对话框状态
const showCreateDialog = ref(false)
const showEditDialog = ref(false)
const editingChannel = ref<any>(null)
const creating = ref(false)
const updating = ref(false)

// 分页
const currentPage = ref(1)
const pageSize = ref(10)

// 筛选后的渠道列表
const filteredChannels = computed(() => {
  return channelList.value.filter(channel => {
    if (filterChannelType.value && channel.channel_type !== filterChannelType.value) return false
    if (filterStatus.value && channel.status !== filterStatus.value) return false
    if (filterConnectionStatus.value && channel.connection_status !== filterConnectionStatus.value) return false
    return true
  })
})

onMounted(async () => {
  await fetchChannels()
})

async function fetchChannels() {
  try {
    const params: any = {
      page: currentPage.value,
      page_size: pageSize.value,
    }
    if (filterChannelType.value) params.channel_type = filterChannelType.value
    if (filterStatus.value) params.status = filterStatus.value
    await channelStore.fetchChannels(params)
  } catch (error) {
    console.error('Failed to fetch channels:', error)
  }
}

function handleFilter() {
  currentPage.value = 1
  fetchChannels()
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

function handleCreate(data: any) {
  creating.value = true
  showCreateDialog.value = false
  channelStore.createChannel(data).then(() => {
    fetchChannels()
  }).catch(error => {
    console.error('Failed to create channel:', error)
  }).finally(() => {
    creating.value = false
  })
}

function handleEdit(channel: any) {
  editingChannel.value = channel
  showEditDialog.value = true
}

async function handleUpdate(data: any) {
  if (!editingChannel.value) return
  updating.value = true
  try {
    await channelStore.updateChannel(editingChannel.value.id, data)
    showEditDialog.value = false
    await fetchChannels()
  } catch (error) {
    console.error('Failed to update channel:', error)
  } finally {
    updating.value = false
  }
}

async function handleDelete(channel: any) {
  if (!confirm(`确定要删除渠道「${channel.name}」吗？此操作不可恢复。`)) {
    return
  }
  try {
    await channelStore.deleteChannel(channel.id)
    await fetchChannels()
  } catch (error) {
    console.error('删除失败:', error)
  }
}

function handlePageChange(page: number) {
  currentPage.value = page
  fetchChannels()
}
</script>

<style scoped>
.page-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.filters-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}

.filters-bar__left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.form-select--sm {
  padding: 6px 12px;
  font-size: 13px;
}

.channel-list {
  background: var(--color-bg-primary);
  border-radius: var(--radius-lg);
  border: 1px solid var(--color-border);
  overflow: hidden;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
}

.data-table th,
.data-table td {
  padding: 14px 16px;
  text-align: left;
  border-bottom: 1px solid var(--color-border);
}

.data-table th {
  font-weight: 600;
  color: var(--color-text-secondary);
  font-size: 12px;
  text-transform: uppercase;
  background: var(--color-bg-secondary);
}

.data-table tbody tr:hover {
  background: var(--color-bg-tertiary);
}

.channel-name {
  display: flex;
  align-items: center;
  gap: 10px;
}

.channel-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  overflow: hidden;
  flex-shrink: 0;
}

.channel-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.type-badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.type-wechat {
  background: #dcfce7;
  color: #166534;
}

.type-wechat-work {
  background: #dbeafe;
  color: #1e40af;
}

.type-email {
  background: #fef9c3;
  color: #854d0e;
}

.type-sms {
  background: #f3f4f6;
  color: #374151;
}

.type-whatsapp {
  background: #d1fae5;
  color: #065f46;
}

.type-line {
  background: #ede9fe;
  color: #5b21b6;
}

.type-other {
  background: #fee2e2;
  color: #991b1b;
}

.connection-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 500;
}

.connection-online {
  background: #d1fae5;
  color: #065f46;
}

.connection-offline {
  background: #f3f4f6;
  color: #6b7280;
}

.connection-error {
  background: #fee2e2;
  color: #991b1b;
}

.col-name {
  width: 200px;
}

.col-type {
  width: 100px;
}

.col-status {
  width: 90px;
}

.col-connection {
  width: 90px;
}

.col-stats {
  width: 80px;
}

.col-actions {
  width: 140px;
  text-align: right;
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 16px;
}

.pagination-info {
  color: var(--color-text-secondary);
  font-size: 14px;
}

.pagination-current {
  padding: 4px 12px;
  background: var(--color-primary-light);
  color: var(--color-primary);
  border-radius: 4px;
  font-weight: 500;
}
</style>
