import { useEffect, useRef, useState } from 'react'
import { Switch } from '@shared/Switch'
import { HotkeyRow } from '../components/HotkeyRow'
import {
  cancelHotkeyCapture,
  notifyHotkeySettingsReady,
  onHotkeyEvent,
  saveHotkeyBinding,
  startHotkeyCapture,
  toggleEnableMonitoringAtStartup,
} from '../services/hotkeyBridge'
import type { HotkeyBinding, HotkeyRowSnapshot } from '../types'

interface PendingBinding {
  id: string
  binding: HotkeyBinding
}

export function HotkeySettingsApp() {
  const [rows, setRows] = useState<HotkeyRowSnapshot[]>([])
  const [enableMonitoringAtStartup, setEnableMonitoringAtStartup] = useState(false)
  const [isLoaded, setIsLoaded] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [editingRowId, setEditingRowId] = useState<string | null>(null)
  const [savingRowId, setSavingRowId] = useState<string | null>(null)
  const [isUpdatingMonitoring, setIsUpdatingMonitoring] = useState(false)
  const [pendingBinding, setPendingBinding] = useState<PendingBinding | null>(null)
  const [rowErrors, setRowErrors] = useState<Record<string, string | null>>({})

  const editingRowIdRef = useRef(editingRowId)
  const pendingBindingRef = useRef(pendingBinding)
  const pendingRowRequestIdRef = useRef<string | null>(null)
  const pendingMonitoringRequestIdRef = useRef<string | null>(null)

  editingRowIdRef.current = editingRowId
  pendingBindingRef.current = pendingBinding

  useEffect(() => {
    const unsubscribe = onHotkeyEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        setRows(event.rows)
        setEnableMonitoringAtStartup(event.enableMonitoringAtStartup)
        setIsLoaded(true)
        setLoadError(null)
        return
      }
      if (event.type === 'loadError') {
        setIsLoaded(false)
        setLoadError(event.message)
        return
      }
      if (event.type === 'captured') {
        setEditingRowId(null)
        setSavingRowId(event.id)
        setPendingBinding({ id: event.id, binding: event.binding })
        setRowErrors((current) => ({ ...current, [event.id]: null }))
        pendingRowRequestIdRef.current = saveHotkeyBinding(event.id, event.binding)
        return
      }
      if (event.type === 'captureCancelled') {
        if (editingRowIdRef.current === event.id) {
          setEditingRowId(null)
        }
        return
      }
      if (event.type === 'intentResult') {
        if (event.requestId === pendingRowRequestIdRef.current) {
          pendingRowRequestIdRef.current = null
          setSavingRowId(null)
          const settled = pendingBindingRef.current
          if (event.status === 'success' && settled) {
            setRows((current) => current.map((row) => (row.id === settled.id ? { ...row, binding: settled.binding } : row)))
          } else if (event.status === 'error' && settled) {
            setRowErrors((current) => ({ ...current, [settled.id]: event.message ?? 'Failed to save hotkey.' }))
          }
          setPendingBinding(null)
          return
        }
        if (event.requestId === pendingMonitoringRequestIdRef.current) {
          pendingMonitoringRequestIdRef.current = null
          setIsUpdatingMonitoring(false)
          if (event.status === 'error') {
            setEnableMonitoringAtStartup((current) => !current)
          }
        }
      }
    })
    notifyHotkeySettingsReady()
    return unsubscribe
  }, [])

  // Guarantees `cancelCapture` is sent for whichever row was being edited
  // whenever the user switches to a different row, switches Settings tabs
  // away from Hotkeys (unmount), or closes the window (unmount) -- otherwise
  // an abandoned capture would leave global hotkey listeners suspended.
  // Harmless no-op on native if capture already finished normally
  // (`HotkeyRecordingCapture` guards on its own `isCapturing` flag).
  useEffect(() => {
    if (editingRowId === null) return
    return () => {
      cancelHotkeyCapture(editingRowId)
    }
  }, [editingRowId])

  useEffect(() => {
    if (editingRowId !== null) {
      startHotkeyCapture(editingRowId)
    }
  }, [editingRowId])

  function handleEdit(id: string) {
    if (!isLoaded || editingRowId !== null || savingRowId !== null) return
    setEditingRowId(id)
  }

  function handleCancel(id: string) {
    cancelHotkeyCapture(id)
    setEditingRowId(null)
  }

  function handleToggleMonitoring() {
    if (!isLoaded || isUpdatingMonitoring) return
    const next = !enableMonitoringAtStartup
    setEnableMonitoringAtStartup(next)
    setIsUpdatingMonitoring(true)
    pendingMonitoringRequestIdRef.current = toggleEnableMonitoringAtStartup(next)
  }

  function handleRetryLoad() {
    setLoadError(null)
    notifyHotkeySettingsReady()
  }

  return (
    <div className="hotkey-settings-shell">
      <section className="hotkey-settings-section">
        <Switch
          id="hotkey-enable-monitoring-at-startup"
          label="Enable monitoring at startup"
          checked={enableMonitoringAtStartup}
          disabled={!isLoaded || isUpdatingMonitoring}
          onChange={handleToggleMonitoring}
        />
      </section>

      <section className="hotkey-settings-section">
        <h2>Hotkeys</h2>
        {!isLoaded && !loadError && <p className="hotkey-settings-status" role="status">Loading hotkeys...</p>}
        {loadError && (
          <div className="hotkey-load-error">
            <p className="hotkey-row-error" role="alert">{loadError}</p>
            <button type="button" className="secondary-button" onClick={handleRetryLoad}>Retry</button>
          </div>
        )}
        {rows.map((row) => {
          const displayRow = pendingBinding?.id === row.id ? { ...row, binding: pendingBinding.binding } : row
          return (
            <HotkeyRow
              key={row.id}
              row={displayRow}
              isEditing={editingRowId === row.id}
              isSaving={savingRowId === row.id}
              isDisabled={!isLoaded}
              errorMessage={rowErrors[row.id] ?? null}
              onEdit={() => handleEdit(row.id)}
              onCancel={() => handleCancel(row.id)}
            />
          )
        })}
      </section>
    </div>
  )
}
