import { FormField, FormSection } from '../FormField'
import { Switch } from '@shared/Switch'
import type { WizardFeature } from '../types'

function ConnectionTestIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8" /><path d="m8.5 12.2 2.2 2.2 4.8-5" /></svg>
}

export interface DetailsStepValues {
  displayName: string
  modelId: string
  description: string
  contextWindow: string
  maxOutputTokens: string
  requiresAuth: boolean
  apiKey: string
  baseUrl: string
  modelIdentifier: string
  features: WizardFeature[]
}

interface DetailsStepProps {
  isLocal: boolean
  values: DetailsStepValues
  onChange: (partial: Partial<DetailsStepValues>) => void
  onToggleFeature: (featureId: string) => void
  canTestConnection: boolean
  onTestConnection: () => void
  isTestingConnection: boolean
  connectionTestResult: { success: boolean; message: string } | null
  isDownloading: boolean
  downloadProgress: number | null
  downloadStatus: string | null
}

export function DetailsStep({
  isLocal, values, onChange, onToggleFeature, canTestConnection, onTestConnection,
  isTestingConnection, connectionTestResult, isDownloading, downloadProgress, downloadStatus,
}: DetailsStepProps) {
  return (
    <div className="custom-models-wizard-step">
      <h4 className="custom-models-wizard-step-heading">Model Details</h4>
      <p className="custom-models-wizard-step-introduction">Review the configuration below. Model details are pre-filled when the selected source provides them.</p>

      <FormSection title="Basic Information">
        <FormField label="Display Name">
          <input type="text" value={values.displayName} onChange={(event) => onChange({ displayName: event.target.value })} />
        </FormField>
        <FormField label="Model ID" hint="Used internally to identify this model.">
          <input type="text" value={values.modelId} onChange={(event) => onChange({ modelId: event.target.value })} />
        </FormField>
        <FormField label="Description (optional)">
          <input type="text" value={values.description} onChange={(event) => onChange({ description: event.target.value })} />
        </FormField>
      </FormSection>

      {!isLocal && (
        <FormSection title="API Endpoint">
          <FormField label="Base URL">
            <input type="text" value={values.baseUrl} onChange={(event) => onChange({ baseUrl: event.target.value })} placeholder="https://api.example.com/v1" />
          </FormField>
          <FormField label="Model Identifier">
            <input type="text" value={values.modelIdentifier} onChange={(event) => onChange({ modelIdentifier: event.target.value })} placeholder="gpt-4o" />
          </FormField>
        </FormSection>
      )}

      <FormSection title="Context Limits">
        <div className="custom-models-context-limit-grid">
          <FormField label="Context Window (tokens)">
            <input type="number" value={values.contextWindow} onChange={(event) => onChange({ contextWindow: event.target.value })} />
          </FormField>
          <FormField label="Max Output Tokens">
            <input type="number" value={values.maxOutputTokens} onChange={(event) => onChange({ maxOutputTokens: event.target.value })} />
          </FormField>
        </div>
      </FormSection>

      {!isLocal && (
        <FormSection title="Authentication">
          <Switch id="custom-model-requires-api-key" label="Requires API Key" checked={values.requiresAuth} onChange={(checked) => onChange({ requiresAuth: checked })} />
          {values.requiresAuth && (
            <FormField label="API Key" hint="Stored securely. Never displayed again after saving.">
              <input type="password" value={values.apiKey} onChange={(event) => onChange({ apiKey: event.target.value })} autoComplete="off" />
            </FormField>
          )}
        </FormSection>
      )}

      <FormSection title="Features">
        <p className="custom-models-form-section-description">Enable only the capabilities this model supports.</p>
        {values.features
          .filter((feature) => feature.id === 'streaming' || feature.id === 'system_prompts')
          .map((feature) => (
            <Switch
              key={feature.id}
              id={`custom-model-feature-${feature.id}`}
              label={feature.name}
              checked={feature.isEnabled}
              onChange={() => onToggleFeature(feature.id)}
            />
          ))}
      </FormSection>

      {!isLocal && (
        <FormSection title="Connection Test">
          <div className="custom-models-connection-test">
            <button type="button" className="custom-models-action-button custom-models-test-connection-button" onClick={onTestConnection} disabled={!canTestConnection || isTestingConnection}>
              <ConnectionTestIcon />
              {isTestingConnection ? 'Testing...' : 'Test Connection'}
            </button>
            {connectionTestResult && (
              <p className={connectionTestResult.success ? 'custom-models-connection-result custom-models-connection-result-success' : 'custom-models-connection-result custom-models-connection-result-error'}>
                {connectionTestResult.message}
              </p>
            )}
          </div>
        </FormSection>
      )}

      {isDownloading && (
        <div className="custom-models-download-status" role="status">
          <div><strong>Downloading model</strong><span>{downloadStatus ?? 'Preparing download'}</span></div>
          <span>{downloadProgress !== null && downloadProgress > 0 ? `${Math.round(downloadProgress * 100)}%` : '...'}</span>
          <div className="custom-models-download-status-track"><span style={{ width: `${Math.max(0, (downloadProgress ?? 0) * 100)}%` }} /></div>
        </div>
      )}
    </div>
  )
}
