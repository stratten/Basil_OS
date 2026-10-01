import { NativeSymbol } from './NativeSymbol';

export function RefineBadge({ kind }: { kind: 'mic' | 'pencil' }) {
  return (
    <span className="assistant-session-actions__refine">
      <NativeSymbol name="refine" size={15} />
      <span className="assistant-session-actions__refine-badge" aria-hidden="true">
        <NativeSymbol name={kind === 'mic' ? 'micFill' : 'pencil'} size={8} />
      </span>
    </span>
  );
}
