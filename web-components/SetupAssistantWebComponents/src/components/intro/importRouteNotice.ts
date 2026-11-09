import type { SetupAgentModelAccess } from '@/types'

/** One plain sentence saying where an imported text goes, chosen from the route the person confirmed on the model step. */
export function importRouteNotice(access: SetupAgentModelAccess | null): string {
  if (!access || !access.resolved) {
    return 'You have not chosen how I should think yet, so the memory model from Settings reads this. Where that model runs decides where your text goes.'
  }
  if (access.mode === 'local') {
    return 'Your text stays on this Mac. The model you chose to run here reads it.'
  }
  if (access.mode === 'provider_key') {
    const provider = access.provider?.trim() || 'your chosen provider'
    return `Your text is sent to ${provider}, using your own key, so the model you chose there can read it.`
  }
  return 'Your text is sent to Basil\u2019s cloud service so the model you chose can read it.'
}
