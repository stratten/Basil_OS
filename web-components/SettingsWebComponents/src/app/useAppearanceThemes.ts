import { useEffect, useRef, useState } from 'react'
import {
  deleteAppearanceTheme,
  notifyAppearanceThemesReady,
  onAppearanceThemesEvent,
  saveAppearanceTheme,
} from '../services/appearanceThemesBridge'
import type { CustomAppearanceTheme, CustomAppearanceThemeInput } from '../types'

export type AppearanceThemeOperation = 'save' | 'delete'

interface PendingThemeRequest {
  requestId: string
  operation: AppearanceThemeOperation
  onSuccess: () => void
}

export interface AppearanceThemesController {
  themes: CustomAppearanceTheme[]
  loadError: string | null
  pendingOperation: AppearanceThemeOperation | null
  errorMessage: string | null
  errorOperation: AppearanceThemeOperation | null
  saveTheme: (input: CustomAppearanceThemeInput, onSaved: () => void) => void
  deleteTheme: (themeId: string, onDeleted: () => void) => void
  clearError: () => void
}

export function useAppearanceThemes(): AppearanceThemesController {
  const [themes, setThemes] = useState<CustomAppearanceTheme[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const [pendingOperation, setPendingOperation] = useState<AppearanceThemeOperation | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [errorOperation, setErrorOperation] = useState<AppearanceThemeOperation | null>(null)
  const pendingRequestRef = useRef<PendingThemeRequest | null>(null)

  useEffect(() => {
    const unsubscribe = onAppearanceThemesEvent((event) => {
      if (event.type === 'init' || event.type === 'snapshot') {
        setThemes(event.themes)
        setLoadError(null)
        return
      }
      if (event.type === 'loadError') {
        setLoadError(event.message)
        return
      }
      const pending = pendingRequestRef.current
      if (!pending || event.requestId !== pending.requestId) return
      pendingRequestRef.current = null
      setPendingOperation(null)
      if (event.status === 'error') {
        setErrorMessage(event.message ?? 'The theme request could not be completed.')
        setErrorOperation(pending.operation)
        return
      }
      setErrorMessage(null)
      setErrorOperation(null)
      pending.onSuccess()
    })
    notifyAppearanceThemesReady()
    return unsubscribe
  }, [])

  function begin(operation: AppearanceThemeOperation, requestId: string, onSuccess: () => void) {
    pendingRequestRef.current = { requestId, operation, onSuccess }
    setPendingOperation(operation)
  }

  function clearError() {
    setErrorMessage(null)
    setErrorOperation(null)
  }

  function saveTheme(input: CustomAppearanceThemeInput, onSaved: () => void) {
    if (pendingRequestRef.current) return
    clearError()
    begin('save', saveAppearanceTheme(input), onSaved)
  }

  function deleteTheme(themeId: string, onDeleted: () => void) {
    if (pendingRequestRef.current) return
    clearError()
    begin('delete', deleteAppearanceTheme(themeId), onDeleted)
  }

  return { themes, loadError, pendingOperation, errorMessage, errorOperation, saveTheme, deleteTheme, clearError }
}
