<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const props = defineProps<{ text: string }>()

const html = computed(() => {
  if (!props.text) return ''
  const raw = marked.parse(props.text, { gfm: true, breaks: false }) as string
  return DOMPurify.sanitize(raw)
})
</script>

<template>
  <div class="md" v-html="html"></div>
</template>

<style scoped>
.md {
  color: var(--text-primary);
  font-size: 13.5px;
  line-height: 1.7;
}

.md :deep(h1),
.md :deep(h2),
.md :deep(h3),
.md :deep(h4) {
  margin: 16px 0 8px;
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.3;
  color: var(--text-primary);
}
.md :deep(h1) { font-size: 19px; }
.md :deep(h2) { font-size: 16px; }
.md :deep(h3) { font-size: 14px; }
.md :deep(h4) { font-size: 13px; }
.md :deep(:first-child) { margin-top: 0; }

.md :deep(p) { margin: 8px 0; }

.md :deep(strong) {
  font-weight: 600;
  color: var(--text-primary);
}
.md :deep(em) {
  font-style: italic;
  color: var(--text-secondary);
}

.md :deep(code) {
  font-family: 'JetBrains Mono', 'SF Mono', 'Menlo', monospace;
  background: var(--accent-bg-soft);
  color: var(--accent);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 0.9em;
  letter-spacing: -0.01em;
}

.md :deep(pre) {
  background: var(--surface-deep);
  border: 1px solid var(--border-soft);
  padding: 12px 14px;
  border-radius: 8px;
  overflow-x: auto;
  font-size: 12px;
  margin: 10px 0;
  line-height: 1.55;
}
.md :deep(pre code) {
  background: transparent;
  color: var(--text-on-deep);
  padding: 0;
  font-size: 12px;
}

.md :deep(ul),
.md :deep(ol) {
  margin: 8px 0;
  padding-left: 22px;
}
.md :deep(li) {
  margin: 4px 0;
}

.md :deep(blockquote) {
  margin: 10px 0;
  padding: 6px 14px;
  border-left: 3px solid var(--border-accent);
  background: var(--accent-bg-soft);
  color: var(--text-secondary);
  border-radius: 0 4px 4px 0;
}

.md :deep(hr) {
  border: none;
  border-top: 1px solid var(--border-soft);
  margin: 16px 0;
}

.md :deep(table) {
  border-collapse: collapse;
  margin: 12px 0;
  width: 100%;
  font-size: 12.5px;
  border: 1px solid var(--border-soft);
  border-radius: 6px;
  overflow: hidden;
}
.md :deep(th),
.md :deep(td) {
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-soft);
  text-align: left;
}
.md :deep(th) {
  background: var(--surface-1);
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--text-secondary);
  text-transform: uppercase;
}
.md :deep(tr:last-child td) {
  border-bottom: none;
}
.md :deep(tr:hover td) {
  background: var(--surface-1);
}

.md :deep(a) {
  color: var(--accent);
  text-decoration: underline;
  text-decoration-color: var(--border-accent);
}
.md :deep(a:hover) {
  text-decoration-color: var(--accent);
}
</style>
