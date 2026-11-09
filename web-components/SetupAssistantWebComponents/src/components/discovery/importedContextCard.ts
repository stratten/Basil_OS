import type { SetupImportedContextSummary } from '@/state/setupAssistantStore'

export interface ImportedContextCard {
  label: string
  title: string
  detail: string
}

/** What the orientation step shows first when the person already imported background during setup, or null when nothing usable was imported. */
export function describeImportedContext(summary: SetupImportedContextSummary | null | undefined): ImportedContextCard | null {
  if (!summary) return null
  const notes = summary.entries_added
  const facts = summary.facts_proposed
  const hasProfile = Boolean(summary.profile_updated)
  if (!hasProfile && notes === 0 && facts === 0) return null

  const sentences: string[] = []
  if (hasProfile) sentences.push(summary.profile_summary?.trim() || 'You saved a profile from what you imported.')
  if (notes > 0) sentences.push(`${notes} ${notes === 1 ? 'note is' : 'notes are'} in your searchable history.`)
  if (facts > 0) sentences.push(`${facts} ${facts === 1 ? 'fact is' : 'facts are'} waiting for your approval.`)

  return {
    label: 'From what you imported',
    title: hasProfile ? 'Your profile is already in place' : 'Your imported context is in place',
    detail: sentences.join(' '),
  }
}
