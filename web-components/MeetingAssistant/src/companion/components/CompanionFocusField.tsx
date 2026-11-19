import { useEffect, useId, useRef, useState } from 'react';

export const COMPANION_FOCUS_MAX_CHARS = 600;

interface CompanionFocusFieldProps {
  /** The saved focus. */
  value: string;
  /** Saves the trimmed text; resolves true when the backend accepted it. */
  onSave: (next: string) => Promise<boolean>;
}

/** Where the user tells the Companion what to concentrate on. Built on the Analysis card's labeled instructions textarea; the text is saved when the field loses focus. */
export default function CompanionFocusField({ value, onSave }: CompanionFocusFieldProps) {
  const inputId = useId();
  const [draft, setDraft] = useState(value);
  const [error, setError] = useState<string | null>(null);
  const editingRef = useRef(false);

  useEffect(() => {
    if (!editingRef.current) setDraft(value);
  }, [value]);

  const commit = async () => {
    editingRef.current = false;
    const next = draft.trim();
    if (next === value.trim()) {
      setDraft(value);
      return;
    }
    setError(null);
    const saved = await onSave(next);
    if (saved) setDraft(next);
    else setError('The focus could not be saved. Try again.');
  };

  return (
    <div className="companion-focus">
      <label className="meeting-analysis-field-label" htmlFor={inputId}>Focus (optional):</label>
      <textarea
        id={inputId}
        className="meeting-analysis-custom-instructions companion-focus-input"
        placeholder="What should the Companion concentrate on? For example: flag any commitment about the launch date."
        value={draft}
        maxLength={COMPANION_FOCUS_MAX_CHARS}
        rows={3}
        onFocus={() => {
          editingRef.current = true;
        }}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => void commit()}
      />
      {error && <p className="meeting-history-load-more-error" role="alert">{error}</p>}
    </div>
  );
}
