import React, { useState, useEffect } from 'react'
import '../styles.css'

// Import individual components for selective use
import { AssistantSessionWidgetMock } from '../components/comparison/assistantSession'
import { BasilWireframeWrapper, DrawingWindow } from '../components/comparison/shared'

// Import mock contexts
import { 
  SlackContext,
  IMessageContext,
  EmailContext,
  ResearchContext,
  CalendarContext,
  CodeEditorContext,
  DocumentContext,
} from '../components/comparison/assistantSession/contexts'

interface DemoConfig {
  context: 'email' | 'slack' | 'imessage' | 'research' | 'calendar' | 'code' | 'document'
  requestText: string
  outputText: string
  autoPlay?: boolean
}

// Parse config from URL or window global (set by Swift)
function getConfig(): DemoConfig {
  // Check for window global first (Swift can set this)
  if (typeof window !== 'undefined' && (window as any).basilDemoConfig) {
    return (window as any).basilDemoConfig
  }
  
  // Default demo
  return {
    context: 'email',
    requestText: 'Draft a friendly reply saying I\'m free Tuesday between 10 and 2',
    outputText: 'Hi Julia,\n\nThanks for following up! Tuesday works perfectly. I\'m free between 10am and 2pm ET.\n\nLooking forward to it!\n\nBest,\nSam',
    autoPlay: true,
  }
}

const ContextComponents = {
  email: EmailContext,
  slack: SlackContext,
  imessage: IMessageContext,
  research: ResearchContext,
  calendar: CalendarContext,
  code: CodeEditorContext,
  document: DocumentContext,
}

export function SingleDemo() {
  const [config] = useState(getConfig)
  const [phase, setPhase] = useState<'idle' | 'recording' | 'processing' | 'complete'>('idle')
  const [displayedRequest, setDisplayedRequest] = useState('')
  const [displayedOutput, setDisplayedOutput] = useState('')

  const ContextComponent = ContextComponents[config.context]

  // Auto-play animation
  useEffect(() => {
    if (!config.autoPlay) return

    const timeline = [
      { time: 500, action: () => setPhase('recording') },
      { time: 2000, action: () => setDisplayedRequest(config.requestText.slice(0, 20) + '...') },
      { time: 3000, action: () => setDisplayedRequest(config.requestText) },
      { time: 3500, action: () => setPhase('processing') },
      { time: 5000, action: () => {
        setPhase('complete')
        setDisplayedOutput(config.outputText)
      }},
    ]

    const timers = timeline.map(({ time, action }) => 
      setTimeout(action, time)
    )

    return () => timers.forEach(clearTimeout)
  }, [config])

  return (
    <div className="flex gap-6 p-6 items-start justify-center min-h-screen">
      {/* Context window */}
      <div className="flex-1 max-w-md">
        <DrawingWindow isDrawing={true} delay={0.2} variant="gray">
          <ContextComponent />
        </DrawingWindow>
      </div>

      {/* Basil widget */}
      <div className="flex-1 max-w-sm">
        <BasilWireframeWrapper isDrawing={true} isComplete={phase === 'complete'}>
          <AssistantSessionWidgetMock
            state={phase}
            requestText={displayedRequest}
            assistantSessionOutput={displayedOutput}
            recordingSeconds={phase === 'recording' ? 2 : 0}
          />
        </BasilWireframeWrapper>
      </div>
    </div>
  )
}

export default SingleDemo
