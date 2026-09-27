import { useEffect, useRef, useState } from 'react'
import { SettingsSubTabs, type SettingsSubTabDefinition } from '@shared/SettingsSubTabs'
import { notifyConnectionsSettingsReady, onConnectionsEvent } from '../services/connectionsBridge'
import type {
  ConnectionsInitEvent,
  ConnectionsProviderProfileConfigurationEvent,
  ConnectionsSettingsFields,
  ConnectionsSnapshotEvent,
  ConnectionsWorkspaceFolderChosenEvent,
} from '../types'
import { ConnectionsPanel } from '../components/ConnectionsPanel'
import { CallLogPanel } from '../components/CallLogPanel'
import { ProviderProfilesPanel } from '../components/ProviderProfilesPanel'
import '../styles/connections-settings.css'

export type ConnectionsSubTab = 'servers' | 'providerProfiles'

export const CONNECTIONS_SUB_TABS: readonly SettingsSubTabDefinition<ConnectionsSubTab>[] = [
  { id: 'servers', label: 'MCP' },
  { id: 'providerProfiles', label: 'ACP' },
]

function connectionsTabId(id: ConnectionsSubTab): string {
  return `connections-subtab-${id}`
}

function connectionsPanelId(id: ConnectionsSubTab): string {
  return `connections-subpanel-${id}`
}

function extractFields(event: ConnectionsInitEvent | ConnectionsSnapshotEvent): ConnectionsSettingsFields {
  return {
    starterServers: event.starterServers,
    connections: event.connections,
    callLogEntries: event.callLogEntries,
    isLoading: event.isLoading,
    isAddingConnection: event.isAddingConnection,
    isLoadingCallLog: event.isLoadingCallLog,
    errorMessage: event.errorMessage,
    statusMessage: event.statusMessage,
    pendingFlowFriendlyName: event.pendingFlowFriendlyName,
    githubDeviceFlow: event.githubDeviceFlow,
    isPollingGitHubDeviceFlow: event.isPollingGitHubDeviceFlow,
    providerProfiles: event.providerProfiles,
    isLoadingProviderProfiles: event.isLoadingProviderProfiles,
    isMutatingProviderProfiles: event.isMutatingProviderProfiles,
    providerProfilesStatusMessage: event.providerProfilesStatusMessage,
    providerProfilesErrorMessage: event.providerProfilesErrorMessage,
  }
}

export function ConnectionsSettingsApp({ requestedSubTab }: { requestedSubTab?: ConnectionsSubTab } = {}) {
  const [fields, setFields] = useState<ConnectionsSettingsFields | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [subTab, setSubTab] = useState<ConnectionsSubTab>(requestedSubTab ?? 'servers')
  const [configEvent, setConfigEvent] = useState<ConnectionsProviderProfileConfigurationEvent | null>(null)
  const [folderEvent, setFolderEvent] = useState<ConnectionsWorkspaceFolderChosenEvent | null>(null)
  const pendingRef = useRef<string | null>(null)
  pendingRef.current = pendingId

  useEffect(() => {
    if (requestedSubTab) setSubTab(requestedSubTab)
  }, [requestedSubTab])

  useEffect(() => {
    const unsubscribe = onConnectionsEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        setFields(extractFields(event))
        setLoadError(null)
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      if (event.type === 'intentResult' && event.requestId === pendingRef.current) {
        setPendingId(null)
        if (event.status === 'error') {
          setRequestError(event.message ?? 'Something went wrong.')
        } else {
          setRequestError(null)
        }
        return
      }
      if (event.type === 'providerProfileConfiguration') {
        setConfigEvent(event)
        return
      }
      if (event.type === 'workspaceFolderChosen') {
        setFolderEvent(event)
      }
    })
    notifyConnectionsSettingsReady()
    return unsubscribe
  }, [])

  function trackRequest(id: string) {
    setRequestError(null)
    setPendingId(id)
  }

  if (!fields && !loadError) {
    return <p className="connections-settings-status" role="status">Loading connections...</p>
  }

  if (loadError) {
    return (
      <div className="connections-settings-error">
        <p role="alert">{loadError}</p>
        <button type="button" className="secondary-button" onClick={() => notifyConnectionsSettingsReady()}>Retry</button>
      </div>
    )
  }

  const f = fields!

  return (
    <div className="connections-settings-shell">
      <header className="connections-settings-header">
        <h2>Connections</h2>
        <p>Connect remote MCP servers (Linear, GitHub, custom) so the agent can act on them with your authorization.</p>
      </header>

      <SettingsSubTabs
        tabs={CONNECTIONS_SUB_TABS}
        selected={subTab}
        onSelect={setSubTab}
        ariaLabel="Connections sections"
        getTabId={connectionsTabId}
        getPanelId={connectionsPanelId}
      />

      {f.statusMessage && (
        <p className="connections-settings-banner connections-settings-banner-info" role="status">{f.statusMessage}</p>
      )}
      {f.errorMessage && (
        <p className="connections-settings-banner connections-settings-banner-error" role="alert">{f.errorMessage}</p>
      )}
      {requestError && (
        <p className="connections-settings-banner connections-settings-banner-error" role="alert">{requestError}</p>
      )}

      {subTab === 'servers' ? (
        <div id={connectionsPanelId('servers')} role="tabpanel" aria-labelledby={connectionsTabId('servers')}>
          <ConnectionsPanel fields={f} pendingId={pendingId} onTrackRequest={trackRequest} />
          <CallLogPanel entries={f.callLogEntries} isLoading={f.isLoadingCallLog} pendingId={pendingId} onTrackRequest={trackRequest} />
        </div>
      ) : (
        <div id={connectionsPanelId('providerProfiles')} role="tabpanel" aria-labelledby={connectionsTabId('providerProfiles')}>
          <ProviderProfilesPanel
            providerProfiles={f.providerProfiles}
            isLoading={f.isLoadingProviderProfiles}
            isMutating={f.isMutatingProviderProfiles}
            statusMessage={f.providerProfilesStatusMessage}
            errorMessage={f.providerProfilesErrorMessage}
            pendingId={pendingId}
            requestError={requestError}
            onTrackRequest={trackRequest}
            configEvent={configEvent}
            onConsumeConfigEvent={() => setConfigEvent(null)}
            folderEvent={folderEvent}
            onConsumeFolderEvent={() => setFolderEvent(null)}
          />
        </div>
      )}
    </div>
  )
}
