<template>
  <div class="page-container">
    <PageHeader
      title="Prompt 预览弹窗（Demo）"
      description="P1-002-H 组件验收 · mock 数据"
      show-back
    />
    <div class="demo-note">
      <span>🧪 Demo 模式：数据为本地 mock，用于视觉验收（组件代码与生产一致）。</span>
    </div>

    <div class="demo-bar">
      <button
        class="btn btn--primary"
        @click="dialogOpen = true"
      >
        打开预览弹窗
      </button>
      <span class="demo-bar__hint">
        必填变量：user_name / surname · 可选变量：interest / word_count
      </span>
    </div>

    <PromptPreviewDialog
      v-model:open="dialogOpen"
      title="预览 Prompt 渲染结果"
      :content="demoContent"
      :variables="demoVariables"
      @copy="onCopied"
    />

    <div v-if="copiedText" class="copy-proof">
      <div class="copy-proof__label">✓ 复制成功，剪贴板内容：</div>
      <pre class="copy-proof__text">{{ copiedText }}</pre>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import PageHeader from '@/components/common/PageHeader.vue'
import PromptPreviewDialog from '@/components/prompt/PromptPreviewDialog.vue'
import type { VariableDef } from '@/api/types'

const dialogOpen = ref(true)
const copiedText = ref('')

function onCopied(payload: { text: string }) {
  copiedText.value = payload.text
}

// mock 数据（对齐 PRD 附录 10.1 变量语法示例）
const demoContent = `你是一位家谱专家。请为{{user_name}}介绍{{surname}}姓氏的起源。

背景信息：
- 姓氏：{{surname}}
- 用户姓名：{{user_name}}
- 兴趣点：{{interest}}（可选）

请生成一段通俗易懂的介绍，字数在{{word_count}}字以内。`

const demoVariables: VariableDef[] = [
  { name: 'user_name', description: '用户姓名', required: true },
  { name: 'surname', description: '姓氏', required: true },
  {
    name: 'interest',
    description: '兴趣点',
    required: false,
    defaultValue: '姓氏起源',
  },
  {
    name: 'word_count',
    description: '字数上限',
    required: false,
    defaultValue: '500',
  },
]
</script>

<style scoped>
.demo-note {
  background: var(--color-info-light);
  color: var(--color-info);
  border: 1px solid var(--color-info);
  border-radius: var(--radius-md);
  padding: 10px 14px;
  font-size: 13px;
  margin-bottom: 16px;
}

.demo-bar {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.demo-bar__hint {
  font-size: 12px;
  color: var(--color-text-muted);
}

.copy-proof {
  margin-top: 20px;
}

.copy-proof__label {
  font-size: 13px;
  font-weight: 500;
  color: var(--color-success);
  margin-bottom: 8px;
}

.copy-proof__text {
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 12px;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  margin: 0;
}
</style>
