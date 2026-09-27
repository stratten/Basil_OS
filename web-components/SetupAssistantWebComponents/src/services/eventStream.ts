import type { SetupAgentEvent, SetupAgentRequest } from '@/types'
import type { FontConfig, ThemeConfig } from '@/theme/themeBootstrap'

declare global {
  interface Window {
    basilSetupAssistantConfig?: {
      apiBaseUrl?: string
      theme?: ThemeConfig
      fonts?: FontConfig
    }
  }
}

const API_BASE = window.basilSetupAssistantConfig?.apiBaseUrl ?? ''

export interface SetupAgentStreamController {
  abort: () => void
}

export function streamSetupAgentEvents(
  request: SetupAgentRequest,
  onEvent: (event: SetupAgentEvent) => void,
  onError: (error: Error) => void,
): SetupAgentStreamController {
  const abortController = new AbortController()

  void readSetupAgentEventStream(request, onEvent, onError, abortController.signal)

  return {
    abort: () => abortController.abort(),
  }
}

async function readSetupAgentEventStream(
  request: SetupAgentRequest,
  onEvent: (event: SetupAgentEvent) => void,
  onError: (error: Error) => void,
  signal: AbortSignal,
) {
  try {
    const response = await fetch(`${API_BASE}/setup-assistant/agent/stream`, {
      method: 'POST',
      headers: {
        Accept: 'text/event-stream',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
      signal,
    })

    if (!response.ok || !response.body) {
      throw new Error('Basil could not start the setup conversation stream.')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (!signal.aborted) {
      const { value, done } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''

      frames.forEach(frame => {
        const dataLine = frame
          .split('\n')
          .find(line => line.startsWith('data:'))
        if (!dataLine) return

        const jsonText = dataLine.replace(/^data:\s?/, '')
        if (!jsonText.trim()) return
        onEvent(JSON.parse(jsonText) as SetupAgentEvent)
      })
    }
  } catch (error) {
    if (signal.aborted) return
    onError(error instanceof Error ? error : new Error(String(error)))
  }
}

