import { useRef, useState } from 'react'

import {
  fetchConnectionCatalogDiscovery,
  fetchEmailClientDiscovery,
  fetchLowRiskDiscovery,
  fetchModelCatalogDiscovery,
  fetchSentEmailMetadataDiscovery,
} from '@/services/api'
import type { useSetupAssistantStore } from '@/state/setupAssistantStore'
import type { SetupDiscoveryFact } from '@/types'

import {
  mergeDiscoveryFacts,
  shouldCollectEmailMetadataForMessage,
} from '../setupAssistantDiscoveryHelpers'

type SetupAssistantStore = ReturnType<typeof useSetupAssistantStore>

// Owns the two discovery flows that feed the setup agent's context:
// (1) the four parallel low-risk catalog fetches that run once when the
//     orientation stage begins, and
// (2) the on-demand sent-email metadata pull triggered only when the
//     user's typed message looks Dill-and-email related.
//
// The in-flight ref guards against duplicate orientation fetches if the
// user double-clicks Continue or the React tree re-mounts mid-fetch; the
// loading flag drives the orientation UI's "Basil is getting oriented"
// state. Errors set the store's user-facing error message but still
// return the existing facts so the caller can keep going with a partial
// dataset rather than blocking the flow on a soft failure.

export interface SetupDiscoveryApi {
  fetchDiscoveryFactsForOrientation: () => Promise<SetupDiscoveryFact[]>
  collectOptionalEmailMetadataIfUseful: (content: string) => Promise<SetupDiscoveryFact[] | undefined>
  isDiscoveryFetching: boolean
}

export function useSetupDiscovery({
  store,
}: {
  store: SetupAssistantStore
}): SetupDiscoveryApi {
  const discoveryFetchInFlightRef = useRef(false)
  const [isDiscoveryFetching, setIsDiscoveryFetching] = useState(false)

  const fetchDiscoveryFactsForOrientation = async (): Promise<SetupDiscoveryFact[]> => {
    if (discoveryFetchInFlightRef.current) {
      return store.state.discoveryFacts
    }
    discoveryFetchInFlightRef.current = true
    setIsDiscoveryFetching(true)
    try {
      const responses = await Promise.all([
        fetchLowRiskDiscovery(),
        fetchModelCatalogDiscovery(),
        fetchEmailClientDiscovery(),
        fetchConnectionCatalogDiscovery(),
      ])
      const merged = responses.flatMap(response => response.facts ?? [])
      store.setDiscoveryFacts(merged)
      return merged
    } catch (error) {
      store.setError(error instanceof Error
        ? `Basil could not finish the setup discovery sweep: ${error.message}`
        : 'Basil could not finish the setup discovery sweep.')
      return store.state.discoveryFacts
    } finally {
      discoveryFetchInFlightRef.current = false
      setIsDiscoveryFetching(false)
    }
  }

  const collectOptionalEmailMetadataIfUseful = async (
    content: string,
  ): Promise<SetupDiscoveryFact[] | undefined> => {
    if (!shouldCollectEmailMetadataForMessage(content)) {
      return undefined
    }
    try {
      const response = await fetchSentEmailMetadataDiscovery()
      const mergedFacts = mergeDiscoveryFacts(store.state.discoveryFacts, response.facts ?? [])
      store.setDiscoveryFacts(mergedFacts)
      return mergedFacts
    } catch (error) {
      store.setError(error instanceof Error
        ? `Basil could not read email metadata for that setup path: ${error.message}`
        : 'Basil could not read email metadata for that setup path.')
      return store.state.discoveryFacts
    }
  }

  return { fetchDiscoveryFactsForOrientation, collectOptionalEmailMetadataIfUseful, isDiscoveryFetching }
}
