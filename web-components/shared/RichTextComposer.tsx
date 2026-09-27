import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ClipboardEvent,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
  type RefObject,
} from 'react';
import './rich-text-followup.css';

export interface RichTextComposerProps {
  editorRef: RefObject<HTMLDivElement>;
  disabled: boolean;
  placeholder: string;
  submitDisabled: boolean;
  onDraftChange: (value: string) => void;
  onSubmit: () => void;
  onHtmlChange?: (html: string) => void;
  onPaste?: (event: ClipboardEvent<HTMLDivElement>) => void;
  onKeyDown?: (event: KeyboardEvent<HTMLDivElement>) => void;
  toolbarEnd?: ReactNode;
  bottomStart?: ReactNode;
  bottomMiddle?: ReactNode;
  bottomEnd?: ReactNode;
  sendReplacement?: ReactNode;
  className?: string;
  editorClassName?: string;
  editorAriaLabel?: string;
  showActions?: boolean;
}

type FormatName = 'bold' | 'italic' | 'underline' | 'insertUnorderedList' | 'insertOrderedList';

function editorText(editorRef: RefObject<HTMLDivElement>): string {
  return editorRef.current?.innerText.trim() ?? '';
}

const NO_ACTIVE_FORMATS: Record<FormatName, boolean> = {
  bold: false,
  italic: false,
  underline: false,
  insertUnorderedList: false,
  insertOrderedList: false,
};

function computeActiveFormats(editorRef: RefObject<HTMLDivElement>): Record<FormatName, boolean> {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount === 0 || !editorRef.current?.contains(selection.anchorNode)) {
    return NO_ACTIVE_FORMATS;
  }
  const queryCommandState = typeof document.queryCommandState === 'function'
    ? (command: FormatName) => document.queryCommandState(command)
    : () => false;
  return {
    bold: queryCommandState('bold'),
    italic: queryCommandState('italic'),
    underline: queryCommandState('underline'),
    insertUnorderedList: queryCommandState('insertUnorderedList'),
    insertOrderedList: queryCommandState('insertOrderedList'),
  };
}

const FORMAT_COMMAND_TAGS: Partial<Record<string, string[]>> = {
  bold: ['B', 'STRONG'],
  italic: ['I', 'EM'],
  underline: ['U'],
};

function findEnclosingFormatElement(node: Node | null, editor: HTMLElement, tagNames: string[]): HTMLElement | null {
  let current: Node | null = node;
  while (current && current !== editor) {
    if (current.nodeType === Node.ELEMENT_NODE && tagNames.includes((current as HTMLElement).tagName)) {
      return current as HTMLElement;
    }
    current = current.parentNode;
  }
  return null;
}

// WebKit/Chromium contentEditable tracks a "typing style" for the caret that
// is separate from the actual DOM: document.queryCommandState('bold') (or
// italic/underline) can report true -- so the next typed character would
// render formatted -- even though no matching element actually encloses the
// caret. This phantom state gets stuck after certain caret placements, most
// commonly landing at the end of an existing plain-text line, with no
// toolbar click involved. Run this every time the caret moves (the point
// where the phantom state is introduced) and clear any format the browser
// claims is active but the real DOM doesn't back, so typing follows the
// document instead of the browser's stale internal guess.
function reconcilePhantomTypingStyle(editorRef: RefObject<HTMLDivElement>): void {
  const editor = editorRef.current;
  const selection = window.getSelection();
  if (!editor || !selection || selection.rangeCount === 0 || !selection.isCollapsed) return;
  const caretNode = selection.getRangeAt(0).startContainer;
  if (!editor.contains(caretNode)) return;
  if (typeof document.queryCommandState !== 'function') return;
  for (const command of Object.keys(FORMAT_COMMAND_TAGS) as (keyof typeof FORMAT_COMMAND_TAGS)[]) {
    const tagNames = FORMAT_COMMAND_TAGS[command];
    if (!tagNames || !document.queryCommandState(command)) continue;
    if (findEnclosingFormatElement(caretNode, editor, tagNames)) continue;
    document.execCommand(command, false);
  }
}

function ToolbarButton({
  disabled,
  onClick,
  title,
  active = false,
  children,
}: {
  disabled: boolean;
  onClick: () => void;
  title: string;
  active?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      className={`rich-text-composer-toolbar-button${active ? ' is-active' : ''}`}
      title={title}
      aria-label={title}
      disabled={disabled}
      onMouseDown={(event) => event.preventDefault()}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export default function RichTextComposer({
  editorRef,
  disabled,
  placeholder,
  submitDisabled,
  onDraftChange,
  onSubmit,
  onHtmlChange,
  onPaste,
  onKeyDown,
  toolbarEnd,
  bottomStart,
  bottomMiddle,
  bottomEnd,
  sendReplacement,
  className,
  editorClassName,
  editorAriaLabel = 'Message',
  showActions = true,
}: RichTextComposerProps) {
  const [activeFormats, setActiveFormats] = useState<Record<FormatName, boolean>>({
    bold: false,
    italic: false,
    underline: false,
    insertUnorderedList: false,
    insertOrderedList: false,
  });
  const [resizedEditorHeight, setResizedEditorHeight] = useState<number>();
  const resizeStateRef = useRef<{ pointerId: number; startY: number; startHeight: number }>();

  useEffect(() => {
    const updateActiveFormats = () => {
      reconcilePhantomTypingStyle(editorRef);
      setActiveFormats(computeActiveFormats(editorRef));
    };
    document.addEventListener('selectionchange', updateActiveFormats);
    return () => document.removeEventListener('selectionchange', updateActiveFormats);
  }, [editorRef]);

  const composerClassName = useMemo(
    () => ['rich-text-composer', className].filter(Boolean).join(' '),
    [className],
  );

  function focusEditor(): void {
    const editor = editorRef.current;
    if (!editor) return;
    const selection = window.getSelection();
    const hasExistingSelectionInEditor = !!selection
      && selection.rangeCount > 0
      && editor.contains(selection.getRangeAt(0).commonAncestorContainer);
    editor.focus();
    if (hasExistingSelectionInEditor) {
      // A toolbar button's onMouseDown already calls event.preventDefault()
      // specifically to keep the user's text selection intact across the
      // click (see ToolbarButton above). Previously this function then
      // unconditionally collapsed that preserved selection to a caret at the
      // end of the editor's content before the format command ran, which is
      // why selecting existing text and clicking Italic/Underline silently
      // applied the toggle to an empty end-of-document caret instead of to
      // the selected text. When a valid selection already exists inside this
      // editor, leave it untouched so the format command below applies to it.
      return;
    }
    if (!selection) return;
    if (editor.childNodes.length === 0) {
      editor.appendChild(document.createTextNode(''));
    }
    const range = document.createRange();
    range.selectNodeContents(editor);
    range.collapse(false);
    selection.removeAllRanges();
    selection.addRange(range);
  }

  function executeCommand(command: string, value?: string): void {
    focusEditor();
    expandCollapsedCaretToEnclosingFormat(command);
    document.execCommand(command, false, value);
    // execCommand doesn't reliably fire `selectionchange` on its own (the
    // caret/selection range itself may not move), so the toolbar button's
    // pressed state would otherwise stay stale until the next keystroke.
    // Re-derive it synchronously here so clicking Bold/Italic/Underline (in
    // either direction) is reflected immediately.
    setActiveFormats(computeActiveFormats(editorRef));
    onDraftChange(editorText(editorRef));
    onHtmlChange?.(editorRef.current?.innerHTML ?? '');
  }

  // document.execCommand on a collapsed caret only affects the style of
  // future typed characters -- it cannot remove formatting from surrounding
  // text, so clicking a toolbar toggle while the caret sits inside an
  // already-styled run (no drag-selection) previously did nothing visible.
  // When the caret is collapsed and already inside a matching inline
  // element for this command, select that whole element first so the
  // subsequent execCommand call actually toggles the formatting off.
  function expandCollapsedCaretToEnclosingFormat(command: string): void {
    const tagNames = FORMAT_COMMAND_TAGS[command];
    if (!tagNames) return;
    const editor = editorRef.current;
    const selection = window.getSelection();
    if (!editor || !selection || selection.rangeCount === 0 || !selection.isCollapsed) return;
    if (typeof document.queryCommandState !== 'function' || !document.queryCommandState(command)) return;
    const caretNode = selection.getRangeAt(0).startContainer;
    if (!editor.contains(caretNode)) return;
    const enclosing = findEnclosingFormatElement(caretNode, editor, tagNames);
    if (!enclosing) return;
    const range = document.createRange();
    range.selectNodeContents(enclosing);
    selection.removeAllRanges();
    selection.addRange(range);
  }

  function clearFormatting(): void {
    focusEditor();
    document.execCommand('removeFormat', false);
    setActiveFormats(computeActiveFormats(editorRef));
    onDraftChange(editorText(editorRef));
    onHtmlChange?.(editorRef.current?.innerHTML ?? '');
  }

  function toggleInlineCode(): void {
    focusEditor();
    const selection = window.getSelection();
    const editor = editorRef.current;
    if (!selection || !editor || selection.rangeCount === 0 || selection.isCollapsed) return;
    const range = selection.getRangeAt(0);
    if (!editor.contains(range.commonAncestorContainer)) return;
    const commonElement = range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE
      ? range.commonAncestorContainer as Element
      : range.commonAncestorContainer.parentElement;
    const existingCode = commonElement?.closest('code');
    if (existingCode && editor.contains(existingCode)) {
      existingCode.replaceWith(document.createTextNode(existingCode.textContent ?? ''));
    } else {
      const code = document.createElement('code');
      code.append(range.extractContents());
      range.insertNode(code);
      selection.removeAllRanges();
      const nextRange = document.createRange();
      nextRange.selectNodeContents(code);
      selection.addRange(nextRange);
    }
    onDraftChange(editorText(editorRef));
    onHtmlChange?.(editorRef.current?.innerHTML ?? '');
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    onKeyDown?.(event);
    if (event.defaultPrevented) return;
    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      if (!submitDisabled) onSubmit();
    }
  }

  function beginEditorResize(event: PointerEvent<HTMLDivElement>): void {
    const editor = editorRef.current;
    if (!editor || disabled) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    resizeStateRef.current = {
      pointerId: event.pointerId,
      startY: event.clientY,
      startHeight: editor.getBoundingClientRect().height,
    };
  }

  function resizeEditor(event: PointerEvent<HTMLDivElement>): void {
    const resizeState = resizeStateRef.current;
    if (!resizeState || resizeState.pointerId !== event.pointerId) return;
    setResizedEditorHeight(Math.max(60, resizeState.startHeight + resizeState.startY - event.clientY));
  }

  function endEditorResize(event: PointerEvent<HTMLDivElement>): void {
    const resizeState = resizeStateRef.current;
    if (!resizeState || resizeState.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    resizeStateRef.current = undefined;
  }

  return (
    <div className={composerClassName}>
      <div className="rich-text-composer-toolbar" aria-label="Formatting">
        <ToolbarButton disabled={disabled} onClick={() => executeCommand('bold')} title="Bold" active={activeFormats.bold}>
          <strong>B</strong>
        </ToolbarButton>
        <ToolbarButton disabled={disabled} onClick={() => executeCommand('italic')} title="Italic" active={activeFormats.italic}>
          <em>I</em>
        </ToolbarButton>
        <ToolbarButton disabled={disabled} onClick={() => executeCommand('underline')} title="Underline" active={activeFormats.underline}>
          <u>U</u>
        </ToolbarButton>
        <div className="rich-text-composer-toolbar-divider" />
        <ToolbarButton disabled={disabled} onClick={toggleInlineCode} title="Inline code">
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <polyline points="4,4 1,8 4,12" />
            <polyline points="12,4 15,8 12,12" />
          </svg>
        </ToolbarButton>
        <ToolbarButton disabled={disabled} onClick={() => executeCommand('formatBlock', 'pre')} title="Code block">
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="1" y="1" width="14" height="14" rx="2" />
            <polyline points="5,5 3,8 5,11" />
            <polyline points="11,5 13,8 11,11" />
          </svg>
        </ToolbarButton>
        <div className="rich-text-composer-toolbar-divider" />
        <ToolbarButton disabled={disabled} onClick={() => executeCommand('insertUnorderedList')} title="Bullet list" active={activeFormats.insertUnorderedList}>
          <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
            <circle cx="2" cy="4" r="1.2" />
            <rect x="5" y="3" width="10" height="2" rx="0.5" />
            <circle cx="2" cy="8" r="1.2" />
            <rect x="5" y="7" width="10" height="2" rx="0.5" />
            <circle cx="2" cy="12" r="1.2" />
            <rect x="5" y="11" width="10" height="2" rx="0.5" />
          </svg>
        </ToolbarButton>
        <ToolbarButton disabled={disabled} onClick={() => executeCommand('insertOrderedList')} title="Numbered list" active={activeFormats.insertOrderedList}>
          <svg width="12" height="12" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
            <text x="0.5" y="5.5" fontSize="5" fontFamily="var(--font-family-medium)">1.</text>
            <rect x="5" y="3" width="10" height="2" rx="0.5" />
            <text x="0.5" y="9.5" fontSize="5" fontFamily="var(--font-family-medium)">2.</text>
            <rect x="5" y="7" width="10" height="2" rx="0.5" />
            <text x="0.5" y="13.5" fontSize="5" fontFamily="var(--font-family-medium)">3.</text>
            <rect x="5" y="11" width="10" height="2" rx="0.5" />
          </svg>
        </ToolbarButton>
        <div className="rich-text-composer-toolbar-divider" />
        <ToolbarButton disabled={disabled} onClick={clearFormatting} title="Clear formatting">
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="m4 11.5 6.8-6.8 2.3 2.3-6.8 6.8H4v-2.3Z" />
            <path d="m9.8 5.7 1.5-1.5a1.2 1.2 0 0 1 1.7 0l.8.8a1.2 1.2 0 0 1 0 1.7l-1.5 1.5" />
            <path d="M2 14h12" />
          </svg>
        </ToolbarButton>
        {toolbarEnd ? <span className="rich-text-composer-toolbar-end">{toolbarEnd}</span> : null}
      </div>
      <div className="rich-text-composer-editor-shell">
        <div
          ref={editorRef}
          className={['rich-text-composer-editor', editorClassName].filter(Boolean).join(' ')}
          style={resizedEditorHeight ? { height: `${resizedEditorHeight}px` } : undefined}
          contentEditable={!disabled}
          suppressContentEditableWarning
          role="textbox"
          aria-label={editorAriaLabel}
          aria-multiline="true"
          data-placeholder={placeholder}
          onInput={() => {
            onDraftChange(editorText(editorRef));
            onHtmlChange?.(editorRef.current?.innerHTML ?? '');
          }}
          onPaste={onPaste}
          onKeyDown={handleKeyDown}
        />
        <div
          className="rich-text-composer-resize-handle"
          onPointerDown={beginEditorResize}
          onPointerMove={resizeEditor}
          onPointerUp={endEditorResize}
          onPointerCancel={endEditorResize}
          aria-hidden="true"
        />
      </div>
      {showActions && (
        <div className="rich-text-composer-actions">
        <div className="rich-text-composer-actions-start">{bottomStart}</div>
        <div className="rich-text-composer-actions-middle">{bottomMiddle}</div>
        <div className="rich-text-composer-actions-end">
          {bottomEnd}
          {sendReplacement ?? (
            <div className="rich-text-composer-send-control">
              <button
                type="button"
                className="rich-text-composer-send-button"
                onClick={onSubmit}
                disabled={submitDisabled}
                title="Send message (⌘↩)"
                aria-label="Send"
              >
                <svg width="14" height="14" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
                  <path d="M14.7 1.3a.75.75 0 0 0-.8-.16L1.55 6.2a.75.75 0 0 0 .03 1.4l5.46 1.8 1.8 5.46a.75.75 0 0 0 1.4.03l5.06-12.35a.75.75 0 0 0-.16-.8ZM8.1 8.7 3.9 7.32l8.79-3.6L8.1 8.7Zm.6-.8 4.98-4.98-3.6 8.79L8.7 7.9Z" />
                </svg>
              </button>
              <span className="rich-text-composer-send-shortcut chats-send-shortcut" title="Command-Return sends" aria-label="Command-Return sends">
                <span>⌘</span>
                <span>↩</span>
              </span>
            </div>
          )}
        </div>
        </div>
      )}
    </div>
  );
}
