import type { DiffLine, DiffType } from '@/api/types'

/**
 * 基于 LCS 的行级 diff（用于 Prompt 版本对比）。
 * 输入两份文本，输出逐行 diff：unchanged / added / removed / modified。
 * modified 为对「位置相同但内容不同」的行做的启发式配对，便于高亮展示。
 */
export function diffLines(oldText: string, newText: string): DiffLine[] {
  const oldLines = oldText.split('\n')
  const newLines = newText.split('\n')

  // LCS 动态规划表
  const m = oldLines.length
  const n = newLines.length
  const dp: number[][] = Array.from({ length: m + 1 }, () =>
    new Array<number>(n + 1).fill(0),
  )
  for (let i = m - 1; i >= 0; i--) {
    const row = dp[i]
    if (!row) continue
    const nextRow = dp[i + 1]
    const nextLeft = oldLines[i] ?? ''
    for (let j = n - 1; j >= 0; j--) {
      const nextNew = newLines[j] ?? ''
      row[j] =
        nextLeft === nextNew
          ? (nextRow ? nextRow[j + 1] ?? 0 : 0) + 1
          : Math.max(nextRow ? nextRow[j] ?? 0 : 0, row[j + 1] ?? 0)
    }
  }

  // 回溯得到对齐序列
  type SeqItem =
    | { kind: 'equal'; oldIndex: number; newIndex: number }
    | { kind: 'old'; index: number }
    | { kind: 'new'; index: number }
  const seq: SeqItem[] = []
  let i = 0
  let j = 0
  while (i < m && j < n) {
    const oldLine = oldLines[i] ?? ''
    const newLine = newLines[j] ?? ''
    if (oldLine === newLine) {
      seq.push({ kind: 'equal', oldIndex: i, newIndex: j })
      i++
      j++
    } else {
      const down = dp[i + 1]?.[j] ?? 0
      const right = dp[i]?.[j + 1] ?? 0
      if (down >= right) {
        seq.push({ kind: 'old', index: i })
        i++
      } else {
        seq.push({ kind: 'new', index: j })
        j++
      }
    }
  }
  while (i < m) {
    seq.push({ kind: 'old', index: i })
    i++
  }
  while (j < n) {
    seq.push({ kind: 'new', index: j })
    j++
  }

  // 组装 DiffLine：相邻的删除块与新增块按位置启发式配对为 modified
  const result: DiffLine[] = []
  let k = 0
  while (k < seq.length) {
    const item = seq[k]
    if (!item) break

    if (item.kind === 'equal') {
      result.push({
        type: 'unchanged',
        oldLine: item.oldIndex + 1,
        newLine: item.newIndex + 1,
        oldContent: oldLines[item.oldIndex] ?? '',
        newContent: newLines[item.newIndex] ?? '',
      })
      k++
      continue
    }

    // 收集连续的删除块
    const removed: Array<{ index: number; content: string }> = []
    let p = k
    while (p < seq.length) {
      const cur = seq[p]
      if (!cur || cur.kind !== 'old') break
      removed.push({ index: cur.index, content: oldLines[cur.index] ?? '' })
      p++
    }
    // 收集紧随的新增块
    const added: Array<{ index: number; content: string }> = []
    while (p < seq.length) {
      const cur = seq[p]
      if (!cur || cur.kind !== 'new') break
      added.push({ index: cur.index, content: newLines[cur.index] ?? '' })
      p++
    }

    // 启发式：数量相等时按位置配对为 modified，余量分别为 removed / added
    const pairCount = Math.min(removed.length, added.length)
    if (removed.length === added.length) {
      for (let q = 0; q < removed.length; q++) {
        const r = removed[q]
        const a = added[q]
        if (r && a) {
          result.push({
            type: 'modified',
            oldLine: r.index + 1,
            newLine: a.index + 1,
            oldContent: r.content,
            newContent: a.content,
          })
        }
      }
    } else {
      for (let q = 0; q < pairCount; q++) {
        const r = removed[q]
        const a = added[q]
        if (r && a) {
          result.push({
            type: 'modified',
            oldLine: r.index + 1,
            newLine: a.index + 1,
            oldContent: r.content,
            newContent: a.content,
          })
        }
      }
      for (let q = pairCount; q < removed.length; q++) {
        const r = removed[q]
        if (r) {
          result.push({
            type: 'removed',
            oldLine: r.index + 1,
            oldContent: r.content,
          })
        }
      }
      for (let q = pairCount; q < added.length; q++) {
        const a = added[q]
        if (a) {
          result.push({
            type: 'added',
            newLine: a.index + 1,
            newContent: a.content,
          })
        }
      }
    }
    k = p
  }

  return result
}

export function diffTypeLabel(type: DiffType): string {
  switch (type) {
    case 'added':
      return '新增'
    case 'removed':
      return '删除'
    case 'modified':
      return '修改'
    default:
      return '未变更'
  }
}

/** 统计 diff 中的变化行数（不含未变更） */
export function diffChangeCount(diff: DiffLine[]): number {
  return diff.filter((l) => l.type !== 'unchanged').length
}
