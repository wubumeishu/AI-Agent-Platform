<template>
  <div class="persona-editor">
    <!-- 基本信息 -->
    <Card>
      <template #header>
        <h3>基本信息</h3>
      </template>
      
      <div class="form-group">
        <label class="form-label">
          名称 <span class="required">*</span>
        </label>
        <input
          v-model="editForm.name"
          type="text"
          class="form-input"
          placeholder="请输入 Persona 名称"
          required
        />
      </div>
      
      <div class="form-group">
        <label class="form-label">头像图标</label>
        <div class="icon-picker">
          <button
            v-for="icon in availableIcons"
            :key="icon"
            type="button"
            class="icon-btn"
            :class="{ 'icon-btn--active': editForm.icon === icon }"
            @click="editForm.icon = icon"
          >
            {{ icon }}
          </button>
        </div>
      </div>
      
      <div class="form-group">
        <label class="form-label">描述</label>
        <textarea
          v-model="editForm.description"
          class="form-textarea"
          placeholder="请输入描述（可选）"
          rows="3"
          maxlength="300"
        ></textarea>
        <span class="form-hint">{{ (editForm.description || '').length }}/300</span>
      </div>
    </Card>

    <!-- 性格参数 -->
    <Card class="mt-5">
      <template #header>
        <h3>性格参数</h3>
      </template>
      
      <div class="form-grid">
        <div class="form-group">
          <label class="form-label">语气风格</label>
          <select v-model="editForm.personality.tone" class="form-select">
            <option value="professional">专业严谨</option>
            <option value="friendly">友好亲切</option>
            <option value="casual">随意轻松</option>
          </select>
          <p class="form-hint">决定 AI 回复的语气风格</p>
        </div>
        
        <div class="form-group">
          <label class="form-label">回复长度</label>
          <select v-model="editForm.personality.reply_length" class="form-select">
            <option value="concise">简洁明了</option>
            <option value="balanced">适中平衡</option>
            <option value="detailed">详细全面</option>
          </select>
          <p class="form-hint">控制回复的详略程度</p>
        </div>
        
        <div class="form-group">
          <label class="form-label">主动性</label>
          <select v-model="editForm.personality.proactiveness" class="form-select">
            <option value="low">被动响应</option>
            <option value="medium">适中引导</option>
            <option value="high">主动推进</option>
          </select>
          <p class="form-hint">AI 主动引导对话的程度</p>
        </div>
      </div>
      
      <div class="form-group mt-4">
        <label class="form-label">风格边界</label>
        <p class="form-hint">设置 AI 对话的行为边界</p>
        <div class="boundary-tags">
          <span
            v-for="(boundary, index) in editForm.personality.style_boundaries"
            :key="index"
            class="boundary-tag"
          >
            {{ boundary }}
            <button type="button" class="boundary-tag__remove" @click="removeBoundary(index)">×</button>
          </span>
          <input
            v-model="newBoundary"
            type="text"
            class="form-input form-input--sm boundary-input"
            placeholder="添加边界规则..."
            @keyup.enter="addBoundary"
          />
        </div>
      </div>
    </Card>

    <!-- 版本历史 -->
    <Card class="mt-5" v-if="versions.length > 0">
      <template #header>
        <div class="header-with-action">
          <h3>版本历史</h3>
          <button class="btn btn--ghost btn--sm" @click="$emit('view-all')">查看全部</button>
        </div>
      </template>
      
      <div class="version-list">
        <div
          v-for="(version, index) in versions.slice(0, 5)"
          :key="version.id"
          class="version-item"
          :class="{ 'version-item--current': version.id === persona.id }"
        >
          <div class="version-item__info">
            <span class="version-badge">v{{ version.version }}</span>
            <span class="version-date">{{ formatTime(version.created_at) }}</span>
          </div>
          <div class="version-item__params">
            <span class="param-chip">{{ toneLabel(version.personality.tone) }}</span>
            <span class="param-chip">{{ lengthLabel(version.personality.reply_length) }}</span>
          </div>
        </div>
        <div v-if="versions.length === 0" class="empty-versions">
          <p>暂无版本历史</p>
        </div>
      </div>
    </Card>

    <!-- 预览区域 -->
    <Card class="mt-5">
      <template #header>
        <h3>效果预览</h3>
      </template>
      
      <div class="preview-box">
        <div class="preview-message preview-message--user">
          <span class="message-label">用户</span>
          <p>{{ previewInput || '输入消息查看效果...' }}</p>
        </div>
        <div class="preview-message preview-message--ai">
          <span class="message-label">AI</span>
          <p class="preview-content">{{ previewOutput || generatePreview() }}</p>
        </div>
      </div>
      
      <div class="form-group mt-4">
        <label class="form-label">测试输入</label>
        <textarea
          v-model="previewInput"
          class="form-textarea"
          placeholder="输入测试消息..."
          rows="2"
        ></textarea>
      </div>
    </Card>

    <!-- 操作按钮 -->
    <div class="actions mt-5">
      <button class="btn btn--primary" :disabled="saving" @click="$emit('save')">
        {{ saving ? '保存中...' : '保存修改' }}
      </button>
      <button class="btn btn--ghost ml-2" @click="$emit('clone')">克隆为新版</button>
      <button class="btn btn--ghost ml-2" @click="$emit('delete')">删除</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import Card from '../common/Card.vue'
import type { Persona } from '@/api/types'

const props = defineProps<{
  persona: Persona
  versions?: Persona[]
}>()

const emit = defineEmits<{
  (e: 'save'): void
  (e: 'clone'): void
  (e: 'delete'): void
  (e: 'view-all'): void
}>()

const availableIcons = ['🎭', '💬', '👤', '🤖', '💡', '🎯', '⚡', '🔧', '📝', '🎨']

const editForm = ref({
  name: props.persona.name,
  description: props.persona.description || '',
  icon: props.persona.icon || '🎭',
  personality: { ...props.persona.personality },
})

const newBoundary = ref('')
const saving = ref(false)
const versions = ref<Persona[]>(props.versions || [])
const previewInput = ref('')
const previewOutput = ref('')

watch(() => props.persona, (newPersona) => {
  editForm.value = {
    name: newPersona.name,
    description: newPersona.description || '',
    icon: newPersona.icon || '🎭',
    personality: { ...newPersona.personality },
  }
}, { deep: true })

function addBoundary(): void {
  if (newBoundary.value.trim()) {
    editForm.value.personality.style_boundaries.push(newBoundary.value.trim())
    newBoundary.value = ''
  }
}

function removeBoundary(index: number): void {
  editForm.value.personality.style_boundaries.splice(index, 1)
}

function generatePreview(): string {
  const tone = editForm.value.personality.tone
  const length = editForm.value.personality.reply_length
  
  const responses: Record<string, Record<string, string>> = {
    professional: {
      concise: '感谢您的咨询，我将为您提供专业的解答。',
      balanced: '您好！很高兴为您服务。我将基于专业知识为您提供详细的解答，如有其他问题请随时告知。',
      detailed: '尊敬的客户，感谢您选择我们的服务。作为专业的客服人员，我将为您提供全方位的支持。以下是详细说明...',
    },
    friendly: {
      concise: '嗨！很高兴见到你～有什么我可以帮你的吗？😊',
      balanced: '嘿！你好呀！✨ 很高兴认识你～有什么我可以帮你的吗？别客气，尽管问！',
      detailed: '哈喽！超级开心见到你！🎉 我是你的专属助手，会尽我所能帮助你～ 你可以问我任何问题，我会用最温暖的方式回答你！',
    },
    casual: {
      concise: '嗯，这个问题可以的，我来帮你看看。',
      balanced: '这事儿吧，我跟你说哈，其实挺简单的...',
      detailed: '哎说到这个啊，我给你详细讲讲。首先呢，咱们得这么看...',
    },
  }
  
  const toneMap = responses[tone] ?? responses.professional
  const responseMap = toneMap?.[length] ?? toneMap?.concise ?? ''
  return responseMap || ''
}

function formatTime(time: string): string {
  return new Date(time).toLocaleString('zh-CN')
}

function toneLabel(tone: string): string {
  const map: Record<string, string> = {
    professional: '专业',
    friendly: '友好',
    casual: '随意',
  }
  return map[tone] || tone
}

function lengthLabel(length: string): string {
  const map: Record<string, string> = {
    concise: '简洁',
    balanced: '适中',
    detailed: '详细',
  }
  return map[length] || length
}
</script>

<style scoped>
.required {
  color: var(--color-error);
}

.form-hint {
  display: block;
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
  margin-top: var(--spacing-1);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--spacing-4);
}

.icon-picker {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-2);
}

.icon-btn {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  border: 2px solid var(--color-border);
  border-radius: var(--radius-md);
  background: var(--color-bg-primary);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.icon-btn:hover {
  border-color: var(--color-primary);
  transform: scale(1.1);
}

.icon-btn--active {
  border-color: var(--color-primary);
  background: var(--color-primary-light);
}

.boundary-tags {
  display: flex;
  flex-wrap: wrap;
  gap: var(--spacing-2);
  margin-top: var(--spacing-2);
}

.boundary-tag {
  display: inline-flex;
  align-items: center;
  gap: var(--spacing-1);
  padding: var(--spacing-1) var(--spacing-2);
  background: var(--color-bg-tertiary);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-sm);
}

.boundary-tag__remove {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--color-text-muted);
  font-size: var(--font-size-lg);
  line-height: 1;
  padding: 0;
}

.boundary-tag__remove:hover {
  color: var(--color-error);
}

.boundary-input {
  flex: 1;
  min-width: 150px;
}

.header-with-action {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.version-list {
  max-height: 300px;
  overflow-y: auto;
}

.version-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--spacing-3);
  border-radius: var(--radius-md);
  margin-bottom: var(--spacing-2);
  background: var(--color-bg-secondary);
}

.version-item--current {
  background: var(--color-primary-light);
  border: 1px solid var(--color-primary);
}

.version-item__info {
  display: flex;
  align-items: center;
  gap: var(--spacing-2);
}

.version-badge {
  font-size: var(--font-size-sm);
  font-weight: var(--font-weight-semibold);
  color: var(--color-primary);
}

.version-date {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.version-item__params {
  display: flex;
  gap: var(--spacing-2);
}

.param-chip {
  font-size: var(--font-size-xs);
  padding: var(--spacing-1) var(--spacing-2);
  background: var(--color-bg-primary);
  border-radius: var(--radius-sm);
  color: var(--color-text-secondary);
}

.empty-versions {
  text-align: center;
  padding: var(--spacing-6);
  color: var(--color-text-muted);
}

.preview-box {
  background: var(--color-bg-secondary);
  border-radius: var(--radius-lg);
  padding: var(--spacing-4);
  display: flex;
  flex-direction: column;
  gap: var(--spacing-3);
}

.preview-message {
  display: flex;
  flex-direction: column;
  gap: var(--spacing-1);
}

.preview-message--user {
  align-items: flex-end;
}

.preview-message--ai {
  align-items: flex-start;
}

.message-label {
  font-size: var(--font-size-xs);
  color: var(--color-text-muted);
}

.preview-content {
  background: var(--color-primary-light);
  padding: var(--spacing-3);
  border-radius: var(--radius-lg);
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
  max-width: 80%;
}

.actions {
  display: flex;
  align-items: center;
}

.ml-2 {
  margin-left: var(--spacing-2);
}

.mt-5 {
  margin-top: var(--spacing-5);
}
</style>
