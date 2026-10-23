import type { CSSProperties } from 'react'
import paprikaIcon from '../assets/PaprikaIcon.png'

const brandSources = {
  paprika: paprikaIcon,
  dill: new URL('../../../shared/assets/native-symbols/dill-icon.png', import.meta.url).href,
} as const

const symbolSources = {
  transcription: new URL('../../../shared/assets/native-symbols/transcription-waveform.png', import.meta.url).href,
  speechToText: new URL('../../../shared/assets/native-symbols/transcription-mic-fill.png', import.meta.url).href,
  conversation: new URL('../../../shared/assets/native-symbols/guide-conversation.png', import.meta.url).href,
  activityCapture: new URL('../../../shared/assets/native-symbols/guide-activity-capture.png', import.meta.url).href,
  models: new URL('../../../shared/assets/native-symbols/guide-models.png', import.meta.url).href,
  thinkingModels: new URL('../../../shared/assets/native-symbols/guide-thinking-models.png', import.meta.url).href,
  cloudPricing: new URL('../../../shared/assets/native-symbols/guide-cloud-pricing.png', import.meta.url).href,
  advancedOptions: new URL('../../../shared/assets/native-symbols/guide-advanced-options.png', import.meta.url).href,
  privacy: new URL('../../../shared/assets/native-symbols/guide-privacy.png', import.meta.url).href,
} as const

export type GuideIconName = keyof typeof brandSources | keyof typeof symbolSources | 'dillAndPaprika'

export function GuideIcon({ name, size, className }: { name: GuideIconName; size: number; className?: string }) {
  if (name === 'dillAndPaprika') {
    const logoSize = Math.round(size * 0.85)
    return (
      <span
        aria-hidden="true"
        className={`pug-guide-icon pug-guide-icon--pair${className ? ` ${className}` : ''}`}
        style={{ width: Math.round(logoSize * 1.75), height: size }}
      >
        <img src={brandSources.dill} alt="" style={{ width: logoSize, height: logoSize }} />
        <img src={brandSources.paprika} alt="" style={{ width: logoSize, height: logoSize }} />
      </span>
    )
  }
  if (name in brandSources) {
    return (
      <img
        src={brandSources[name as keyof typeof brandSources]}
        alt=""
        aria-hidden="true"
        className={`pug-guide-icon pug-guide-icon--brand${className ? ` ${className}` : ''}`}
        style={{ width: size, height: size }}
      />
    )
  }
  const source = symbolSources[name as keyof typeof symbolSources]
  // Symbols are black-on-transparent SF Symbol exports, masked so they inherit the surrounding text color.
  const style = {
    width: size,
    height: size,
    backgroundColor: 'currentColor',
    WebkitMaskImage: `url("${source}")`,
    maskImage: `url("${source}")`,
    WebkitMaskSize: 'contain',
    maskSize: 'contain',
    WebkitMaskRepeat: 'no-repeat',
    maskRepeat: 'no-repeat',
    WebkitMaskPosition: 'center',
    maskPosition: 'center',
  } as CSSProperties
  return <span aria-hidden="true" className={`pug-guide-icon${className ? ` ${className}` : ''}`} style={style} />
}
