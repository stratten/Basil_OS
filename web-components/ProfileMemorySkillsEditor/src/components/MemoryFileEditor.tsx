import { useEffect, useState } from 'react';
import { getMemoryCap, getMemoryDocument, updateMemoryDocument } from '../services/api';
import { notifySaved } from '../services/bridge';

interface Props {
  apiBaseUrl: string;
  fileName: string;
}

export function MemoryFileEditor({ apiBaseUrl, fileName }: Props) {
  const [content, setContent] = useState('');
  const [capBytes, setCapBytes] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sizeBytes = new TextEncoder().encode(content).length;

  useEffect(() => {
    Promise.all([getMemoryDocument(apiBaseUrl, fileName), getMemoryCap(apiBaseUrl, fileName)])
      .then(([document, cap]) => {
        setContent(document.content);
        setCapBytes(cap);
      })
      .catch((err) => setError(String(err)));
  }, [apiBaseUrl, fileName]);

  async function save() {
    try {
      await updateMemoryDocument(apiBaseUrl, fileName, content);
      notifySaved(true);
    } catch (err) {
      setError(String(err));
    }
  }

  return (
    <section className="editor-panel">
      {error && <div className="editor-error">{error}</div>}
      <textarea className="editor-textarea editor-textarea--mono" value={content} onChange={(event) => setContent(event.target.value)} />
      <div className="editor-footer">
        <span>{sizeBytes} / {capBytes ?? 'unknown'} bytes</span>
        {capBytes && <progress max={capBytes} value={Math.min(sizeBytes, capBytes)} />}
        <button className="editor-primary-button" onClick={save}>Save</button>
      </div>
    </section>
  );
}
