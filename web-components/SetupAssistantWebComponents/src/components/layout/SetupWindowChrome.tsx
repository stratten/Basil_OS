import type { ReactNode } from 'react'

import { BasilWindowChrome } from '../../../../shared/BasilWindowChrome'
import { closeSetupAssistant, collapseSetupAssistant, expandSetupAssistant, minimizeSetupAssistant } from '@/services/bridge'
import { useSetupAssistantTheme } from '@/theme/themeBootstrap'

interface Props {
  title: string
  children: ReactNode
}

export function SetupWindowChrome({ title, children }: Props) {
  useSetupAssistantTheme()

  return (
    <BasilWindowChrome
      title={title}
      onClose={closeSetupAssistant}
      onMinimize={minimizeSetupAssistant}
      onCollapse={collapseSetupAssistant}
      onExpand={expandSetupAssistant}
    >
      {children}
    </BasilWindowChrome>
  )
}
