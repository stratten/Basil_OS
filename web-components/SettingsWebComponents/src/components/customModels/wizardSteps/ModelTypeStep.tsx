export type ApiHandlerType = 'openai_compatible' | 'anthropic_compatible'

type ModelTypeIconKind = 'local' | 'remote' | 'openai' | 'anthropic'

function ModelTypeIcon({ kind }: { kind: ModelTypeIconKind }) {
  if (kind === 'local') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M7 9h10M7 13h6" /></svg>
  }
  if (kind === 'remote') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="M4 12h16M12 4c2 2.2 3 5 3 8s-1 5.8-3 8M12 4c-2 2.2-3 5-3 8s1 5.8 3 8" /></svg>
  }
  if (kind === 'openai') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5 14.7 8l5.1 1.2-3.4 4.1.5 5.2-4.9-2.1-4.9 2.1.5-5.2-3.4-4.1L9.3 8 12 3.5Z" /></svg>
  }
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 4 8v8l8 5 8-5V8l-8-5ZM4 8l8 5 8-5M12 13v8" /></svg>
}

interface ModelTypeStepProps {
  isLocal: boolean
  handlerType: ApiHandlerType
  onSelectLocal: () => void
  onSelectApi: (handlerType: ApiHandlerType) => void
}

export function ModelTypeStep({ isLocal, handlerType, onSelectLocal, onSelectApi }: ModelTypeStepProps) {
  return (
    <div className="custom-models-wizard-step">
      <h4 className="custom-models-wizard-step-heading">What type of model would you like to add?</h4>
      <div className="custom-models-selection-cards">
        <button type="button" className={isLocal ? 'custom-models-selection-card custom-models-selection-card-selected' : 'custom-models-selection-card'} onClick={onSelectLocal} aria-pressed={isLocal}>
          <span className="custom-models-selection-card-icon"><ModelTypeIcon kind="local" /></span>
          <span className="custom-models-selection-card-content">
            <span className="custom-models-selection-card-title">Local Model</span>
            <span className="custom-models-selection-card-subtitle">Run a GGUF model locally via llama.cpp</span>
          </span>
        </button>
        <button type="button" className={!isLocal ? 'custom-models-selection-card custom-models-selection-card-selected' : 'custom-models-selection-card'} onClick={() => onSelectApi('openai_compatible')} aria-pressed={!isLocal}>
          <span className="custom-models-selection-card-icon"><ModelTypeIcon kind="remote" /></span>
          <span className="custom-models-selection-card-content">
            <span className="custom-models-selection-card-title">API / Remote Model</span>
            <span className="custom-models-selection-card-subtitle">Connect to an OpenAI or Anthropic-compatible endpoint</span>
          </span>
        </button>
      </div>

      {!isLocal && (
        <fieldset className="custom-models-handler-selector">
          <legend>Choose the API handler</legend>
          <button type="button" className={handlerType === 'openai_compatible' ? 'custom-models-handler-option custom-models-handler-option-selected' : 'custom-models-handler-option'} onClick={() => onSelectApi('openai_compatible')} aria-pressed={handlerType === 'openai_compatible'}>
            <span className="custom-models-handler-option-icon"><ModelTypeIcon kind="openai" /></span>
            <span><strong>OpenAI-Compatible</strong><small>Ollama, LM Studio, vLLM, Together AI, Groq, and similar services.</small></span>
          </button>
          <button type="button" className={handlerType === 'anthropic_compatible' ? 'custom-models-handler-option custom-models-handler-option-selected' : 'custom-models-handler-option'} onClick={() => onSelectApi('anthropic_compatible')} aria-pressed={handlerType === 'anthropic_compatible'}>
            <span className="custom-models-handler-option-icon"><ModelTypeIcon kind="anthropic" /></span>
            <span><strong>Anthropic-Compatible</strong><small>AWS Bedrock, Anthropic proxies, and compatible gateways.</small></span>
          </button>
        </fieldset>
      )}
    </div>
  )
}
