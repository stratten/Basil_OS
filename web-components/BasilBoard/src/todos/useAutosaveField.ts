import { useCallback, useEffect, useRef, useState } from 'react';

export type AutosaveStatus = 'idle' | 'saving' | 'saved' | 'error';

interface UseAutosaveFieldOptions {
  /** Identity of the record being edited; a change discards the draft and adopts the new server value. */
  itemId: string;
  /** The persisted value for this field. */
  serverValue: string;
  /** Canonical form used to decide whether the draft differs from the server value and what is sent. */
  normalize?: (value: string) => string;
  /** A draft that fails validation is discarded in favor of the server value instead of being sent. */
  isValid?: (normalizedValue: string) => boolean;
  /** Persists the normalized value. Resolves true when the server accepted it. */
  save: (value: string) => Promise<boolean>;
  /** Called whenever the hook replaces the draft itself (server sync, revert, item change), for uncontrolled editors. */
  onProgrammaticChange?: (value: string) => void;
}

const SAVED_INDICATOR_MS = 2000;

function identity(value: string): string {
  return value;
}

/**
 * Draft state for one click-to-edit field that autosaves on blur or Enter and reverts on Escape.
 * The server value is only adopted while the field is neither focused nor holding unsaved input, so a refresh
 * triggered by a different field's save can never overwrite what the user is typing here.
 */
export default function useAutosaveField({
  itemId, serverValue, normalize, isValid, save, onProgrammaticChange,
}: UseAutosaveFieldOptions) {
  const [draft, setDraftState] = useState(serverValue);
  const [status, setStatus] = useState<AutosaveStatus>('idle');
  const draftRef = useRef(serverValue);
  const touchedRef = useRef(false);
  const focusedRef = useRef(false);
  const savingRef = useRef(false);
  const itemIdRef = useRef(itemId);
  const serverRef = useRef(serverValue);
  const saveRef = useRef(save);
  const isValidRef = useRef(isValid);
  const normalizeRef = useRef(normalize ?? identity);
  const programmaticRef = useRef(onProgrammaticChange);
  const savedTimerRef = useRef<number>();
  serverRef.current = serverValue;
  saveRef.current = save;
  isValidRef.current = isValid;
  normalizeRef.current = normalize ?? identity;
  programmaticRef.current = onProgrammaticChange;

  const applyProgrammatic = useCallback((value: string) => {
    draftRef.current = value;
    setDraftState(value);
    programmaticRef.current?.(value);
  }, []);

  useEffect(() => () => window.clearTimeout(savedTimerRef.current), []);

  useEffect(() => {
    if (itemIdRef.current !== itemId) {
      itemIdRef.current = itemId;
      touchedRef.current = false;
      focusedRef.current = false;
      window.clearTimeout(savedTimerRef.current);
      setStatus('idle');
      applyProgrammatic(serverValue);
      return;
    }
    if (touchedRef.current || focusedRef.current) return;
    if (normalizeRef.current(draftRef.current) === normalizeRef.current(serverValue)) return;
    applyProgrammatic(serverValue);
  }, [applyProgrammatic, itemId, serverValue]);

  const setDraft = useCallback((value: string) => {
    draftRef.current = value;
    touchedRef.current = true;
    setDraftState(value);
    setStatus((current) => (current === 'saving' ? current : 'idle'));
  }, []);

  const commit = useCallback(async (): Promise<void> => {
    if (!touchedRef.current || savingRef.current) return;
    const sent = normalizeRef.current(draftRef.current);
    if (isValidRef.current && !isValidRef.current(sent)) {
      touchedRef.current = false;
      setStatus('idle');
      applyProgrammatic(serverRef.current);
      return;
    }
    if (sent === normalizeRef.current(serverRef.current)) {
      touchedRef.current = false;
      setStatus('idle');
      return;
    }
    savingRef.current = true;
    window.clearTimeout(savedTimerRef.current);
    setStatus('saving');
    let accepted = false;
    try {
      accepted = await saveRef.current(sent);
    } catch {
      accepted = false;
    }
    savingRef.current = false;
    if (!accepted) {
      setStatus('error');
      return;
    }
    if (normalizeRef.current(draftRef.current) !== sent) {
      // The user kept typing while the save was in flight; send the newer text next.
      setStatus('idle');
      void commit();
      return;
    }
    touchedRef.current = false;
    setStatus('saved');
    savedTimerRef.current = window.setTimeout(() => setStatus('idle'), SAVED_INDICATOR_MS);
  }, [applyProgrammatic]);

  const revert = useCallback(() => {
    touchedRef.current = false;
    window.clearTimeout(savedTimerRef.current);
    setStatus('idle');
    applyProgrammatic(serverRef.current);
  }, [applyProgrammatic]);

  const onFocus = useCallback(() => {
    focusedRef.current = true;
  }, []);

  const onBlur = useCallback(() => {
    focusedRef.current = false;
    void commit();
  }, [commit]);

  return { draft, status, setDraft, commit, revert, onFocus, onBlur };
}
