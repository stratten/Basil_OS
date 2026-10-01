import { memo } from 'react'

// Match a leading bullet glyph at the start of a (trimmed) line.
// Accepts hyphen, asterisk, and the U+2022 BULLET character that
// model output frequently emits literally instead of as proper
// markdown. Multi-character glyphs like "* " and "- " are covered
// by the same regex via \s+.
const LEADING_BULLET = /^[-*\u2022]\s+/

// Match an inline run of " • " (or " - ") that the model sometimes
// uses to chain list items on one line instead of using newlines.
// Two-or-more occurrences in the same block is the trigger for
// splitting back into proper <li> elements; one occurrence is
// usually intentional prose (e.g. a parenthetical) and is left
// alone. Hyphens require surrounding spaces to avoid eating "—"
// em-dashes or compound words.
const INLINE_BULLET_SPLIT = /\s+[\u2022]\s+|\s+-\s+(?=\S)/g

export const SetupConversationMarkdown = memo(function SetupConversationMarkdown({ content }: { content: string }) {
  const blocks = content.split(/\n{2,}/).filter(block => block.trim().length > 0)

  return (
    <>
      {blocks.map((block, index) => renderMarkdownBlock(block, index))}
    </>
  )
})

function renderMarkdownBlock(block: string, blockIndex: number) {
  const lines = block.split('\n').filter(line => line.trim().length > 0)

  // Case A: every line in the block is a bulleted line. Standard
  // markdown list rendering. Preserves the existing behavior for
  // any prompt that already produces newline-separated `- item`
  // bullets and adds U+2022 to the accepted leading-glyph set.
  if (lines.length > 0 && lines.every(line => LEADING_BULLET.test(line.trim()))) {
    return (
      <ul key={`md-${blockIndex}`} style={{ margin: '8px 0 0', paddingLeft: 20 }}>
        {lines.map((line, lineIndex) => (
          <li key={`md-${blockIndex}-${lineIndex}`}>
            {renderInlineMarkdown(line.trim().replace(LEADING_BULLET, ''))}
          </li>
        ))}
      </ul>
    )
  }

  // Case B: the block contains inline bullet runs (the symptom we
  // actually saw — the setup agent put "intro: • item • item • item"
  // on one line). Two or more inline bullet separators trip the
  // recovery path. We split the block on those separators, treat
  // whatever came before the first separator as a prelude paragraph
  // (unless the block itself begins with a bullet), and render the
  // rest as <li> elements. Single-bullet occurrences are left as
  // prose so we don't shred parentheticals.
  const inlineMatches = block.match(INLINE_BULLET_SPLIT)
  if (inlineMatches && inlineMatches.length >= 2) {
    const segments = block.split(INLINE_BULLET_SPLIT).map(segment => segment.trim())
    const blockStartsWithBullet = LEADING_BULLET.test(block.trimStart())
    const prelude = blockStartsWithBullet ? '' : segments[0]
    const items = (blockStartsWithBullet ? segments : segments.slice(1))
      .map(item => item.replace(LEADING_BULLET, '').trim())
      .filter(item => item.length > 0)

    if (items.length > 0) {
      return (
        <div key={`md-${blockIndex}`}>
          {prelude.length > 0 && (
            <p style={{ margin: 0 }}>{renderInlineMarkdown(prelude)}</p>
          )}
          <ul style={{ margin: prelude.length > 0 ? '8px 0 0' : 0, paddingLeft: 20 }}>
            {items.map((item, itemIndex) => (
              <li key={`md-${blockIndex}-${itemIndex}`}>
                {renderInlineMarkdown(item)}
              </li>
            ))}
          </ul>
        </div>
      )
    }
  }

  return (
    <p key={`md-${blockIndex}`}>
      {renderInlineMarkdown(block)}
    </p>
  )
}

function renderInlineMarkdown(content: string) {
  const parts = content.split(/(\*\*[^*]+\*\*)/g)

  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={`${part}-${index}`}>{part.slice(2, -2)}</strong>
    }

    return part
  })
}
