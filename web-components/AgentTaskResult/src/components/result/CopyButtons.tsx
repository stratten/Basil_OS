import { useState } from 'react';
import type { ReactNode } from 'react';
import { useCopiedFlag } from '@shared/useCopyFeedback';
import { copyRichTextToClipboard, copyToClipboard } from '../../services/bridge';

const copyButtonGroupStyle = {
  position: 'absolute',
  top: 2,
  right: 'var(--padding-xs)',
  display: 'flex',
  alignItems: 'center',
  gap: 2,
  zIndex: 1,
} as const;

const copyButtonBaseStyle = {
  border: 'none',
  cursor: 'pointer',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: 'var(--secondary)',
  width: 20,
  height: 20,
  padding: 0,
  borderRadius: 'var(--corner-radius-small)',
  lineHeight: 1,
  transition: 'opacity 0.15s, background 0.15s',
} as const;

export function CopyButtonGroup({ text }: { text: string }) {
  return (
    <div style={copyButtonGroupStyle}>
      <CopyConfirmationButton
        title="Copy rich text"
        onCopy={() => copyRichTextToClipboard(text)}
        icon={<RichTextCopyIcon />}
      />
      <CopyConfirmationButton
        title="Copy markdown"
        onCopy={() => copyToClipboard(text)}
        icon={<MarkdownCopyIcon />}
      />
    </div>
  );
}

function CopyConfirmationButton({
  title,
  onCopy,
  icon,
}: {
  title: string;
  onCopy: () => void;
  icon: ReactNode;
}) {
  const [copied, flashCopied] = useCopiedFlag();
  const [isHovering, setIsHovering] = useState(false);

  const handleCopy = () => {
    onCopy();
    flashCopied();
  };

  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={handleCopy}
      onMouseEnter={() => setIsHovering(true)}
      onMouseLeave={() => setIsHovering(false)}
      style={{
        ...copyButtonBaseStyle,
        opacity: isHovering || copied ? 1 : 0.4,
        background: isHovering || copied ? 'rgba(51, 85, 155, 0.08)' : 'transparent',
      }}
    >
      {copied ? <CheckmarkIcon /> : icon}
    </button>
  );
}

export function MarkdownCopyIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="5" y="5" width="9" height="9" rx="1.5" />
      <path d="M11 5V3.5A1.5 1.5 0 009.5 2h-6A1.5 1.5 0 002 3.5v6A1.5 1.5 0 003.5 11H5" />
    </svg>
  );
}

export function RichTextCopyIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M3 3h10M8 3v10" />
      <path d="M5.5 13h5" />
    </svg>
  );
}

export function CheckmarkIcon() {
  return (
    <svg width="10" height="10" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M13 4.5L6.5 11 3 7.5" />
    </svg>
  );
}
