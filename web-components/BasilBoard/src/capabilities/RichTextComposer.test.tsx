import { createRef, type ComponentProps } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import RichTextComposer from '../../../shared/RichTextComposer';

function renderComposer(overrides: Partial<ComponentProps<typeof RichTextComposer>> = {}) {
  const onSubmit = vi.fn();
  const onDraftChange = vi.fn();
  const editorRef = createRef<HTMLDivElement>();
  render(
    <RichTextComposer
      editorRef={editorRef}
      disabled={false}
      placeholder="Write a message"
      submitDisabled={false}
      onDraftChange={onDraftChange}
      onSubmit={onSubmit}
      {...overrides}
    />,
  );
  return { editorRef, onDraftChange, onSubmit };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe('RichTextComposer', () => {
  it('reports HTML changes and can omit chat-only actions for embedded editors', () => {
    const onHtmlChange = vi.fn();
    const { editorRef } = renderComposer({
      editorAriaLabel: 'To-Do notes',
      onHtmlChange,
      showActions: false,
    });

    editorRef.current!.innerHTML = '<strong>Keep this formatting</strong>';
    fireEvent.input(editorRef.current!);

    expect(onHtmlChange).toHaveBeenCalledWith('<strong>Keep this formatting</strong>');
    expect(screen.getByRole('textbox', { name: 'To-Do notes' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Send' })).not.toBeInTheDocument();
  });

  it('renders the Conversation-standard icon-only send control and shortcut', async () => {
    const { onSubmit } = renderComposer();

    const sendButton = screen.getByRole('button', { name: 'Send' });
    expect(sendButton.textContent).toBe('');
    expect(sendButton.querySelector('svg')).toBeTruthy();
    expect(screen.getByLabelText('Command-Return sends').textContent).toBe('⌘↩');

    await userEvent.click(sendButton);
    expect(onSubmit).toHaveBeenCalledOnce();
  });

  it('submits on Command-Return and forwards plaintext draft changes', () => {
    const { editorRef, onDraftChange, onSubmit } = renderComposer();
    const editor = screen.getByRole('textbox', { name: 'Message' });
    editor.textContent = 'Format this';

    fireEvent.input(editor);
    fireEvent.keyDown(editor, { key: 'Enter', metaKey: true });

    expect(onDraftChange).toHaveBeenLastCalledWith('Format this');
    expect(onSubmit).toHaveBeenCalledOnce();
    expect(editorRef.current).toBe(editor);
  });

  it('applies formatting commands from the shared toolbar', async () => {
    const execCommand = vi.fn();
    Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand });
    renderComposer();

    await userEvent.click(screen.getByRole('button', { name: 'Bold' }));

    expect(execCommand).toHaveBeenCalledWith('bold', false, undefined);
  });

  it('places clear formatting after the list controls and renders a top resize handle', () => {
    renderComposer();

    const numberedList = screen.getByRole('button', { name: 'Numbered list' });
    const clearFormatting = screen.getByRole('button', { name: 'Clear formatting' });
    expect(numberedList.compareDocumentPosition(clearFormatting) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(document.querySelector('.rich-text-composer-resize-handle')).toBeInTheDocument();
  });

  it('clears selected formatting and synchronizes the draft state', async () => {
    const execCommand = vi.fn();
    const onHtmlChange = vi.fn();
    Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand });
    const { editorRef, onDraftChange } = renderComposer({ onHtmlChange });
    editorRef.current!.innerHTML = '<strong>Formatted text</strong>';
    const selection = window.getSelection()!;
    const range = document.createRange();
    range.selectNodeContents(editorRef.current!.querySelector('strong')!);
    selection.removeAllRanges();
    selection.addRange(range);

    await userEvent.click(screen.getByRole('button', { name: 'Clear formatting' }));

    expect(execCommand).toHaveBeenCalledWith('removeFormat', false);
    expect(onDraftChange).toHaveBeenLastCalledWith('Formatted text');
    expect(onHtmlChange).toHaveBeenLastCalledWith('<strong>Formatted text</strong>');
  });

  it('clears a phantom bold typing style as soon as the caret lands at the end of a plain line', () => {
    const { editorRef } = renderComposer();
    const editor = editorRef.current!;
    editor.textContent = 'Plain text line';

    const textNode = editor.firstChild as Text;
    const range = document.createRange();
    range.setStart(textNode, textNode.length);
    range.collapse(true);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);

    // Simulate the WebKit/Chromium quirk: the browser's internal typing
    // style reports bold=true for this caret even though no <b>/<strong>
    // element actually encloses it (the line is plain text). Real browsers
    // fire `selectionchange` the moment the caret lands here, before any
    // key is pressed -- so drive the fix the same way instead of a keydown.
    const execCommand = vi.fn();
    Object.defineProperty(document, 'queryCommandState', { configurable: true, value: vi.fn(() => true) });
    Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand });

    document.dispatchEvent(new Event('selectionchange'));

    expect(execCommand).toHaveBeenCalledWith('bold', false);
  });

  it('leaves typing style alone when the caret is actually inside a bold run', () => {
    const { editorRef } = renderComposer();
    const editor = editorRef.current!;
    editor.innerHTML = '<strong>Bold text</strong>';

    const boldTextNode = editor.querySelector('strong')!.firstChild as Text;
    const range = document.createRange();
    range.setStart(boldTextNode, boldTextNode.length);
    range.collapse(true);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);

    const execCommand = vi.fn();
    // Only bold is actually active here (the caret is inside a <strong>);
    // unlike the phantom-state test above, this must not report italic or
    // underline as active, or the assertion below would trivially pass for
    // the wrong reason.
    Object.defineProperty(document, 'queryCommandState', { configurable: true, value: vi.fn((command: string) => command === 'bold') });
    Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand });

    document.dispatchEvent(new Event('selectionchange'));

    expect(execCommand).not.toHaveBeenCalled();
  });

  it('renders optional controls without Conversation-only controls and disables editing', () => {
    renderComposer({
      disabled: true,
      bottomStart: <span>Model selector</span>,
      bottomEnd: <button type="button">Attach</button>,
    });

    expect(screen.getByText('Model selector')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Attach' })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: 'Conversation only' })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Message' }).getAttribute('contenteditable')).toBe('false');
    expect(screen.getByRole('button', { name: 'Clear formatting' })).toBeDisabled();
  });
});
