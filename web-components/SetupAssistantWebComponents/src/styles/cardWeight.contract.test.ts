// @vitest-environment node

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

function read(relativeToThisFile: string): string {
  return readFileSync(fileURLToPath(new URL(relativeToThisFile, import.meta.url)), 'utf8')
}

const PLAN_STYLESHEETS = [
  './setup-assistant.answer-guide.css',
  './setup-assistant.model-comparison.css',
  './setup-assistant.local-model-failure.css',
  './setup-assistant.starter-downloads.css',
  './setup-assistant.express.css',
  './setup-assistant.hotkeys.css',
  './setup-assistant.model-choice.css',
  '../../../shared/context-import-panel.css',
  '../../../shared/basil-modal-dialog.css',
  '../../../SettingsWebComponents/src/styles/home-settings.css',
  '../../../SettingsWebComponents/src/styles/hotkey-settings.css',
]

describe('card and notice weight', () => {
  it.each(PLAN_STYLESHEETS)('%s draws every border at 1px and has no accent bar down one side', (file) => {
    const css = read(file)
    expect(css).not.toMatch(/\bborder(-top|-right|-bottom|-left)?:\s*([2-9]|\d{2,})px/)
    expect(css).not.toMatch(/\bborder(-top|-right|-bottom|-left)-width:\s*([2-9]|\d{2,})px/)
    expect(css).not.toMatch(/\bborder-left(-color)?:/)
    expect(css).not.toMatch(/\bborder-left-width:/)
  })
})

describe('setup buttons', () => {
  const css = read('./setup-assistant.shared.css')
  const rule = (selector: string) => {
    const start = css.indexOf(`${selector} {`)
    return css.slice(start, css.indexOf('}', start))
  }

  it('uses one compact padding built from the layout tokens, with no outer glow or hover lift', () => {
    expect(css).toContain('padding: calc(var(--padding-xs) + 2px) var(--padding-m);')
    expect(rule('.primary-button')).not.toContain('box-shadow')
    expect(rule('.secondary-button')).not.toContain('box-shadow')
    expect(rule('.primary-button:hover:not(:disabled)')).not.toContain('box-shadow')
    expect(css).not.toContain('translateY(-1px)')
  })
})

describe('download progress and route option color', () => {
  const downloads = read('./setup-assistant.starter-downloads.css')
  const intro = read('./setup-assistant.intro.css')
  const rule = (css: string, selector: string) => {
    const start = css.indexOf(`${selector} {`)
    return css.slice(start, css.indexOf('}', start))
  }

  it('draws the shared progress track slim and borderless, with the amount and percentage in the light weight', () => {
    const shared = read('../../../shared/download-progress.css')
    const track = rule(shared, '.download-progress__track')
    expect(track).toContain('var(--download-progress-track-height, 6px)')
    expect(track).not.toContain('border:')
    expect(rule(shared, '.download-progress__data')).toContain('font-family: var(--font-family-light);')
    expect(rule(downloads, '.model-downloads__state')).not.toContain('font-weight: 700')
    expect(rule(downloads, '.model-downloads__state')).not.toContain('var(--primary)')
  })

  it('draws every download progress with the one shared component, never with its own copy of the bar', () => {
    expect(downloads).not.toContain('.model-downloads__bar')
    expect(downloads).not.toContain('.model-downloads__percent')
    expect(intro).not.toContain('.choice-option-download-bar')
    expect(read('../components/intro/IntroAndPrivacy.tsx')).toContain('<DownloadProgress')
    expect(read('../components/layout/ModelDownloadRows.tsx')).toContain('<DownloadProgress')
  })

  it('adds no pill or filled badge to a selected route', () => {
    const note = rule(read('./setup-assistant.model-choice.css'), '.choice-option-pending-note')
    expect(note).not.toContain('background')
    expect(note).not.toContain('border')
    expect(note).not.toContain('border-radius')
  })

  it('gives each route its own quiet tint and thin border without a bar', () => {
    const tinted = rule(intro, '.intro-privacy .choice-option:is(.choice-option--local, .choice-option--provider_key, .choice-option--basil_cloud)')
    expect(tinted).toContain('background: color-mix(in srgb, var(--choice-accent) 7%, var(--background-primary));')
    expect(tinted).toContain('border-color: color-mix(in srgb, var(--choice-accent) 45%, var(--separator-color));')
    expect(intro).not.toContain('.intro-privacy .choice-option::before')
  })
})

describe('plan components use classes, not inline styles', () => {
  it.each([
    '../components/intro/IntroDownloadsStep.tsx',
    '../components/intro/LocalModelChooser.tsx',
    '../components/intro/BasilCloudAccountModal.tsx',
    '../components/intro/BasilCloudAccountPanel.tsx',
    '../components/intro/IntroHotkeysStep.tsx',
    '../components/intro/IntroTrustNote.tsx',
    '../components/intro/ModelComparison.tsx',
    '../components/layout/LocalModelFailureBanner.tsx',
    '../components/conversation/AnswerGuide.tsx',
    '../../../shared/ContextImportPanel.tsx',
    '../../../shared/BasilModalDialog.tsx',
  ])('%s sets no inline style', (file) => {
    expect(read(file)).not.toContain('style={{')
  })

  it('keeps the learning step single-column: the import section does not reuse the toggle disclosure class that pins itself to column 2', () => {
    expect(read('../components/intro/IntroContextImport.tsx')).not.toContain('intro-toggle-details')
  })

  it('puts the optional import before the approval note, so a short window still shows it above the fold', () => {
    const source = read('../components/intro/IntroAndPrivacy.tsx')
    expect(source.indexOf('<IntroContextImport')).toBeGreaterThan(-1)
    expect(source.indexOf('<IntroTrustNote />')).toBeGreaterThan(source.indexOf('<IntroContextImport'))
  })

  it('uses no 600 or 700 font weight in the shared import panel, the learning step toggles, or the approval note', () => {
    const importPanel = read('../../../shared/context-import-panel.css')
    expect(importPanel).not.toMatch(/font-weight:\s*[67]00/)
    const guide = read('./setup-assistant.answer-guide.css')
    const trustNote = guide.slice(guide.indexOf('.intro-trust-note {'))
    expect(trustNote).not.toMatch(/font-weight:\s*[67]00/)
    expect(guide.slice(guide.indexOf('.intro-context-import > summary'), guide.indexOf('/* The hotkeys step. */'))).not.toMatch(/font-weight:\s*[67]00/)
    const intro = read('./setup-assistant.intro.css')
    const toggleTitle = intro.slice(intro.indexOf('.intro-capture-toggle-body strong {'))
    expect(toggleTitle.slice(0, toggleTitle.indexOf('}'))).toContain('font-weight: normal;')
  })

  it('keeps the import title out of reach of the step heading rule, so it has no extra top margin or headline size', () => {
    const importPanel = read('../../../shared/context-import-panel.css')
    expect(importPanel).toContain('.context-import .context-import-title {')
    const title = importPanel.slice(importPanel.indexOf('.context-import .context-import-title {'))
    expect(title.slice(0, title.indexOf('}'))).toMatch(/margin: 0;/)
  })

  it('gives the opened import section its own spacing, because a details element is not a grid item of the step', () => {
    const guide = read('./setup-assistant.answer-guide.css')
    expect(guide).toMatch(/\.intro-context-import > \.intro-step-lede \{\s*margin-top: var\(--padding-s\);/)
    expect(guide).toMatch(/\.intro-context-import > \.context-import \{\s*margin-top: var\(--padding-m\);/)
    const trustNote = guide.slice(guide.indexOf('.intro-trust-note {'))
    expect(trustNote.slice(0, trustNote.indexOf('}'))).toContain('margin: 0;')
  })

  it('sizes the route notice to its text and keeps a visible thin border', () => {
    const importPanel = read('../../../shared/context-import-panel.css')
    const notice = importPanel.slice(importPanel.indexOf('.context-import-route-notice {'))
    const body = notice.slice(0, notice.indexOf('}'))
    expect(body).toContain('width: fit-content;')
    expect(body).toContain('border: var(--border-thin, 1px) solid var(--primary);')
  })

  it('never shows the browser file control, whose system button, text and file icon match nothing else in the app', () => {
    const importPanel = read('../../../shared/context-import-panel.css')
    expect(importPanel).not.toContain('file-selector-button')
    const hidden = importPanel.slice(importPanel.indexOf('.context-import-file {'))
    expect(hidden.slice(0, hidden.indexOf('}'))).toContain('display: none;')
    const source = read('../../../shared/ImportSourceInput.tsx')
    expect(source).toContain('fileInputRef.current?.click()')
    expect(source).toContain('Choose a file')
  })

  it('writes no doubled percent sign in the shared import stylesheet, which would make the declaration invalid and silently drop it', () => {
    expect(read('../../../shared/context-import-panel.css')).not.toContain('%%')
  })

  it('spaces the review and done blocks as columns, so no button touches the outline of the card above it', () => {
    const importPanel = read('../../../shared/context-import-panel.css')
    const start = importPanel.indexOf('.context-import-review-panel,')
    const body = importPanel.slice(start, importPanel.indexOf('}', start))
    expect(body).toContain('.context-import-done {')
    expect(body).toContain('display: flex;')
    expect(body).toContain('flex-direction: column;')
    expect(body).toContain('gap: 10px;')
    expect(importPanel).toContain('.context-import-review-panel .context-import-actions {')
    expect(importPanel).toContain('.context-import-modal-actions {')
  })

  it('stacks Now and After in one column so a Markdown profile gets the full dialog width', () => {
    const importPanel = read('../../../shared/context-import-panel.css')
    const start = importPanel.indexOf('.context-import-profile-columns {')
    const body = importPanel.slice(start, importPanel.indexOf('}', start))
    expect(body).toContain('grid-template-columns: minmax(0, 1fr);')
    expect(body).not.toContain('auto-fit')
  })

  it('keeps the thinking panel bordered, capped in height and scrollable, so long thinking never grows the dialog', () => {
    const importPanel = read('../../../shared/context-import-panel.css')
    const start = importPanel.indexOf('.context-import-thinking {')
    const body = importPanel.slice(start, importPanel.indexOf('}', start))
    expect(body).toContain('border: var(--border-thin, 1px) solid')
    expect(body).toContain('max-height: 200px;')
    expect(body).toContain('overflow-y: auto;')
    expect(body).toContain('white-space: pre-wrap;')
  })

  it('stops the progress motion for people who ask for reduced motion', () => {
    const importPanel = read('../../../shared/context-import-panel.css')
    const media = importPanel.slice(importPanel.indexOf('@media (prefers-reduced-motion: reduce)'))
    const body = media.slice(0, media.indexOf('\n}\n'))
    expect(body).toContain('.context-import-progress-fill::after')
    expect(body).toContain('.context-import-stage--active .context-import-stage-marker')
    expect(body).toContain('animation: none;')
  })

  it('draws step headings, express summaries, the local model chooser label and the clash notice emphasis without a bold weight, which WebKit fakes on the medium and light faces', () => {
    const block = (file: string, selector: string) => {
      const css = read(file)
      const start = css.indexOf(`${selector} {`)
      expect(start).toBeGreaterThanOrEqual(0)
      return css.slice(start, css.indexOf('}', start))
    }
    expect(block('./setup-assistant.intro.css', '.intro-step-body h3')).toContain('font-weight: normal;')
    expect(block('./setup-assistant.express.css', '.express-hotkeys > summary')).toContain('font-weight: normal;')
    expect(block('./setup-assistant.starter-downloads.css', '.local-model-chooser__label')).toContain('font-weight: normal;')
    const clash = block('./setup-assistant.hotkeys.css', '.intro-hotkey-conflict strong')
    expect(clash).toContain('font-family: var(--font-family-light);')
    expect(clash).toContain('font-weight: normal;')
  })

  it('keeps the clash notice tinted with a thin border, so it is a visible box and not only a color', () => {
    const css = read('./setup-assistant.hotkeys.css')
    const notice = css.slice(css.indexOf('.intro-hotkey-conflict {'))
    const body = notice.slice(0, notice.indexOf('}'))
    expect(body).toContain('background: color-mix(in srgb, var(--notice-base) 14%, var(--background-primary));')
    expect(body).toContain('border: var(--border-thin) solid var(--notice-base);')
  })

  it('labels the validation-only local model chooser briefly', () => {
    expect(read('../components/intro/LocalModelChooser.tsx')).toContain('Local model (validation only)')
  })

  it('sets no inline style in the download rows, because the shared progress sets its own fill width', () => {
    expect(read('../components/layout/ModelDownloadRows.tsx')).not.toContain('style={{')
    expect(read('../../../shared/DownloadProgress.tsx').split('style={{')).toHaveLength(2)
  })
})
