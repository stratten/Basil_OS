import type { ActionKind, ProposedAction } from '../types';

export const KIND_LABELS: Record<ActionKind, string> = {
  merge_candidates: 'Merge duplicates',
  enhance_saved_skill: 'Enhance saved skill',
  duplicate_of_saved_skill: 'Duplicate of saved skill',
  keep_new: 'Keep as new skill',
  delete_saved_skill: 'Delete saved skill',
};

// Kinds that carry an editable merged body (title/when-to-use/procedure/etc.).
export const KINDS_WITH_BODY: ActionKind[] = [
  'merge_candidates',
  'enhance_saved_skill',
  'keep_new',
];

export function actionTitle(action: ProposedAction): string {
  if (action.merged_title) return action.merged_title;
  if (action.target_skill_slug) return action.target_skill_slug;
  return KIND_LABELS[action.kind] ?? action.kind;
}
