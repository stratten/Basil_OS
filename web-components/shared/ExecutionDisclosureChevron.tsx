export default function ExecutionDisclosureChevron({
  expanded,
  color = 'var(--text-tertiary)',
}: {
  expanded: boolean;
  color?: string;
}) {
  return (
    <svg
      width="10"
      height="10"
      viewBox="0 0 16 16"
      fill="none"
      stroke={color}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{
        transition: 'transform 0.2s',
        transform: expanded ? 'rotate(0deg)' : 'rotate(-90deg)',
      }}
    >
      <path d="M4 6l4 4 4-4" />
    </svg>
  );
}
