export const ANSWER_GUIDE_EXAMPLES = [
  'I\'m a freelance designer. Most of my time goes to client email, scheduling, and invoices.',
  'I\'m a product manager with three things on the go: a mobile app launch, a pricing review, and hiring.',
  'Mostly writing and research. I\'d like help summarizing documents and drafting first versions.',
] as const

interface Props {
  onUseExample: (text: string) => void
}

// Shown under the conversation before the user has typed anything. An open question like "what are you working on?" gives no hint of the right level of detail, so this says what a good answer looks like and offers editable starting points.
export function AnswerGuide({ onUseExample }: Props) {
  return (
    <div className="answer-guide" data-testid="answer-guide">
      <p className="answer-guide-lede">
        <strong>Not sure what to say?</strong> A sentence or two is plenty. Describe your role, a short list of what you are working on, or what you hope I can take off your plate. Pick an example to start from, then edit it.
      </p>
      <div className="answer-guide-examples">
        {ANSWER_GUIDE_EXAMPLES.map(example => (
          <button
            key={example}
            type="button"
            className="secondary-button answer-guide-example"
            onClick={() => onUseExample(example)}
          >
            {example}
          </button>
        ))}
      </div>
    </div>
  )
}
