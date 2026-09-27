import type { SetupDiscoveryFact } from '@/types'

// Pure data helpers used by the discovery hook. Lives outside the hook
// so the predicates can be unit-tested without a React renderer and so
// future tweaks to either rule are obvious in isolation rather than
// buried inside an async fetch flow.

/*
 * Should the user's typed message trigger an opportunistic pull of local
 * sent-email metadata? True only when the message looks like it's about
 * Dill AND about email/reply/draft/voice work — we don't want to fire
 * an OS-level scan for unrelated questions, even ones that mention
 * "email" in passing.
 */
export function shouldCollectEmailMetadataForMessage(content: string): boolean {
  return /dill/i.test(content) && /(email|reply|draft|voice)/i.test(content)
}

/*
 * Merge a new batch of discovery facts into the existing list, preferring
 * the newer fact when ids collide. Order is preserved by insertion (Map
 * iteration order), so existing facts keep their slot and brand-new ids
 * land at the end.
 */
export function mergeDiscoveryFacts(
  existingFacts: SetupDiscoveryFact[],
  newFacts: SetupDiscoveryFact[],
): SetupDiscoveryFact[] {
  const byId = new Map(existingFacts.map(fact => [fact.id, fact]))
  newFacts.forEach(fact => byId.set(fact.id, fact))
  return Array.from(byId.values())
}
