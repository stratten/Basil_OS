import type { SetupInlineVisual } from '@/types'
import AnimatedBubble from '../../../../AgentTaskResult/src/components/AnimatedBubble'

/*
 * Inline conversation card that renders one curated setup visual the
 * agent surfaced via show_setup_visual. Sibling of
 * InlineEmailContextCard and InlineDillDraftCard — same eyebrow +
 * heading + body block rhythm — so the conversation reads with a
 * consistent visual language as the user's eye moves across cards.
 *
 * Rendering shapes, switched off `visual.kind`:
 *
 *   - 'icon_pair' (e.g. menu bar idle vs recording): both web_path
 *     and secondary_web_path render as compact icon tiles under a
 *     single caption.
 *
 *   - 'bubble_sequence' (e.g. ready/listening/working): web-rendered
 *     status bubbles reuse the AgentTask bubble implementation.
 *
 *   - 'composite' (screenshot comparisons): both web_path and
 *     secondary_web_path render side by side under a single caption.
 *
 *   - 'screenshot' (e.g. an inbox or summary view): a single
 *     full-bleed image with a caption beneath.
 *
 *   - 'icon' (e.g. a status indicator): a small inline image with
 *     the caption laid out next to it rather than below, so the
 *     card doesn't take up disproportionate vertical space.
 *
 * The card is read-only; the agent decides when to show it and the
 * user can ignore it freely.
 */

interface Props {
  visual: SetupInlineVisual
}

const BUBBLE_SEQUENCE_STATES = [
  {
    label: 'Ready',
    description: 'Green means Basil is available.',
    mode: 'ambient',
    baseColor: 'var(--ready-base, #22c55e)',
    accentColor: 'var(--ready-accent, #bbf7d0)',
  },
  {
    label: 'Listening',
    description: 'Red means Basil is listening or recording.',
    mode: 'audioResponsive',
    baseColor: 'var(--recording-base, #ef4444)',
    accentColor: 'var(--recording-accent, #fecaca)',
    audioLevel: 0.65,
  },
  {
    label: 'Working',
    description: 'Purple means Basil is working on your request.',
    mode: 'processing',
    baseColor: 'var(--processing-base, #7c3aed)',
    accentColor: 'var(--processing-accent, #ddd6fe)',
  },
] as const

export function InlineSetupVisualCard({ visual }: Props) {
  const isComposite = visual.kind === 'composite' && !!visual.secondaryWebPath
  const isIconPair = visual.kind === 'icon_pair' && !!visual.secondaryWebPath
  const isBubbleSequence = visual.kind === 'bubble_sequence'
  const isIcon = visual.kind === 'icon'

  const stateClass = isComposite
    ? 'kind-composite'
    : isIconPair
      ? 'kind-icon-pair'
      : isBubbleSequence
        ? 'kind-bubble-sequence'
        : isIcon
          ? 'kind-icon'
          : 'kind-screenshot'

  return (
    <article
      className={`inline-setup-visual-card ${stateClass}`}
      aria-label={visual.alt}
    >
      <header className="inline-setup-visual-header">
        <span className="inline-setup-visual-eyebrow">Reference</span>
      </header>

      {isBubbleSequence ? (
        <BubbleSequenceVisual caption={visual.caption} />
      ) : isIcon ? (
        <div className="inline-setup-visual-icon-row">
          <img
            className="inline-setup-visual-icon"
            src={visual.webPath}
            alt={visual.alt}
          />
          <p className="inline-setup-visual-caption">{visual.caption}</p>
        </div>
      ) : isComposite || isIconPair ? (
        <>
          <div className={isIconPair
            ? 'inline-setup-visual-icon-pair'
            : 'inline-setup-visual-composite'}
          >
            <img
              className="inline-setup-visual-image"
              src={visual.webPath}
              alt={visual.alt}
            />
            <img
              className="inline-setup-visual-image"
              src={visual.secondaryWebPath ?? ''}
              alt={visual.secondaryAlt ?? visual.alt}
            />
          </div>
          <p className="inline-setup-visual-caption">{visual.caption}</p>
        </>
      ) : (
        <>
          <img
            className="inline-setup-visual-image"
            src={visual.webPath}
            alt={visual.alt}
          />
          <p className="inline-setup-visual-caption">{visual.caption}</p>
        </>
      )}
    </article>
  )
}

function BubbleSequenceVisual({ caption }: { caption: string }) {
  return (
    <>
      <div
        className="inline-setup-bubble-sequence"
        aria-label="Basil bubble status states"
      >
        {BUBBLE_SEQUENCE_STATES.map((state) => (
          <div className="inline-setup-bubble-state" key={state.label}>
            <div className="inline-setup-bubble-preview" aria-hidden="true">
              <AnimatedBubble
                size={72}
                mode={state.mode}
                baseColor={state.baseColor}
                accentColor={state.accentColor}
                audioLevel={'audioLevel' in state ? state.audioLevel : undefined}
              />
            </div>
            <span className="inline-setup-bubble-label">{state.label}</span>
            <p className="inline-setup-bubble-description">{state.description}</p>
          </div>
        ))}
      </div>
      <p className="inline-setup-visual-caption">{caption}</p>
    </>
  )
}
