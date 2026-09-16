<template>
  <div class="page-container">
    <PageHeader title="Prompt 版本历史（Demo）" description="P1-002-I 组件验收 · mock 数据" show-back />
    <div class="demo-note">
      <span>🧪 Demo 模式：通过 apiClient 注入 mock 数据，用于视觉验收（组件代码与生产一致，不污染共享 API）。</span>
    </div>

    <PromptVersionHistory
      v-if="show"
      :template-id="'demo-template'"
      template-name="家族故事生成"
      :api-client="mockApi"
      @close="show = false"
      @rolled-back="onRolledBack"
    />

    <button v-else class="btn btn--primary" @click="show = true">重新打开版本历史</button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import PageHeader from '@/components/common/PageHeader.vue'
import PromptVersionHistory from '@/components/prompts/PromptVersionHistory.vue'
import type { PromptTemplateVersion } from '@/api/types'

const show = ref(true)

// mock 数据（三版本，模拟 PRD 场景）
const baseContent = `你是一位家谱专家。请为{{user_name}}介绍{{surname}}姓氏的起源。

背景信息：
- 姓氏：{{surname}}
- 用户姓名：{{user_name}}
- 兴趣点：{{interest}}（可选）

请生成一段通俗易懂的介绍，字数在{{word_count}}字以内。`

const initialVersions: PromptTemplateVersion[] = [
  {
    version: 3,
    content: `你是一位家谱专家。请为{{user_name}}介绍{{surname}}姓氏的起源。

开场问候：你好，{{user_name}}！

背景信息：
- 姓氏：{{surname}}
- 用户姓名：{{user_name}}
- 兴趣点：{{interest}}（可选）
- 语气：温暖、亲切

请生成一段通俗易懂的介绍，字数在{{word_count}}字以内。`,
    variables: [
      { name: 'user_name', description: '用户姓名', required: true },
      { name: 'surname', description: '姓氏', required: true },
      { name: 'interest', description: '兴趣点', required: false, defaultValue: '姓氏起源' },
      { name: 'word_count', description: '字数上限', required: false, defaultValue: '300' },
    ],
    changed_at: '2026-09-13T10:00:00Z',
    changed_by: 'admin',
    change_note: '优化开头问候语',
  },
  {
    version: 2,
    content: baseContent,
    variables: [
      { name: 'user_name', description: '用户姓名', required: true },
      { name: 'surname', description: '姓氏', required: true },
      { name: 'interest', description: '兴趣点', required: false },
      { name: 'word_count', description: '字数上限', required: false, defaultValue: '300' },
    ],
    changed_at: '2026-09-12T15:30:00Z',
    changed_by: 'admin',
  },
  {
    version: 1,
    content: `你是家谱助手。请为{{user_name}}介绍{{surname}}姓氏的起源。

请生成一段介绍。`,
    variables: [
      { name: 'user_name', description: '用户姓名', required: true },
      { name: 'surname', description: '姓氏', required: true },
    ],
    changed_at: '2026-09-11T09:00:00Z',
    changed_by: 'admin',
    change_note: '初始版本',
  },
]

// 模拟回滚产生新版本（本地 mock 数据源）
let mockVersions: PromptTemplateVersion[] = initialVersions

function onRolledBack() {
  const max = Math.max(...mockVersions.map((v) => v.version))
  const target = mockVersions.find((v) => v.version === 2)
  if (!target) return
  mockVersions = [
    {
      ...target,
      version: max + 1,
      changed_at: new Date().toISOString(),
      changed_by: 'admin',
      change_note: `回滚自 v${target.version}`,
    },
    ...mockVersions,
  ]
}

// 注入 mock API（通过组件的 apiClient prop，不污染共享 promptApi）
const mockApi = {
  versions: async () => mockVersions,
  rollback: async (_id: string, version: number) => {
    void version
  },
}
</script>

<style scoped>
.demo-note {
  padding: 10px 14px;
  border-radius: var(--radius-md);
  background: var(--color-warning-light);
  color: var(--color-warning);
  font-size: 13px;
  margin-bottom: var(--spacing-4);
}
</style>
