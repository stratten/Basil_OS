import { useRef } from 'react';

function readonlySetsHaveSameMembers(left: ReadonlySet<string>, right: ReadonlySet<string>): boolean {
  if (left.size !== right.size) return false;
  for (const value of left) {
    if (!right.has(value)) return false;
  }
  return true;
}

export function useStableReadonlySet(next: ReadonlySet<string>): ReadonlySet<string> {
  const previousRef = useRef<ReadonlySet<string>>(next);
  if (!readonlySetsHaveSameMembers(previousRef.current, next)) {
    previousRef.current = next;
  }
  return previousRef.current;
}
