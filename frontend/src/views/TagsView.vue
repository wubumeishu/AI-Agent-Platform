<template>
  <div class="tags-view">
    <PageHeader title="标签管理">
      <template #actions>
        <button class="btn btn--primary" @click="showCreateDialog = true">
          + 新建标签
        </button>
      </template>
    </PageHeader>

    <!-- Search -->
    <div class="search-bar">
      <div class="search-bar__input-wrapper">
        <span class="search-bar__icon">🔍</span>
        <input
          v-model="searchQuery"
          class="search-bar__input"
          placeholder="搜索标签..."
          @input="handleSearch"
        />
      </div>
    </div>

    <!-- Loading State -->
    <LoadingState v-if="loading" full-screen />

    <!-- Empty State -->
    <EmptyState
      v-else-if="!loading && tags.length === 0"
      icon="🏷️"
      title="暂无标签"
      description="开始创建你的第一个标签"
      :show-action="true"
      action-text="新建标签"
      @action="showCreateDialog = true"
    />

    <!-- Tags Grid -->
    <div v-else class="tags-grid">
      <div
        v-for="tag in tags"
        :key="tag.id"
        class="tag-card"
      >
        <div class="tag-card__header">
          <div class="tag-color-dot" :style="{ backgroundColor: getTagColor(tag.color) }"></div>
          <h3 class="tag-card__name">{{ tag.name }}</h3>
        </div>
        <p class="tag-card__desc" v-if="tag.description">{{ tag.description }}</p>
        <div class="tag-card__stats">
          <span class="stat-item">👥 {{ tag.customer_count || 0 }} 客户</span>
          <span class="stat-item">🎯 {{ tag.lead_count || 0 }} 线索</span>
        </div>
        <div class="tag-card__actions">
          <button class="btn btn--ghost btn--sm" @click="handleEdit(tag)">编辑</button>
          <button class="btn btn--danger btn--sm" @click="handleDelete(tag)">删除</button>
        </div>
      </div>
    </div>

    <!-- Pagination -->
    <div class="pagination" v-if="total > pageSize">
      <button
        class="btn btn--ghost"
        :disabled="currentPage <= 1"
        @click="changePage(currentPage - 1)"
      >
        上一页
      </button>
      <span class="pagination-info">
        第 {{ currentPage }} / {{ totalPages }} 页，共 {{ total }} 条
      </span>
      <button
        class="btn btn--ghost"
        :disabled="currentPage >= totalPages"
        @click="changePage(currentPage + 1)"
      >
        下一页
      </button>
    </div>

    <!-- Create/Edit Dialog -->
    <Modal v-model:visible="showDialog" :title="editingTag ? '编辑标签' : '新建标签'">
      <form @submit.prevent="handleSubmit">
        <div class="form-group">
          <label class="form-label">标签名称 *</label>
          <input
            v-model="form.name"
            type="text"
            class="form-input"
            placeholder="请输入标签名称"
            required
          />
        </div>
        <div class="form-group">
          <label class="form-label">描述</label>
          <textarea
            v-model="form.description"
            class="form-input"
            rows="3"
            placeholder="请输入标签描述"
          ></textarea>
        </div>
        <div class="form-group">
          <label class="form-label">颜色</label>
          <div class="color-picker">
            <button
              v-for="color in tagColors"
              :key="color.value"
              type="button"
              class="color-option"
              :class="{ 'color-option--active': form.color === color.value }"
              :style="{ backgroundColor: color.hex }"
              @click="form.color = color.value"
            ></button>
          </div>
        </div>
        <ModalFooter>
          <button type="button" class="btn btn--ghost" @click="showDialog = false">取消</button>
          <button type="submit" class="btn btn--primary" :disabled="saving">
            {{ saving ? '保存中...' : '保存' }}
          </button>
        </ModalFooter>
      </form>
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useTagStore } from '@/stores/tag'
import PageHeader from '@/components/common/PageHeader.vue'
import LoadingState from '@/components/common/LoadingState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import Modal from '@/components/common/Modal.vue'
import ModalFooter from '@/components/common/ModalFooter.vue'
import type { Tag, CreateTagRequest, UpdateTagRequest } from '@/api/types'

const tagStore = useTagStore()

// State
const tags = computed(() => tagStore.tags)
const total = computed(() => tagStore.total)
const loading = computed(() => tagStore.loading)
const currentPage = ref(1)
const pageSize = ref(12)
const searchQuery = ref('')
const showCreateDialog = ref(false)
const showDialog = ref(false)
const editingTag = ref<Tag | null>(null)
const saving = ref(false)
const form = ref<{ name: string; description: string; color: string }>({
  name: '',
  description: '',
  color: 'blue',
})

const tagColors = [
  { value: 'blue', hex: '#3B82F6' },
  { value: 'green', hex: '#10B981' },
  { value: 'yellow', hex: '#F59E0B' },
  { value: 'red', hex: '#EF4444' },
  { value: 'purple', hex: '#8B5CF6' },
  { value: 'gray', hex: '#6B7280' },
]

// Methods
async function fetchTags() {
  try {
    const params: any = {
      page: currentPage.value,
      page_size: pageSize.value,
    }
    if (searchQuery.value) params.search = searchQuery.value
    await tagStore.fetchTags(params)
  } catch (error) {
    console.error('Failed to fetch tags:', error)
  }
}

function handleSearch() {
  currentPage.value = 1
  fetchTags()
}

function changePage(page: number) {
  currentPage.value = page
  fetchTags()
}

function handleEdit(tag: Tag) {
  editingTag.value = tag
  form.value = {
    name: tag.name,
    description: tag.description || '',
    color: tag.color || 'blue',
  }
  showDialog.value = true
}

function handleSubmit() {
  saving.value = true
  const promise = editingTag.value
    ? tagStore.updateTag(editingTag.value.id, form.value as UpdateTagRequest)
    : tagStore.createTag(form.value as CreateTagRequest)

  promise
    .then(() => {
      showDialog.value = false
      editingTag.value = null
      form.value = { name: '', description: '', color: 'blue' }
      fetchTags()
    })
    .catch(err => console.error('Failed to save tag:', err))
    .finally(() => {
      saving.value = false
    })
}

function handleDelete(tag: Tag) {
  if (confirm(`确定要删除标签「${tag.name}」吗？`)) {
    tagStore.deleteTag(tag.id).then(() => fetchTags())
  }
}

function getTagColor(color: string | undefined): string {
  const colorMap: Record<string, string> = {
    blue: '#3B82F6',
    green: '#10B981',
    yellow: '#F59E0B',
    red: '#EF4444',
    purple: '#8B5CF6',
    gray: '#6B7280',
  }
  return colorMap[color || 'blue'] || '#6B7280'
}

const totalPages = computed(() => Math.ceil(total.value / pageSize.value))

onMounted(() => {
  fetchTags()
})
</script>

<style scoped>
.tags-view {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-4);
}

.search-bar {
  display: flex;
  gap: var(--spacing-3);
  align-items: center;
}

.search-bar__input-wrapper {
  position: relative;
  flex: 1;
  max-width: 400px;
}

.search-bar__icon {
  position: absolute;
  left: var(--spacing-3);
  top: 50%;
  transform: translateY(-50%);
  color: var(--color-text-muted);
}

.search-bar__input {
  width: 100%;
  padding: var(--spacing-2) var(--spacing-3) var(--spacing-2) var(--spacing-8);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
}

.tags-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: var(--spacing-4);
}

.tag-card {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--spacing-4);
  transition: all var(--transition-fast);
}

.tag-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-sm);
}

.tag-card__header {
  display: flex;
  align-items: center;
  gap: var(--spacing-3);
  margin-bottom: var(--spacing-3);
}

.tag-color-dot {
  width: 16px;
  height: 16px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.tag-card__name {
  font-size: var(--font-size-lg);
  font-weight: var(--font-weight-semibold);
  color: var(--color-text-primary);
  margin: 0;
}

.tag-card__desc {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  margin: 0 0 var(--spacing-3) 0;
  line-height: 1.5;
}

.tag-card__stats {
  display: flex;
  gap: var(--spacing-4);
  margin-bottom: var(--spacing-3);
}

.stat-item {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

.tag-card__actions {
  display: flex;
  gap: var(--spacing-2);
  padding-top: var(--spacing-3);
  border-top: 1px solid var(--color-border);
}

/* Color Picker */
.color-picker {
  display: flex;
  gap: var(--spacing-2);
  flex-wrap: wrap;
}

.color-option {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-full);
  border: 2px solid transparent;
  cursor: pointer;
  transition: all var(--transition-fast);
}

.color-option:hover {
  transform: scale(1.1);
}

.color-option--active {
  border-color: var(--color-text-primary);
  box-shadow: var(--shadow-sm);
}

/* Pagination */
.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--spacing-4);
  padding: var(--spacing-4);
}

.pagination-info {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

/* Form */
.form-group {
  margin-bottom: var(--spacing-4);
}

.form-label {
  display: block;
  margin-bottom: var(--spacing-2);
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}

.form-input {
  width: 100%;
  padding: var(--spacing-2) var(--spacing-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  background: var(--color-bg-primary);
  color: var(--color-text-primary);
  transition: border-color var(--transition-fast);
}

.form-input:focus {
  outline: none;
  border-color: var(--color-primary);
}
</style>
