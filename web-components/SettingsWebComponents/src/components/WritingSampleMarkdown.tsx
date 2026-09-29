import { useMemo, type MouseEvent } from 'react'
import DOMPurify from 'dompurify'
import { marked } from 'marked'

marked.setOptions({ gfm: true, breaks: true })

/** Mirrors AssistantSession's markdownToHTML so saved samples read the same way they did in the result view. */
export function writingSampleMarkdownToHTML(markdown: string): string {
  const normalized = markdown.replace(/^[•●]\s/gm, '- ')
  return DOMPurify.sanitize(marked.parse(normalized) as string, {
    FORBID_TAGS: ['audio', 'iframe', 'img', 'source', 'style', 'video'],
    FORBID_ATTR: ['style'],
  })
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
