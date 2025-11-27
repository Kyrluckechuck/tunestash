interface StatusBadgeProps {
  label: string;
  color: 'green' | 'red' | 'amber' | 'gray';
  icon?: React.ReactNode;
  tooltip?: string;
}

const WarningIcon = () => (
  <svg
    className='w-3 h-3'
    viewBox='0 0 20 20'
    fill='currentColor'
    aria-hidden='true'
  >
    <path
      fillRule='evenodd'
      d='M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z'
      clipRule='evenodd'
    />
  </svg>
);

const colorClasses: Record<string, string> = {
  green: 'bg-green-100 text-green-800',
  red: 'bg-red-100 text-red-800',
  amber: 'bg-amber-100 text-amber-800',
  gray: 'bg-gray-100 text-gray-600',
};

export function StatusBadge({
  label,
  color,
  icon = <WarningIcon />,
  tooltip,
}: StatusBadgeProps) {
  return (
    <span
      className={`hidden md:inline-flex px-2 py-1 text-xs font-semibold rounded-full w-28 justify-center cursor-help ${colorClasses[color]}`}
      title={tooltip}
      data-testid='status-badge'
    >
      <span className='inline-flex items-center gap-1'>
        {icon}
        <span>{label}</span>
      </span>
    </span>
  );
}
