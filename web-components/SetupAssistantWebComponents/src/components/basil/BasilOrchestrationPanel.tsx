import { useState } from 'react'

import type { BasilMessage } from '@/types'

interface Props {
  messages: BasilMessage[]
  onUserMessage: (content: string) => void
  isResponding: boolean
  composerEnabled?: boolean
}

export function BasilOrchestrationPanel({
  messages,
  onUserMessage,
  isResponding,
  composerEnabled = true,
}: Props) {
  const [draft, setDraft] = useState('')

  const submitDraft = () => {
    const trimmed = draft.trim()
    if (!trimmed) return
    onUserMessage(trimmed)
    setDraft('')
  }

  return (
    <section className="basil-conversation" aria-label="Basil conversation">
      <div className="basil-panel-header">
        <div>
          <h2>Your setup conversation</h2>
        </div>
      </div>

      <div className="basil-messages">
        {messages.map(message => (
          <article key={message.id} className={`basil-message ${message.role}`}>
            {message.role === 'user' && <span>You</span>}
            <FormattedMessage content={message.content} />
          </article>
        ))}
      </div>

      {composerEnabled && (
        <div className="basil-input-row">
          <textarea
            value={draft}
            onChange={event => setDraft(event.target.value)}
            placeholder="Ask Basil, correct something, or say what you want..."
            rows={3}
          />
          <button
            type="button"
            className="primary-button"
            onClick={submitDraft}
            disabled={isResponding}
          >
            {isResponding ? 'Thinking...' : 'Send'}
          </button>
        </div>
      )}
    </section>
  )
}

function FormattedMessage({ content }: { content: string }) {
  const blocks = formatMessageBlocks(content)

  return (
    <div className="basil-message-content">
      {blocks.map((block, index) => {
        if (block.kind === 'ordered-list') {
          return (
            <ol key={`ordered-${index}`}>
              {block.items.map(item => (
                <li key={item}>{renderInlineText(item)}</li>
              ))}
            </ol>
          )
        }

        return <p key={`paragraph-${index}`}>{renderInlineText(block.text)}</p>
      })}
    </div>
  )
}

type MessageBlock =
  | { kind: 'paragraph'; text: string }
  | { kind: 'ordered-list'; items: string[] }

function formatMessageBlocks(content: string): MessageBlock[] {
  const normalized = content
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/\s+(\d+\.)\s+/g, '\n$1 ')
    .replace(/\s+[-•]\s+/g, '\n- ')
    .trim()

  if (!normalized) {
    return []
  }

  const blocks: MessageBlock[] = []
  let orderedItems: string[] = []

  normalized
    .split(/\n{1,}/)
    .map(line => line.trim())
    .filter(Boolean)
    .forEach(line => {
      const orderedMatch = line.match(/^\d+\.\s+(.*)$/)
      if (orderedMatch) {
        orderedItems.push(orderedMatch[1])
        return
      }

      if (orderedItems.length > 0) {
        blocks.push({ kind: 'ordered-list', items: orderedItems })
        orderedItems = []
      }

      blocks.push({ kind: 'paragraph', text: line.replace(/^[-•]\s+/, '') })
    })

  if (orderedItems.length > 0) {
    blocks.push({ kind: 'ordered-list', items: orderedItems })
  }

  return blocks
}

function renderInlineText(text: string) {
  return text
}

