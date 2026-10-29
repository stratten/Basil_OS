import { useState } from 'react'
import type { CustomModelSummary } from '../../types'

const HANDLER_DISPLAY_NAMES: Record<string, string> = {
  openai_compatible: 'OpenAI-Compatible',
  anthropic_compatible: 'Anthropic-Compatible',
  llama_cpp: 'Local GGUF Model',
}

type ModelIconKind = 'local' | 'remote' | 'download' | 'connection' | 'edit' | 'delete'

function ModelIcon({ kind }: { kind: ModelIconKind }) {
  if (kind === 'local') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M7 9h10M7 13h6" /></svg>
  }
  if (kind === 'remote') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="M4 12h16M12 4c2 2.2 3 5 3 8s-1 5.8-3 8M12 4c-2 2.2-3 5-3 8s1 5.8 3 8" /></svg>
  }
  if (kind === 'download') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v10M8 10l4 4 4-4M5 19h14" /></svg>
  }
  if (kind === 'connection') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="m8.5 12.2 2.2 2.2 4.8-5" /></svg>
  }
  if (kind === 'edit') {
    return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 16.5V20h3.5L18.3 9.2l-3.5-3.5L4 16.5Z" /><path d="m13.8 6.7 3.5 3.5" /></svg>
  }
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5" /></svg>
}

interface CustomModelRowProps {
  model: CustomModelSummary
  isDeleting: boolean
  isDownloading: boolean
  liveDownload: { progress: number; status: string } | null
  connectionTestResult: { success: boolean; message: string } | null
  onEdit: () => void
  onDelete: (deleteFiles: boolean, clearHFCache: boolean) => void
  onDownload: () => void
  onTestConnection: () => void
}

export function CustomModelRow({
  model, isDeleting, isDownloading, liveDownload, connectionTestResult, onEdit, onDelete, onDownload, onTestConnection,
}: CustomModelRowProps) {
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const handlerLabel = HANDLER_DISPLAY_NAMES[model.handler] ?? model.handler
  const progress = liveDownload?.progress ?? model.downloadProgress
  const progressPercent = progress !== undefined ? Math.round(progress * 100) : null

  return (
    <li className="custom-models-row">
      <div className="custom-models-row-layout">
        <span className="custom-models-row-kind-icon" title={model.isLocal ? 'Local model' : 'Remote model'}>
          <ModelIcon kind={model.isLocal ? 'local' : 'remote'} />
        </span>
        <div className="custom-models-row-main">
        <div className="custom-models-row-title">
          <span className="custom-models-row-name">{model.displayName}</span>
          <span className="custom-models-row-handler-badge">{handlerLabel}</span>
        </div>

        {model.isLocal ? (
          model.modelPath ? (
            <p className="custom-models-row-location">{model.modelPath}</p>
          ) : model.downloadUrl ? (
            <p className="custom-models-row-location">HuggingFace: {model.downloadUrl}</p>
          ) : null
        ) : (
          <p className="custom-models-row-location">{model.baseUrl ?? 'No URL configured'}</p>
        )}

        <div className="custom-models-row-meta">
          {!model.isLocal && model.modelIdentifier && <span>Model: {model.modelIdentifier}</span>}
          <span>{Math.round(model.contextWindow / 1000)}K context</span>
          {model.isLocal && model.fileSizeHuman && <span>{model.fileSizeHuman}</span>}
        </div>

        {connectionTestResult && (
          <p className={connectionTestResult.success ? 'custom-models-connection-result custom-models-connection-result-success' : 'custom-models-connection-result custom-models-connection-result-error'}>
            {connectionTestResult.message}
          </p>
        )}
        </div>
      </div>

      <div className="custom-models-row-actions">
        {model.needsDownload && (
          isDownloading ? (
            <span className="custom-models-download-progress">
              {progressPercent !== null && progressPercent > 0 ? `${progressPercent}%` : 'Starting...'}
            </span>
          ) : (
            <button type="button" className="custom-models-action-button custom-models-download-button" onClick={onDownload}>
              <ModelIcon kind="download" />
              Download
            </button>
          )
        )}
        {!model.isLocal && (
          <button type="button" className="custom-models-action-button custom-models-icon-button" onClick={onTestConnection} aria-label="Test connection" title="Test connection">
            <ModelIcon kind="connection" />
            <span className="custom-models-visually-hidden">Test</span>
          </button>
        )}
        <button type="button" className="custom-models-action-button custom-models-icon-button" onClick={onEdit} aria-label="Edit model" title="Edit model">
          <ModelIcon kind="edit" />
          <span className="custom-models-visually-hidden">Edit</span>
        </button>
        <button
          type="button"
          className="custom-models-action-button custom-models-delete-button custom-models-icon-button"
          onClick={() => setShowDeleteConfirm((current) => !current)}
          disabled={isDeleting}
          aria-label="Delete model"
          title="Delete model"
        >
          {isDeleting ? <span className="custom-models-delete-pending">Deleting...</span> : <><ModelIcon kind="delete" /><span className="custom-models-visually-hidden">Delete</span></>}
        </button>
      </div>

      {showDeleteConfirm && (
        <DeleteConfirmationPanel
          model={model}
          onCancel={() => setShowDeleteConfirm(false)}
          onConfirm={(deleteFiles, clearHFCache) => {
            setShowDeleteConfirm(false)
            onDelete(deleteFiles, clearHFCache)
          }}
        />
      )}
    </li>
  )
}

interface DeleteConfirmationPanelProps {
  model: CustomModelSummary
  onCancel: () => void
  onConfirm: (deleteFiles: boolean, clearHFCache: boolean) => void
}

function DeleteConfirmationPanel({ model, onCancel, onConfirm }: DeleteConfirmationPanelProps) {
  const [deleteFiles, setDeleteFiles] = useState(true)
  const [clearHFCache, setClearHFCache] = useState(true)
  const [showExplanation, setShowExplanation] = useState(false)
  const isHuggingFaceModel = model.isLocal && model.downloadUrl !== null

  return (
    <div className="custom-models-delete-confirm" role="group" aria-label={`Delete ${model.displayName}?`}>
      <p className="custom-models-delete-confirm-title">Delete &ldquo;{model.displayName}&rdquo;?</p>

      {model.isLocal ? (
        <div className="custom-models-delete-confirm-options">
          <label className="custom-models-delete-confirm-checkbox">
            <input type="checkbox" checked={deleteFiles} onChange={(event) => setDeleteFiles(event.target.checked)} />
            Delete model files from disk
          </label>

          {isHuggingFaceModel && (
            <div className="custom-models-delete-confirm-hf-cache">
              <label className="custom-models-delete-confirm-checkbox">
                <input type="checkbox" checked={clearHFCache} onChange={(event) => setClearHFCache(event.target.checked)} />
                Also clear HuggingFace cache
              </label>
              <button
                type="button"
                className="custom-models-delete-confirm-explain-toggle"
                onClick={() => setShowExplanation((current) => !current)}
              >
                What is this? {showExplanation ? '▲' : '▼'}
              </button>
              {showExplanation && (
                <div className="custom-models-delete-confirm-explanation">
                  <p>The HuggingFace cache stores a copy of downloaded model files at:</p>
                  <code>~/.cache/huggingface/</code>
                  <p>Clearing it frees additional disk space but means re-downloading if you add this model again later.</p>
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <p className="custom-models-delete-confirm-body">This will remove the model from your custom models list.</p>
      )}

      <div className="custom-models-delete-confirm-actions">
        <button type="button" className="custom-models-action-button" onClick={onCancel}>Cancel</button>
        <button
          type="button"
          className="custom-models-action-button custom-models-delete-confirm-button"
          onClick={() => onConfirm(model.isLocal ? deleteFiles : false, model.isLocal && isHuggingFaceModel ? clearHFCache : false)}
        >
          Delete
        </button>
      </div>
    </div>
  )
}
