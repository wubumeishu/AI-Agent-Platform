<template>
  <div class="page-container">
    <PageHeader
      title="内容库"
      description="管理私域运营内容资产，支持多种内容类型"
      :loading="loading"
    >
      <template #actions>
        <button class="btn btn--primary" @click="handleCreate">
          + 新建内容
        </button>
      </template>
    </PageHeader>

    <div class="page-content">
      <LoadingState v-if="loading" />

      <EmptyState
        v-else-if="!loading && contentList.length === 0"
        icon="📝"
        title="暂无内容"
        description="还没有任何内容"
        :show-action="true"
        action-text="创建内容"
        @action="handleCreate"
      />

      <table v-else class="data-table">
        <thead>
          <tr>
            <th class="col-title">标题</th>
            <th class="col-type">类型</th>
            <th class="col-status">状态</th>
            <th class="col-tags">标签</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="content in contentList" :key="content.id">
            <td class="col-title">{{ content.title }}</td>
            <td class="col-type">
              <span class="type-badge" :class="`type-${content.content_type}`">
                {{ getTypeLabel(content.content_type) }}
              </span>
            </td>
            <td class="col-status">
              <StatusBadge :status="content.status" :label="getStatusLabel(content.status)" />
            </td>
            <td class="col-tags">
              <template v-if="content.tags?.length">
                <span
                  v-for="tag in content.tags.slice(0, 2)"
                  :key="tag"
                  class="tag-badge"
                >
                  {{ tag }}
                </span>
                <span v-if="content.tags.length > 2" class="tag-more">
                  +{{ content.tags.length - 2 }}
                </span>
              </template>
              <span v-else class="text-muted">-</span>
            </td>
            <td class="col-actions">
              <button class="btn btn--ghost btn--sm" @click="handleEdit(content)">编辑</button>
              <button
                v-if="content.status !== 'published'"
                class="btn btn--success btn--sm"
                @click="handlePublish(content)"
              >发布</button>
              <button class="btn btn--danger btn--sm" @click="handleDelete(content)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>

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
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { useContentStore } from '@/stores/content'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'

const contentStore = useContentStore()
const { contentList, total, loading } = storeToRefs(contentStore)

const currentPage = ref(1)
const pageSize = ref(10)

onMounted(async () => {
  await fetchContents()
})

async function fetchContents() {
  try {
    await contentStore.fetchContents({
      page: currentPage.value,
      page_size: pageSize.value,
    })
  } catch (error) {
    console.error('Failed to fetch contents:', error)
  }
}

function getTypeLabel(type: string) {
  const labels: Record<string, string> = {
    article: '文章',
    video: '视频',
    image: '图片',
    pdf: 'PDF',
    html: 'HTML',
    text: '文本',
  }
  return labels[type] || type
}

function getStatusLabel(status: string) {
  const labels: Record<string, string> = {
    draft: '草稿',
    review: '审核中',
    published: '已发布',
    archived: '已归档',
  }
  return labels[status] || status
}

function handleCreate() {
  alert('创建内容功能待实现')
}

function handleEdit(content: any) {
  alert(`编辑内容: ${content.title}`)
}

async function handlePublish(content: any) {
  try {
    await contentStore.publishContent(content.id)
  } catch (error) {
    console.error('发布失败:', error)
  }
}

async function handleDelete(content: any) {
  if (!confirm(`确定要删除内容「${content.title}」吗？`)) {
    return
  }
  try {
    await contentStore.deleteContent(content.id)
    await fetchContents()
  } catch (error) {
    console.error('删除失败:', error)
  }
}

function handlePageChange(page: number) {
  currentPage.value = page
  fetchContents()
}
</script>

<style scoped>
.page-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-content {
  background: var(--color-bg-secondary);
  border-radius: var(--radius-md);
  padding: 24px;
}

.data-table {
  width: 100%;
  border-collapse: collapse;
}

.data-table th,
.data-table td {
  padding: 12px 16px;
  text-align: left;
  border-bottom: 1px solid var(--color-border);
}

.data-table th {
  font-weight: 600;
  color: var(--color-text-secondary);
  font-size: 12px;
  text-transform: uppercase;
}

.data-table tbody tr:hover {
  background: var(--color-bg-tertiary);
}

.col-title {
  width: 250px;
}

.col-type {
  width: 100px;
}

.col-status {
  width: 100px;
}

.col-tags {
  width: 150px;
}

.col-actions {
  width: 200px;
  text-align: right;
}

.type-badge {
  display: inline-block;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.type-article {
  background: #dbeafe;
  color: #1e40af;
}

.type-video {
  background: #dcfce7;
  color: #166534;
}

.type-image {
  background: #fef9c3;
  color: #854d0e;
}

.type-pdf {
  background: #fee2e2;
  color: #991b1b;
}

.type-html {
  background: #f3f4f6;
  color: #374151;
}

.tag-badge {
  display: inline-block;
  padding: 2px 6px;
  background: var(--color-bg-tertiary);
  border-radius: 4px;
  font-size: 11px;
  margin-right: 4px;
}

.tag-more {
  font-size: 11px;
  color: var(--color-text-secondary);
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 16px;
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
