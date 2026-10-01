import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { HistoryDetail } from './HistoryDetail';
import type { AssistantOutputHistoryDetail } from '../../services/historyApi';

const BASE_ENTRY: AssistantOutputHistoryDetail = {
  id: 7,
  outputType: 'assistant_session',
  inputModality: 'voice',
  outputText: 'Original reply',
  contextText: null,
  explanationText: null,
  modelName: null,
  timestamp: '2026-09-28T13:54:00Z',
  status: 'completed',
  refinementCount: 0,
  refinements: [],
  appName: 'Mail',
  userRequest: 'Reply to Miriam',
  processingTimeMs: null,
  sampleContextType: 'email_reply',
  recipient: 'miriam@example.com',
  savedSample: null,
};

function renderDetail(entry: AssistantOutputHistoryDetail) {
  return render(
    <HistoryDetail
      entry={entry}
      baseUrl="http://localhost:8000"
      loading={false}
      nativeActionError={null}
      onClearNativeActionError={() => undefined}
    />,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(HTMLElement.prototype, 'clientHeight');
  Reflect.deleteProperty(HTMLElement.prototype, 'offsetHeight');
  Reflect.deleteProperty(HTMLElement.prototype, 'scrollHeight');
});

describe('HistoryDetail writing samples', () => {
  it('saves the latest refinement using the stored context and shows a saved indicator', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: 'saved',
      sample_id: 'sample-9',
      content: 'Refined reply',
    }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    renderDetail({
      ...BASE_ENTRY,
      refinementCount: 1,
      refinements: [{ instruction: 'Shorter', output: 'Refined reply', timestamp: '2026-09-28T13:55:00Z' }],
    });

    fireEvent.click(screen.getByRole('button', { name: /save as sample/i }));

    await waitFor(() => expect(screen.getByText('Saved as sample')).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/assistant-outputs/7/save-sample',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ content: 'Refined reply' }) }),
    );
  });

  it('offers a picker for older rows without stored context', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: 'saved',
      sample_id: 'sample-9',
      content: 'Original reply',
    }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const { container } = renderDetail({ ...BASE_ENTRY, appName: 'Notes', sampleContextType: null, recipient: null });

    const actions = container.querySelector('.assistant-output-history-detail__actions')!;
    expect(screen.queryByRole('combobox', { name: /sample context/i })).not.toBeInTheDocument();
    expect(actions.firstElementChild).toHaveClass('assistant-output-history-detail__context-chip');
    expect(actions.firstElementChild).toHaveTextContent('Document');

    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }));
    const picker = screen.getByRole('combobox', { name: /sample context/i }) as HTMLSelectElement;
    expect(actions.firstElementChild).toBe(picker);
    expect(picker.value).toBe('document');
    fireEvent.change(picker, { target: { value: 'social_media' } });
    fireEvent.click(screen.getByRole('button', { name: /apply edits/i }));
    expect(actions.firstElementChild).toHaveTextContent('Social Media');
    fireEvent.click(screen.getByRole('button', { name: /save as sample/i }));

    await waitFor(() => expect(screen.getByText('Saved as sample')).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/assistant-outputs/7/save-sample',
      expect.objectContaining({ body: JSON.stringify({ content: 'Original reply', context_type: 'social_media' }) }),
    );
    expect(screen.queryByRole('combobox', { name: /sample context/i })).not.toBeInTheDocument();
  });

  it('hides the picker when the row has a stored context', () => {
    renderDetail(BASE_ENTRY);
    expect(screen.queryByRole('combobox', { name: /sample context/i })).not.toBeInTheDocument();
  });

  it('shows a save error and re-enables the button when the save is rejected', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('Bad', { status: 400 })));
    renderDetail(BASE_ENTRY);

    fireEvent.click(screen.getByRole('button', { name: /save as sample/i }));

    await waitFor(() => expect(screen.getByText('Failed to save sample.')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /save as sample/i })).not.toBeDisabled();
    expect(screen.queryByText('Saved as sample')).not.toBeInTheDocument();
  });

  it('saves applied edits instead of the latest refinement', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      status: 'saved',
      sample_id: 'sample-9',
      content: 'Hand edit',
    }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    renderDetail({
      ...BASE_ENTRY,
      refinementCount: 1,
      refinements: [{ instruction: 'Shorter', output: 'Refined reply', timestamp: '2026-09-28T13:55:00Z' }],
    });

    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /edit output/i }), { target: { value: 'Hand edit' } });
    fireEvent.click(screen.getByRole('button', { name: /apply edits/i }));
    fireEvent.click(screen.getByRole('button', { name: /save as sample/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/assistant-outputs/7/save-sample',
      expect.objectContaining({ body: JSON.stringify({ content: 'Hand edit' }) }),
    ));
  });

  it('falls back to saving again when the linked sample was deleted', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('Not found', { status: 404 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        status: 'saved',
        sample_id: 'sample-11',
        content: 'Edited reply',
      }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    renderDetail({ ...BASE_ENTRY, savedSample: { id: 'sample-3', content: 'Original reply' } });

    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /edit output/i }), { target: { value: 'Edited reply' } });
    fireEvent.click(screen.getByRole('button', { name: /update sample/i }));

    await waitFor(() => expect(screen.getByText(/saved sample no longer exists/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: /save as sample/i }));
    await waitFor(() => expect(screen.getByText('Saved as sample')).toBeInTheDocument());
    expect(fetchMock).toHaveBeenLastCalledWith(
      'http://localhost:8000/assistant-outputs/7/save-sample',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ content: 'Edited reply' }) }),
    );
  });

  it('updates the linked sample after an edit and surfaces a failed save', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({
        status: 'updated',
        sample_id: 'sample-3',
        content: 'Edited reply',
      }), { status: 200 }))
      .mockResolvedValueOnce(new Response('Failed', { status: 500 }));
    vi.stubGlobal('fetch', fetchMock);
    renderDetail({ ...BASE_ENTRY, savedSample: { id: 'sample-3', content: 'Original reply' } });

    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }));
    const edit = screen.getByRole('textbox', { name: /edit output/i });
    fireEvent.change(edit, { target: { value: 'Edited reply' } });
    fireEvent.click(screen.getByRole('button', { name: /update sample/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8000/user/writing-samples/sample-3',
      expect.objectContaining({ method: 'PATCH', body: JSON.stringify({ content: 'Edited reply' }) }),
    ));

    fireEvent.click(screen.getByRole('button', { name: /apply edits/i }));
    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }));
    fireEvent.change(screen.getByRole('textbox', { name: /edit output/i }), { target: { value: 'Failed update' } });
    fireEvent.click(screen.getByRole('button', { name: /update sample/i }));
    await waitFor(() => expect(screen.getByText('Failed to update the saved sample.')).toBeInTheDocument());
  });
});

function stubLayout(paneHeight: number, actionsHeight: number, contentHeight: number) {
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    get(this: HTMLElement) {
      return this.classList.contains('assistant-output-history-detail') ? paneHeight : 0;
    },
  });
  Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
    configurable: true,
    get(this: HTMLElement) {
      return this.classList.contains('assistant-output-history-detail__actions') ? actionsHeight : 0;
    },
  });
  Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
    configurable: true,
    get(this: HTMLElement) {
      return this instanceof HTMLTextAreaElement ? contentHeight : 0;
    },
  });
}

describe('HistoryDetail edit box sizing', () => {
  it.each([
    [200, '204px'],
    [40, '120px'],
  ])('fits short content of %i px without exceeding the pane', (contentHeight, expected) => {
    stubLayout(500, 28, contentHeight);
    renderDetail(BASE_ENTRY);

    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }));

    expect((screen.getByRole('textbox', { name: /edit output/i }) as HTMLTextAreaElement).style.height).toBe(expected);
  });

  it('grows to the available pane height for long content', () => {
    Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
      configurable: true,
      get(this: HTMLElement) {
        return this.classList.contains('assistant-output-history-detail') ? 500 : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
      configurable: true,
      get(this: HTMLElement) {
        return this.classList.contains('assistant-output-history-detail__actions') ? 28 : 0;
      },
    });
    Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
      configurable: true,
      get(this: HTMLElement) {
        return this instanceof HTMLTextAreaElement ? 900 : 0;
      },
    });
    renderDetail(BASE_ENTRY);

    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }));

    expect((screen.getByRole('textbox', { name: /edit output/i }) as HTMLTextAreaElement).style.height).toBe('400px');
  });
});

describe('HistoryDetail refine buttons', () => {
  afterEach(() => {
    Reflect.deleteProperty(window, 'webkit');
  });

  it.each([
    ['Refine by voice', 'voice'],
    ['Refine by typing', 'typed'],
  ])('%s posts refineFromHistory with input=%s', (label, input) => {
    const postMessage = vi.fn();
    window.webkit = { messageHandlers: { assistantOutputHistoryBridge: { postMessage } } };
    renderDetail(BASE_ENTRY);

    fireEvent.click(screen.getByRole('button', { name: label }));

    expect(postMessage).toHaveBeenCalledWith({ type: 'refineFromHistory', assistantOutputId: 7, input });
  });

  it('no longer renders the single text Refine button', () => {
    renderDetail(BASE_ENTRY);
    expect(screen.queryByRole('button', { name: /^refine$/i })).not.toBeInTheDocument();
  });
});
