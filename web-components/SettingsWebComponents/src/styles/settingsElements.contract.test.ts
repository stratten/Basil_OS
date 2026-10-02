import { readdirSync, readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const stylesDirectory = 'src/styles'
const sharedStylesheetName = 'settings-elements.css'
const cardShadow = '0 1px 3px rgb(0 0 0 / 10%), 0 8px 20px rgb(0 0 0 / 8%)'

interface CssRule {
  selectors: string[]
  body: string
}

function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, '')
}

function readStylesheet(fileName: string): string {
  return stripComments(readFileSync(`${stylesDirectory}/${fileName}`, 'utf8'))
}

function parseRules(css: string): CssRule[] {
  return Array.from(css.matchAll(/([^{}]+)\{([^{}]*)\}/g), (match) => ({
    selectors: match[1]
      .split(',')
      .map((selector) => selector.trim().replace(/\s+/g, ' '))
      .filter((selector) => selector.length > 0),
    body: match[2],
  }))
}

function ruleStartingWith(rules: CssRule[], firstSelector: string): CssRule {
  const rule = rules.find((candidate) => candidate.selectors[0] === firstSelector)
  if (!rule) {
    throw new Error(`No rule starts with ${firstSelector}`)
  }
  return rule
}

const sharedRules = parseRules(readStylesheet(sharedStylesheetName))
const leafStylesheetNames = readdirSync(stylesDirectory)
  .filter((fileName) => fileName.endsWith('.css') && fileName !== sharedStylesheetName)
  .sort()

describe('Settings element primitives', () => {
  it('loads the shared stylesheet before SettingsShell and every leaf stylesheet', () => {
    const main = readFileSync('src/main.tsx', 'utf8')
    const sharedImport = main.indexOf("import './styles/settings-elements.css'")
    expect(sharedImport).toBeGreaterThanOrEqual(0)
    expect(sharedImport).toBeLessThan(main.indexOf("import { SettingsShell } from './app/SettingsShell'"))
    expect(sharedImport).toBeLessThan(main.indexOf("import './styles/appearance-settings.css'"))
  })

  it('defines the type-size tokens and a 13px body base instead of the 16px browser default', () => {
    const rootRule = ruleStartingWith(sharedRules, ':root')
    expect(rootRule.body).toContain('--font-size-callout: 13px;')
    expect(rootRule.body).toContain('--font-size-status-tiny: 10px;')
    expect(ruleStartingWith(sharedRules, 'body').body).toContain('font-size: var(--font-size-callout);')
  })

  it('themes every text-entry field and textarea by default', () => {
    const fieldRule = ruleStartingWith(sharedRules, ":where(input:is([type='text']")
    expect(fieldRule.selectors.join(', ')).toContain('textarea)')
    expect(fieldRule.body).toContain('background: var(--background-primary);')
    expect(fieldRule.body).toContain('border: 1px solid var(--field-border);')
    expect(fieldRule.body).toContain('color: var(--text-primary);')
    expect(fieldRule.body).toContain('min-height: 26px;')
    expect(fieldRule.body).toContain('padding: 4px 8px;')
  })

  it('gives every Settings section the canonical card', () => {
    const cardRule = ruleStartingWith(sharedRules, '.meetings-settings-section')
    expect(cardRule.selectors).toEqual([
      '.meetings-settings-section',
      '.browser-automation-section',
      '.reasoning-defaults-section',
      '.proactive-suggestions-section',
      '.skills-settings-section',
      '.home-settings-section',
      '.hotkey-settings-section',
      '.appearance-settings-section',
      '.profile-settings-section',
      '.memory-intelligence-section',
      '.models-settings-provider-group',
      '.models-settings-vision-section',
      '.writing-examples-style-section',
      '.writing-examples-samples-section',
      '.transcription-settings-section',
      '.transcription-history-panel',
      '.activity-capture-card',
      '.memories-card',
      '.account-settings-section',
      '.permissions-command-security-section',
      '.connections-panel',
      '.connections-call-log',
    ])
    expect(cardRule.body).toContain('background: color-mix(in srgb, var(--background-primary) 92%, var(--primary));')
    expect(cardRule.body).toContain('border-radius: 10px;')
    expect(cardRule.body).toContain(`box-shadow: ${cardShadow};`)
    expect(cardRule.body).toContain('padding: 16px;')
  })

  it('gives every section title the same type treatment', () => {
    const titleRule = ruleStartingWith(sharedRules, '.meetings-settings-section h2')
    expect(titleRule.selectors).toEqual([
      '.meetings-settings-section h2',
      '.browser-automation-section h2',
      '.reasoning-defaults-section h2',
      '.proactive-suggestions-section h2',
      '.skills-settings-section h2',
      '.home-settings-section h2',
      '.hotkey-settings-section h2',
      '.appearance-settings-section h2',
      '.profile-settings-section h2',
      '.memory-intelligence-section h2',
      '.models-settings-provider-group h2',
      '.models-settings-vision-section h2',
      '.writing-examples-style-section h2',
      '.writing-examples-samples-section h2',
      '.transcription-settings-section h2',
      '.activity-capture-card h3',
      '.memories-card h3',
      '.account-settings-section h3',
      '.permissions-command-security-section-title',
      '.connections-panel-header h3',
      '.connections-call-log-header h3',
    ])
    expect(titleRule.body).toContain('font-size: 15px;')
    expect(titleRule.body).toContain('color: var(--text-primary);')
  })

  it('gives every hint the same secondary text treatment', () => {
    const hintRule = ruleStartingWith(sharedRules, '.meetings-settings-hint')
    expect(hintRule.selectors).toEqual([
      '.meetings-settings-hint',
      '.app-exclusion-hint',
      '.browser-automation-field-hint',
      '.reasoning-defaults-field-hint',
      '.proactive-suggestions-field-hint',
      '.skills-settings-field-hint',
      '.home-settings-hint',
      '.transcription-settings-hint',
      '.activity-capture-hint',
      '.memories-hint',
      '.account-settings-hint',
      '.profile-settings-field-hint',
      '.mac-contacts-settings-description',
      '.memory-intelligence-cadence',
      '.reasoning-api-models-key-explainer',
      '.reasoning-api-models-key-required',
      '.permissions-command-security-section-description',
      '.connections-add-form-hint',
      '.provider-profiles-subtitle',
      '.custom-models-form-field-hint',
    ])
    expect(hintRule.body).toContain('color: var(--text-secondary);')
    expect(hintRule.body).toContain('font-size: 12px;')
  })

  it('pulls every hint up against the element it describes', () => {
    const cardHintRule = sharedRules.find((rule) => rule.selectors[0].startsWith(':is(.meetings-settings-section'))
    const subcardHintRule = sharedRules.find((rule) => rule.selectors[0].startsWith(':is(.activity-capture-subcard'))
    expect(cardHintRule?.body).toContain('margin-top: -10px;')
    expect(subcardHintRule?.body).toContain('margin-top: -8px;')
    const cardSelector = cardHintRule?.selectors.join(', ') ?? ''
    for (const blockCard of ['.appearance-settings-section', '.hotkey-settings-section', '.permissions-command-security-section', '.connections-call-log']) {
      expect(cardSelector).not.toContain(blockCard)
    }
    for (const hint of ['.meetings-settings-hint', '.transcription-settings-hint', '.reasoning-defaults-field-hint', '.home-settings-hint', '.memories-hint', '.mac-contacts-settings-description']) {
      expect(cardSelector).toContain(hint)
    }
  })

  it('sizes every dropdown trigger like a text field', () => {
    const dropdownRule = ruleStartingWith(sharedRules, '.tokenized-select > .tokenized-select__trigger')
    expect(dropdownRule.body).toContain('font-size: 13px;')
    expect(dropdownRule.body).toContain('min-height: 26px;')
    expect(dropdownRule.body).toContain('padding: 4px 8px;')
  })

  it('sizes every numeric stepper field the same way', () => {
    expect(ruleStartingWith(sharedRules, '.meetings-numeric-field input').selectors).toEqual([
      '.meetings-numeric-field input',
      '.transcription-push-to-talk-threshold input',
      '.permissions-timeout-stepper input',
      ".proactive-suggestions-frequency input[type='number']",
      ".reasoning-defaults-threshold-row input[type='number']",
    ])
  })

  it('uses compact sizing for primary, secondary, and danger buttons', () => {
    const baseRule = ruleStartingWith(sharedRules, '.primary-button')
    expect(baseRule.selectors).toEqual(['.primary-button', '.secondary-button', '.permissions-application-refresh'])
    const dangerOutlineRule = ruleStartingWith(sharedRules, '.models-settings-delete-button')
    expect(dangerOutlineRule.selectors).toEqual([
      '.models-settings-delete-button',
      '.models-settings-cancel-button',
      '.writing-examples-delete-button',
      '.writing-examples-delete-all-button',
      '.memory-intelligence-decline-button',
      '.profile-settings-clear-button',
      '.reasoning-api-models-key-remove-button',
      '.account-delete-button',
      '.connections-device-flow-cancel',
    ])
    const dangerFilledRule = ruleStartingWith(sharedRules, '.account-delete-confirm-button')
    expect(dangerFilledRule.selectors).toEqual([
      '.account-delete-confirm-button',
      '.reasoning-api-models-key-remove-confirm-button',
      '.appearance-theme-delete-confirm-button',
    ])
    for (const rule of [baseRule, dangerOutlineRule, dangerFilledRule]) {
      expect(rule.body).toContain('font-size: 12px;')
      expect(rule.body).toContain('min-height: 30px;')
      expect(rule.body).toContain('padding: 6px 12px;')
    }
  })

  it('finds every leaf stylesheet', () => {
    expect(leafStylesheetNames).toHaveLength(23)
  })

  it.each(leafStylesheetNames)('%s leaves element defaults to the shared stylesheet', (fileName) => {
    const css = readStylesheet(fileName)
    expect(css).not.toContain('accent-color')
    expect(css).not.toContain('font-family: inherit')
    expect(css).not.toContain(cardShadow)
    const unscopedButtonSelectors = parseRules(css)
      .flatMap((rule) => rule.selectors)
      .filter((selector) => selector.startsWith('.primary-button') || selector.startsWith('.secondary-button'))
    expect(unscopedButtonSelectors).toEqual([])
  })
})

describe('Meetings detection layout', () => {
  it('puts On detection and Check Every in the left column and Cooldown in the right column', () => {
    const source = readFileSync('src/app/MeetingsSettingsApp.tsx', 'utf8')
    const columns = source.indexOf('className="meetings-detection-columns"')
    const firstColumn = source.indexOf('className="meetings-detection-column"', columns)
    const secondColumn = source.indexOf('className="meetings-detection-column"', firstColumn + 1)
    expect(columns).toBeGreaterThanOrEqual(0)
    expect(firstColumn).toBeLessThan(source.indexOf('legend="On detection"'))
    expect(source.indexOf('legend="On detection"')).toBeLessThan(source.indexOf('label="Check Every"'))
    expect(source.indexOf('label="Check Every"')).toBeLessThan(secondColumn)
    expect(secondColumn).toBeLessThan(source.indexOf('legend="Cooldown"'))
  })

  it('lays the automation mode switches out in two columns that collapse on narrow widths', () => {
    const source = readFileSync('src/components/MeetingAutomationPanel.tsx', 'utf8')
    expect(source.indexOf('<legend>Modes</legend>')).toBeLessThan(source.indexOf('className="meetings-automation-mode-grid"'))
    expect(source.indexOf('className="meetings-automation-mode-grid"')).toBeLessThan(source.indexOf('className="meetings-automation-mode-toggle"'))
    const css = readStylesheet('meetings-settings.css')
    const gridRules = parseRules(css).filter((rule) => rule.selectors[0] === '.meetings-automation-mode-grid')
    expect(gridRules.map((rule) => rule.body.includes('repeat(2, minmax(0, 1fr))'))).toContain(true)
    expect(gridRules.map((rule) => /grid-template-columns: minmax\(0, 1fr\);/.test(rule.body))).toContain(true)
  })
})

describe('Settings spacing and chrome type sizes', () => {
  const cardContainers: Array<[string, string]> = [
    ['account-settings.css', '.account-settings'],
    ['activity-capture-settings.css', '.activity-capture-shell'],
    ['appearance-settings.css', '.appearance-settings-shell'],
    ['capture-settings.css', '.capture-settings-shell'],
    ['connections-settings.css', '.connections-settings-shell'],
    ['connections-settings.css', ".connections-settings-shell > [role='tabpanel']"],
    ['home-settings.css', '.home-settings-shell'],
    ['home-settings.css', '.home-settings-overview-grid'],
    ['home-settings.css', '.home-settings-compact-grid'],
    ['hotkey-settings.css', '.hotkey-settings-shell'],
    ['meetings-settings.css', '.meetings-settings-shell'],
    ['memories-settings.css', '.memories-shell'],
    ['memory-intelligence-settings.css', '.memory-intelligence-shell'],
    ['models-settings.css', '.models-settings-shell'],
    ['permissions-settings.css', '.permissions-settings-shell'],
    ['permissions-settings.css', '.permissions-application-panel'],
    ['permissions-settings.css', '.permissions-command-security-pair'],
    ['proactive-suggestions-settings.css', '.proactive-suggestions-shell'],
    ['profile-settings.css', '.profile-settings-shell'],
    ['profile-settings.css', '.profile-settings-columns'],
    ['reasoning-defaults-settings.css', '.reasoning-automation-shell'],
    ['reasoning-defaults-settings.css', '.reasoning-defaults-shell'],
    ['skills-settings.css', '.skills-settings-shell'],
    ['skills-settings.css', '.skills-settings-lists'],
    ['transcription-settings.css', '.transcription-settings-shell'],
    ['transcription-settings.css', '.transcription-settings-panel'],
    ['writing-examples-settings.css', '.writing-examples-shell'],
  ]

  it('spaces every card stack with the shared 12px card gap', () => {
    expect(ruleStartingWith(sharedRules, ':root').body).toContain('--settings-card-gap: 12px;')
    for (const [fileName, selector] of cardContainers) {
      const rule = ruleStartingWith(parseRules(readStylesheet(fileName)), selector)
      expect(rule.body, `${fileName} ${selector}`).toContain('gap: var(--settings-card-gap);')
    }
  })

  it('steps the navigation down from 14px group headings to 13px items and sizes the Settings window title at 16px', () => {
    const shellRules = parseRules(readStylesheet('settings-shell.css'))
    expect(ruleStartingWith(shellRules, '.settings-shell-navigation-heading').body).toContain('font-size: 14px;')
    expect(ruleStartingWith(shellRules, '.settings-shell-nav-item').body).toContain('font-size: var(--font-size-callout);')
    expect(ruleStartingWith(shellRules, '.basil-window-title').body).toContain('font-size: 16px;')
  })

  it('lays the Appearance colors out as Background and Text beside Primary and Secondary', () => {
    const source = readFileSync('src/app/AppearanceSettingsApp.tsx', 'utf8')
    const firstColumn = source.indexOf('className="appearance-color-column"')
    const secondColumn = source.indexOf('className="appearance-color-column"', firstColumn + 1)
    expect(source.indexOf('className="appearance-color-columns"')).toBeLessThan(firstColumn)
    expect(firstColumn).toBeLessThan(source.indexOf('id="appearance-background-color"'))
    expect(source.indexOf('id="appearance-background-color"')).toBeLessThan(source.indexOf('id="appearance-text-color"'))
    expect(source.indexOf('id="appearance-text-color"')).toBeLessThan(secondColumn)
    expect(secondColumn).toBeLessThan(source.indexOf('id="appearance-primary-color"'))
    expect(source.indexOf('id="appearance-primary-color"')).toBeLessThan(source.indexOf('id="appearance-secondary-color"'))
    const appearanceRules = parseRules(readStylesheet('appearance-settings.css'))
    expect(ruleStartingWith(appearanceRules, '.appearance-color-columns').body).toContain('repeat(2, minmax(0, 1fr))')
    const colorLabelRule = ruleStartingWith(appearanceRules, '.appearance-color-field-label')
    expect(colorLabelRule.body).toContain('font-size: 12px;')
    expect(colorLabelRule.body).toContain('width: 120px;')
    expect(colorLabelRule.body).toContain('white-space: nowrap;')
    expect(ruleStartingWith(appearanceRules, '.appearance-color-field-hex').body).toContain('font-size: 12px;')
  })
})
