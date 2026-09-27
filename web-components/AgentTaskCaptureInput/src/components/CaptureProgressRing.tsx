interface Props {
  size: number;
  progress: number; // 0 (empty) to 1 (full), matches `viewModel.progressPercentage`.
  color: string;
  strokeWidth?: number;
  gradientFrom?: string;
  gradientTo?: string;
}

export default function CaptureProgressRing({
  size,
  progress,
  color,
  strokeWidth = 2,
  gradientFrom,
  gradientTo,
}: Props) {
  const radius = size / 2 - strokeWidth;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.min(1, Math.max(0, progress));
  const dashOffset = circumference * (1 - clamped);
  const gradientId = 'capture-progress-ring-gradient';
  const stroke = gradientFrom && gradientTo ? `url(#${gradientId})` : color;
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      style={{ position: 'absolute', inset: 0, transform: 'rotate(-90deg)' }}
      aria-hidden="true"
    >
      {gradientFrom && gradientTo ? (
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={gradientFrom} />
            <stop offset="100%" stopColor={gradientTo} />
          </linearGradient>
        </defs>
      ) : null}
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={stroke}
        strokeWidth={strokeWidth}
        strokeDasharray={circumference}
        strokeDashoffset={dashOffset}
        strokeLinecap="round"
        opacity={0.85}
      />
    </svg>
  );
}
