// web-components/TranscriptionWidget/src/components/TranscriptBody.tsx

import { useState } from 'react';
import { copyToClipboard } from '../bridge/transcriptionWidgetBridge';
import { TranscriptionSymbol } from './TranscriptionSymbol';

export function TranscriptBody({
  displayText,
  isStatus,
}: {
  displayText: string;
  isStatus: boolean;
}) {
  const [isHovering, setIsHovering] = useState(false);
  const [copied, setCopied] = useState(false);
  const showCopyButton = !isStatus && displayText.length > 0;

  function handleCopy(): void {
    copyToClipboard();
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div
      className="transcription-body"
      onMouseEnter={() => setIsHovering(true)}
      onMouseLeave={() => setIsHovering(false)}
    >
      <div className="transcription-body__scroll">
        <p className={isStatus ? 'transcription-body__text transcription-body__text--status' : 'transcription-body__text'}>
          {displayText}
        </p>
      </div>
      {showCopyButton ? (
        <button
          type="button"
          className="transcription-body__copy-button"
          style={{ opacity: isHovering ? 1 : 0.4 }}
          onClick={handleCopy}
        >
          <TranscriptionSymbol name={copied ? 'copied' : 'copy'} size={10} />
          <span>{copied ? 'Copied' : 'Copy All'}</span>
        </button>
      ) : null}
    </div>
  );
}
