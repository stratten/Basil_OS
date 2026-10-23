import type { DiffLine } from './diffLines';

export interface DiffViewProps {
  diff: DiffLine[];
  label: string;
}

/**
 * Renders a line-level diff produced by `diffLines`/`diffLineArrays`.
 * Extracted verbatim from ArtifactReviewWorkspace's inline diff markup so
 * FilePreviewApp and LocalWebPreviewApp can show the same diff rendering
 * for a selected historical version without duplicating the JSX.
 */
export function DiffView({ diff, label }: DiffViewProps) {
  return (
    <pre className="artifact-review-diff" aria-label={label}>
      {diff.map((line, index) => (
        <div
          key={index}
          className={`artifact-review-diff-line artifact-review-diff-line--${line.type}`}
        >
          <span className="artifact-review-diff-marker" aria-hidden="true">
            {line.type === 'added' ? '+' : line.type === 'removed' ? '-' : ' '}
          </span>
          <span className="artifact-review-diff-content">{line.content}</span>
        </div>
      ))}
    </pre>
  );
}
