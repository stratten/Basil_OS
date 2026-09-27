interface LocalFileStepProps {
  filePath: string
  onBrowse: () => void
  fileValidationError: string | null
  isFetchingMetadata: boolean
  metadataError: string | null
  extractedModelName: string | null
  extractedArchitecture: string | null
  extractedContextWindow: number | null
}

function LocalFileIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7h7l2 2h9v9H3V7Z" /><path d="M3 9h18" /></svg>
}

function FileSelectedIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="m8.5 12 2.3 2.3 4.8-5" /></svg>
}

export function LocalFileStep({
  filePath, onBrowse, fileValidationError, isFetchingMetadata, metadataError,
  extractedModelName, extractedArchitecture, extractedContextWindow,
}: LocalFileStepProps) {
  return (
    <div className="custom-models-wizard-step">
      <h4 className="custom-models-wizard-step-heading">Select Local GGUF File</h4>
      <p className="custom-models-wizard-step-introduction">Choose a GGUF file stored on this Mac. Basil will inspect its metadata before continuing.</p>

      <div className="custom-models-local-file-picker">
        <div className="custom-models-local-file-picker-header">
          <span className="custom-models-local-file-picker-icon"><LocalFileIcon /></span>
          <div>
            <strong>{filePath ? 'Model file selected' : 'No model file selected'}</strong>
            <span>Supported format: .gguf</span>
          </div>
          <button type="button" className="custom-models-action-button custom-models-local-file-browse-button" onClick={onBrowse}>
            {filePath ? 'Choose another file' : 'Browse files'}
          </button>
        </div>
        {filePath && <div className="custom-models-local-file-path-card"><FileSelectedIcon /><p className="custom-models-local-file-path">{filePath}</p></div>}
      </div>

      {fileValidationError && <p className="custom-models-error-text" role="alert">{fileValidationError}</p>}
      {isFetchingMetadata && <p className="custom-models-status" role="status">Extracting model metadata...</p>}
      {metadataError && <p className="custom-models-error-text" role="alert">{metadataError}</p>}

      {(extractedModelName || extractedArchitecture || extractedContextWindow) && !isFetchingMetadata && (
        <div className="custom-models-metadata-preview">
          {extractedModelName && <span>Model: {extractedModelName}</span>}
          {extractedArchitecture && <span>Architecture: {extractedArchitecture}</span>}
          {extractedContextWindow && <span>Context: {extractedContextWindow.toLocaleString()} tokens</span>}
        </div>
      )}
    </div>
  )
}
