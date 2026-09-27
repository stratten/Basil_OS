import type { HFModelMetadataSummary } from '../../../types'
import type { HFFileOption } from '../types'

function RepositorySearchIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="5.5" /><path d="m15 15 4 4" /></svg>
}

interface HuggingFaceStepProps {
  url: string
  onUrlChange: (url: string) => void
  onProbe: () => void
  isProbing: boolean
  probeError: string | null
  ggufFiles: HFFileOption[]
  modelMetadata: HFModelMetadataSummary | null
  selectedFile: string | null
  onSelectFile: (filename: string) => void
  isFetchingMetadata: boolean
  metadataError: string | null
}

export function HuggingFaceStep({
  url, onUrlChange, onProbe, isProbing, probeError, ggufFiles, modelMetadata,
  selectedFile, onSelectFile, isFetchingMetadata, metadataError,
}: HuggingFaceStepProps) {
  return (
    <div className="custom-models-wizard-step">
      <h4 className="custom-models-wizard-step-heading">HuggingFace Repository</h4>
      <p className="custom-models-wizard-step-introduction">Enter a repository URL or owner/repository ID, then choose the GGUF file to download.</p>
      <div className="custom-models-form-field">
        <label className="custom-models-form-field-label" htmlFor="custom-models-hf-url">Repository URL or ID</label>
        <div className="custom-models-hf-url-row">
          <input
            id="custom-models-hf-url"
            type="text"
            value={url}
            placeholder="e.g. TheBloke/Llama-2-7B-GGUF"
            onChange={(event) => onUrlChange(event.target.value)}
          />
          <button type="button" className="custom-models-action-button custom-models-hf-search-button" onClick={onProbe} disabled={!url.trim() || isProbing}>
            <RepositorySearchIcon />
            {isProbing ? 'Searching...' : 'Search'}
          </button>
        </div>
        <p className="custom-models-form-field-hint">For example: TheBloke/Llama-2-7B-GGUF or a full HuggingFace URL.</p>
      </div>

      {probeError && <p className="custom-models-error-text" role="alert">{probeError}</p>}

      {ggufFiles.length > 0 && (
        <div className="custom-models-hf-file-list" role="radiogroup" aria-label="GGUF files">
          <div className="custom-models-hf-file-list-header">
            <p className="custom-models-hf-file-list-heading">Available GGUF files</p>
            <span>{ggufFiles.length} found</span>
          </div>
          {ggufFiles.map((file) => (
            <label key={file.name} className={selectedFile === file.name ? 'custom-models-hf-file-option custom-models-hf-file-option-selected' : 'custom-models-hf-file-option'}>
              <input type="radio" name="hf-gguf-file" checked={selectedFile === file.name} onChange={() => onSelectFile(file.name)} />
              <span className="custom-models-hf-file-content">
                <strong className="custom-models-hf-file-name">{file.name}</strong>
                <span className="custom-models-hf-file-size">{file.sizeHuman ?? 'Size unavailable'}</span>
              </span>
            </label>
          ))}
        </div>
      )}

      {isFetchingMetadata && <p className="custom-models-status" role="status">Extracting model metadata...</p>}
      {metadataError && <p className="custom-models-error-text" role="alert">{metadataError}</p>}

      {modelMetadata && !isFetchingMetadata && (
        <div className="custom-models-metadata-preview">
          {modelMetadata.architecture && <span>Architecture: {modelMetadata.architecture}</span>}
          {modelMetadata.contextWindow && <span>Context: {modelMetadata.contextWindow.toLocaleString()} tokens</span>}
        </div>
      )}
    </div>
  )
}
