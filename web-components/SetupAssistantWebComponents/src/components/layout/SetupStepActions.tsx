import { createContext, useContext, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

const SetupStepActionsSlotContext = createContext<HTMLElement | null>(null)

export const SetupStepActionsSlotProvider = SetupStepActionsSlotContext.Provider

interface Props {
  children: ReactNode
}

// Places a step's own actions (Back, Continue, Done, Close) in the shell's bottom bar, so they never scroll away with variable-height step content. Outside the shell it renders in place.
export function SetupStepActions({ children }: Props) {
  const slot = useContext(SetupStepActionsSlotContext)
  const actions = <div className="setup-step-actions setup-motion-enter">{children}</div>
  return slot ? createPortal(actions, slot) : actions
}
