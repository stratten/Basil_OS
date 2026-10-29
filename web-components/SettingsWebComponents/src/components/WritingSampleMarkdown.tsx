import { useMemo, type MouseEvent } from 'react'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { CHAT_MARKDOWN_PURIFY_OPTIONS, normalizeMarkdownBullets } from '@shared/markdownSafety'

marked.setOptions({ gfm: true, breaks: true })

/** Mirrors AssistantSession's markdownToHTML so saved samples read the same way they did in the result view. */
export function writingSampleMarkdownToHTML(markdown: string): string {
  const normalized = normalizeMarkdownBullets(markdown)
  return DOMPurify.sanitize(marked.parse(normalized) as string, CHAT_MARKDOWN_PURIFY_OPTIONS)
}

// Links stay inert: following one would navigate the Settings web view away from the app.
function suppressLinkNavigation(event: MouseEvent<HTMLDivElement>) {
  if ((event.target as HTMLElement).closest('a')) event.preventDefault()
}

export function WritingSampleMarkdown({ content, collapsed }: { content: string; collapsed: boolean }) {
  const html = useMemo(() => writingSampleMarkdownToHTML(content), [content])
  return (
    <div
      className={collapsed ? 'writing-examples-list-preview writing-examples-markdown writing-examples-markdown-collapsed' : 'writing-examples-list-preview writing-examples-markdown'}
      dangerouslySetInnerHTML={{ __html: html }}
      onClick={suppressLinkNavigation}
    />
  )
}
