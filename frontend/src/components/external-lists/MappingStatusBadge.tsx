interface MappingStatusBadgeProps {
  totalTracks: number;
  mappedTracks: number;
  failedTracks: number;
}

export function MappingStatusBadge({
  totalTracks,
  mappedTracks,
  failedTracks,
}: MappingStatusBadgeProps) {
  if (totalTracks === 0) {
    return (
      <span className='text-sm text-gray-400 dark:text-slate-500'>
        No tracks
      </span>
    );
  }

  const pendingTracks = totalTracks - mappedTracks - failedTracks;
  const progressPercent = Math.round((mappedTracks / totalTracks) * 100);

  return (
    <div className='flex items-center gap-2'>
      <div className='w-24 bg-gray-200 dark:bg-slate-600 rounded-full h-2'>
        <div
          className='h-2 rounded-full bg-green-500'
          style={{ width: `${progressPercent}%` }}
        />
      </div>
      <span className='text-sm text-gray-600 dark:text-slate-400 whitespace-nowrap'>
        {mappedTracks}/{totalTracks}
        {failedTracks > 0 && (
          <span className='text-red-500 ml-1'>({failedTracks} failed)</span>
        )}
        {pendingTracks > 0 && (
          <span className='text-yellow-500 ml-1'>
            ({pendingTracks} pending)
          </span>
        )}
      </span>
    </div>
  );
}
