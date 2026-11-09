import { useEffect, useState } from 'react'

import { fetchLocalModelComparison, type LocalModelComparison } from '@/services/api'

type LoadState = 'loading' | 'ready' | 'unavailable'

interface FixedRoute {
  name: string
  where: string
  size: string
  speed: string
  quality: string
  memory: string
}

// The two routes that are not downloaded models, so the registry has no ratings for them.
const FIXED_ROUTES: FixedRoute[] = [
  { name: 'Basil Cloud', where: 'Basil\'s servers', size: 'No download', speed: 'Fastest', quality: 'Strongest', memory: 'None on your Mac' },
  { name: 'Your own API key', where: 'The AI company you choose', size: 'No download', speed: 'Fast', quality: 'Depends on the model', memory: 'None on your Mac' },
]

export function formatMemory(recommendedRam: string): string {
  const trimmed = recommendedRam.trim()
  return trimmed ? `${trimmed} or more` : 'Not listed'
}

export function ModelComparison() {
  const [comparison, setComparison] = useState<LocalModelComparison | null>(null)
  const [loadState, setLoadState] = useState<LoadState>('loading')

  useEffect(() => {
    let canceled = false
    fetchLocalModelComparison()
      .then(result => {
        if (canceled) return
        setComparison(result)
        setLoadState('ready')
      })
      .catch(() => {
        if (!canceled) setLoadState('unavailable')
      })
    return () => { canceled = true }
  }, [])

  return (
    <div className="model-comparison" data-testid="model-comparison">
      <table className="model-comparison-table">
        <caption>Compared side by side</caption>
        <thead>
          <tr>
            <th scope="col">Option</th>
            <th scope="col">Runs on</th>
            <th scope="col">Size</th>
            <th scope="col">Speed</th>
            <th scope="col">Quality</th>
            <th scope="col">Memory it wants</th>
          </tr>
        </thead>
        <tbody>
          {FIXED_ROUTES.map(route => (
            <tr key={route.name}>
              <th scope="row">{route.name}</th>
              <td>{route.where}</td>
              <td>{route.size}</td>
              <td>{route.speed}</td>
              <td>{route.quality}</td>
              <td>{route.memory}</td>
            </tr>
          ))}
          {comparison?.models.map(model => (
            <tr key={model.modelId} data-compatible={model.systemCompatible}>
              <th scope="row">{model.displayName}{model.systemCompatible ? '' : ' (may be too large for this Mac)'}</th>
              <td>Your Mac</td>
              <td>{model.size}</td>
              <td>{model.speedRating} out of 10</td>
              <td>{model.accuracyRating} out of 10</td>
              <td>{formatMemory(model.recommendedRam)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {loadState === 'loading' && <p className="model-comparison-note" role="status">Looking up the models that suit this Mac.</p>}
      {loadState === 'unavailable' && <p className="model-comparison-note" role="status">I could not read the local model list right now. The two options above still apply.</p>}
      {loadState === 'ready' && comparison?.totalRamGB != null && (
        <p className="model-comparison-note">This Mac has {comparison.totalRamGB} GB of memory. Local models run on your Mac, so memory is what limits how large one can be.</p>
      )}
    </div>
  )
}
