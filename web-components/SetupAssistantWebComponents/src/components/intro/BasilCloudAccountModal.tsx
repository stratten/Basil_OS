import { useState } from 'react'

import { BasilModalDialog } from '@shared/dialogs/BasilModalDialog'

import { BasilCloudAccountPanel, type AccountFormMode } from './BasilCloudAccountPanel'
import type { SetupAgentModelAccessOption } from '@/types'

interface Props {
  option: SetupAgentModelAccessOption
  refreshOptions: () => Promise<void>
  onClose: () => void
}

/** Holds the Basil Cloud sign-in, sign-up, and payment prompts in the shared Basil modal, which only exists after the user chooses Basil Cloud. */
export function BasilCloudAccountModal({ option, refreshOptions, onClose }: Props) {
  // The title names what the form below is for, so it follows the sign-in and create-account toggle.
  const [mode, setMode] = useState<AccountFormMode>('signIn')
  const title = !option.requires_sign_in
    ? 'Add a payment method for Basil Cloud'
    : mode === 'signUp' ? 'Create an account to use Basil Cloud' : 'Sign in to use Basil Cloud'

  return (
    <BasilModalDialog title={title} onClose={onClose} testId="basil-cloud-account-modal">
      <p>
        Basil Cloud runs the model for you on Basil's servers, so there is nothing to download and no API key to manage. You use it through a Basil account, and usage is billed to a card.
      </p>
      <ul className="basil-cloud-modal-trust" aria-label="What to expect">
        <li>Your card is handled by Stripe on a secure page in your browser. Basil never sees it.</li>
        <li>The setup conversation is routed through Basil Cloud while you use this option.</li>
        <li>You can switch to a local model or your own key at any time in Settings.</li>
      </ul>
      <BasilCloudAccountPanel
        key={option.requires_sign_in ? 'sign-in' : 'payment'}
        option={option}
        refreshOptions={refreshOptions}
        onCancel={onClose}
        onModeChange={setMode}
      />
    </BasilModalDialog>
  )
}
