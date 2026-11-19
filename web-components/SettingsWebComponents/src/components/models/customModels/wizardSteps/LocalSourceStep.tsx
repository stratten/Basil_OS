export type LocalSource = 'huggingface' | 'local_file'

function LocalSourceIcon({ source }: { source: LocalSource }) {
  return source === 'huggingface'
    ? <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v10M8 10l4 4 4-4M5 19h14" /></svg>
    : <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7h7l2 2h9v9H3V7Z" /><path d="M3 9h18" /></svg>
}

function SelectedIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="m8.5 12 2.3 2.3 4.8-5" /></svg>
}

interface LocalSourceStepProps {
  localSource: LocalSource
  onSelect: (source: LocalSource) => void
}

export function LocalSourceStep({ localSource, onSelect }: LocalSourceStepProps) {
  return (
    <div className="custom-models-wizard-step">
      <h4 className="custom-models-wizard-step-heading">Where is your model located?</h4>
      <div className="custom-models-selection-cards">
        <button type="button" className={localSource === 'huggingface' ? 'custom-models-selection-card custom-models-selection-card-selected' : 'custom-models-selection-card'} onClick={() => onSelect('huggingface')} aria-pressed={localSource === 'huggingface'}>
          <span className="custom-models-selection-card-icon"><LocalSourceIcon source="huggingface" /></span>
          <span className="custom-models-selection-card-content">
            <span className="custom-models-selection-card-title">Download from HuggingFace</span>
            <span className="custom-models-selection-card-subtitle">Browse a repository and download a GGUF file.</span>
          </span>
          {localSource === 'huggingface' && <span className="custom-models-selection-card-check"><SelectedIcon /></span>}
        </button>
        <button type="button" className={localSource === 'local_file' ? 'custom-models-selection-card custom-models-selection-card-selected' : 'custom-models-selection-card'} onClick={() => onSelect('local_file')} aria-pressed={localSource === 'local_file'}>
          <span className="custom-models-selection-card-icon"><LocalSourceIcon source="local_file" /></span>
          <span className="custom-models-selection-card-content">
            <span className="custom-models-selection-card-title">Use Existing Local File</span>
            <span className="custom-models-selection-card-subtitle">Choose a GGUF file already on this Mac.</span>
          </span>
          {localSource === 'local_file' && <span className="custom-models-selection-card-check"><SelectedIcon /></span>}
        </button>
      </div>
    </div>
  )
}
