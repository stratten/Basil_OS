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

  describe('code blocks', () => {
    function setCaret(node: Node, offset: number): void {
      (screen.getByRole('textbox', { name: 'Message' }) as HTMLElement).focus();
      const range = document.createRange();
      range.setStart(node, offset);
      range.collapse(true);
      const selection = window.getSelection()!;
      selection.removeAllRanges();
      selection.addRange(range);
    }

    function codeBlockButton(): HTMLElement {
      return screen.getByRole('button', { name: 'Code block' });
    }

    it('wraps the current line and keeps new lines inside the same block', () => {
      const onHtmlChange = vi.fn();
      const { editorRef, onDraftChange } = renderComposer({ onHtmlChange });
      const editor = editorRef.current!;
      editor.textContent = 'first line';
      setCaret(editor.firstChild!, 10);

      fireEvent.click(codeBlockButton());

      expect(editor.innerHTML).toBe('<pre>first line\n</pre>');
      expect(codeBlockButton().className).toContain('is-active');

      const notPrevented = fireEvent.keyDown(editor, { key: 'Enter' });
      expect(notPrevented).toBe(false);
      expect(editor.querySelectorAll('pre')).toHaveLength(1);
      expect(editor.querySelector('pre')!.textContent).toBe('first line\n\n');
      expect(window.getSelection()!.anchorOffset).toBe(11);
      expect(onHtmlChange).toHaveBeenLastCalledWith('<pre>first line\n\n</pre>');
      expect(onDraftChange).toHaveBeenCalled();
    });

    it('inserts a line break mid-block without leaving it', () => {
      const { editorRef } = renderComposer();
      const editor = editorRef.current!;
      editor.innerHTML = '<pre>ab\n</pre>';
      setCaret(editor.querySelector('pre')!.firstChild!, 1);

      fireEvent.keyDown(editor, { key: 'Enter' });

      expect(editor.innerHTML).toBe('<pre>a\nb\n</pre>');
      expect(window.getSelection()!.anchorOffset).toBe(2);
    });

    it('exits the block when Return is pressed on an empty last line', () => {
      const { editorRef } = renderComposer();
      const editor = editorRef.current!;
      editor.innerHTML = '<pre>code\n\n</pre>';
      setCaret(editor.querySelector('pre')!.firstChild!, 5);

      fireEvent.keyDown(editor, { key: 'Enter' });

      expect(editor.innerHTML).toBe('<pre>code\n</pre><div><br></div>');
      expect(window.getSelection()!.anchorNode).toBe(editor.querySelector('div'));
      expect(codeBlockButton().className).not.toContain('is-active');
    });

    it('removes an empty block when Return is pressed in it', () => {
      const { editorRef } = renderComposer();
      const editor = editorRef.current!;
      const pre = document.createElement('pre');
      pre.append(document.createTextNode('\n'));
      editor.append(pre);
      setCaret(pre.firstChild!, 0);

      fireEvent.keyDown(editor, { key: 'Enter' });

      expect(editor.innerHTML).toBe('<div><br></div>');
    });

    it('wraps every selected line into one block', () => {
      const { editorRef } = renderComposer();
      const editor = editorRef.current!;
      editor.innerHTML = 'one<div>two</div><div>three</div>';
      const range = document.createRange();
      range.setStart(editor.firstChild!, 0);
      range.setEnd(editor.querySelectorAll('div')[1].firstChild!, 5);
      editor.focus();
      window.getSelection()!.removeAllRanges();
      window.getSelection()!.addRange(range);

      fireEvent.click(codeBlockButton());

      expect(editor.innerHTML).toBe('<pre>one\ntwo\nthree\n</pre>');
    });

    it('merges adjacent one-line blocks into the block being created', () => {
      const { editorRef } = renderComposer();
      const editor = editorRef.current!;
      editor.innerHTML = '<pre>a</pre><pre>b<br></pre><div>c</div>';
      setCaret(editor.querySelector('div')!.firstChild!, 1);

      fireEvent.click(codeBlockButton());

      expect(editor.innerHTML).toBe('<pre>a\nb\nc\n</pre>');
    });

    it('unwraps the block from the toolbar and keeps the caret position', () => {
      const { editorRef } = renderComposer();
      const editor = editorRef.current!;
      editor.innerHTML = '<pre>alpha\nbeta\n</pre>';
      setCaret(editor.querySelector('pre')!.firstChild!, 8);

      fireEvent.click(codeBlockButton());

      expect(editor.innerHTML).toBe('<div>alpha</div><div>beta</div>');
      const selection = window.getSelection()!;
      expect(selection.anchorNode?.textContent).toBe('beta');
      expect(selection.anchorOffset).toBe(2);
      expect(codeBlockButton().className).not.toContain('is-active');
    });

    it('unwraps the block with Backspace at its very start', () => {
      const { editorRef } = renderComposer();
      const editor = editorRef.current!;
      editor.innerHTML = '<pre>x\n\ny\n</pre>';
      setCaret(editor.querySelector('pre')!.firstChild!, 0);

      const notPrevented = fireEvent.keyDown(editor, { key: 'Backspace' });

      expect(notPrevented).toBe(false);
      expect(editor.innerHTML).toBe('<div>x</div><div><br></div><div>y</div>');
    });

    it('leaves Backspace alone inside the block', () => {
      const { editorRef } = renderComposer();
      const editor = editorRef.current!;
      editor.innerHTML = '<pre>xy\n</pre>';
      setCaret(editor.querySelector('pre')!.firstChild!, 1);

      expect(fireEvent.keyDown(editor, { key: 'Backspace' })).toBe(true);
      expect(editor.innerHTML).toBe('<pre>xy\n</pre>');
    });

    it('opens a line below the last block with Down or Right at its end', () => {
      const { editorRef } = renderComposer();
      const editor = editorRef.current!;
      editor.innerHTML = '<pre>one\ntwo\n</pre>';
      const text = editor.querySelector('pre')!.firstChild!;

      setCaret(text, 1);
      expect(fireEvent.keyDown(editor, { key: 'ArrowDown' })).toBe(true);
      setCaret(text, 5);
      expect(fireEvent.keyDown(editor, { key: 'ArrowRight' })).toBe(true);
      expect(editor.innerHTML).toBe('<pre>one\ntwo\n</pre>');

      setCaret(text, 5);
      expect(fireEvent.keyDown(editor, { key: 'ArrowDown' })).toBe(false);
      expect(editor.innerHTML).toBe('<pre>one\ntwo\n</pre><div><br></div>');
    });

    it('does not add a line when content already follows the block', () => {
      const { editorRef } = renderComposer();
      const editor = editorRef.current!;
      editor.innerHTML = '<pre>one\n</pre><div>after</div>';
      setCaret(editor.querySelector('pre')!.firstChild!, 3);

      expect(fireEvent.keyDown(editor, { key: 'ArrowDown' })).toBe(true);
      expect(editor.innerHTML).toBe('<pre>one\n</pre><div>after</div>');
    });

    it('still submits on Command-Return from inside a block', () => {
      const { editorRef, onSubmit } = renderComposer();
      const editor = editorRef.current!;
      editor.innerHTML = '<pre>code\n</pre>';
      setCaret(editor.querySelector('pre')!.firstChild!, 4);

      fireEvent.keyDown(editor, { key: 'Enter', metaKey: true });

      expect(onSubmit).toHaveBeenCalledOnce();
      expect(editor.innerHTML).toBe('<pre>code\n</pre>');
    });

    it('creates an empty block in an empty editor', () => {
      const { editorRef } = renderComposer();
      const editor = editorRef.current!;
      editor.focus();

      fireEvent.click(codeBlockButton());

      expect(editor.innerHTML).toBe('<pre>\n</pre>');
      expect(window.getSelection()!.anchorNode).toBe(editor.querySelector('pre')!.firstChild);
    });
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
