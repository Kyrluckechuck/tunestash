interface PaginationBarProps {
  page: number;
  totalPages: number;
  totalCount: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  loading?: boolean;
}

function getPageWindow(
  current: number,
  total: number
): (number | 'ellipsis')[] {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }

  const pages: (number | 'ellipsis')[] = [];
  const windowSize = 2;

  pages.push(1);

  const windowStart = Math.max(2, current - windowSize);
  const windowEnd = Math.min(total - 1, current + windowSize);

  if (windowStart > 2) {
    pages.push('ellipsis');
  }

  for (let i = windowStart; i <= windowEnd; i++) {
    pages.push(i);
  }

  if (windowEnd < total - 1) {
    pages.push('ellipsis');
  }

  if (total > 1) {
    pages.push(total);
  }

  return pages;
}

export function PaginationBar({
  page,
  totalPages,
  totalCount,
  pageSize,
  onPageChange,
  loading = false,
}: PaginationBarProps) {
  if (totalPages === 0) return null;

  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, totalCount);
  const pages = getPageWindow(page, totalPages);

  const isFirstPage = page <= 1;
  const isLastPage = page >= totalPages;

  return (
    <div className='sticky bottom-0 bg-white dark:bg-slate-800 border-t-2 border-indigo-500 dark:border-indigo-400 px-4 py-3 flex items-center justify-between z-10'>
      <span className='text-sm text-gray-500 dark:text-slate-400'>
        Showing {start}–{end} of {totalCount.toLocaleString()}
      </span>
      <div className='flex items-center gap-1'>
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={isFirstPage || loading}
          aria-label='Previous page'
          className='px-2 py-1 text-sm rounded hover:bg-gray-100 dark:hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed text-gray-600 dark:text-slate-300'
        >
          ← Prev
        </button>
        {pages.map((p, i) =>
          p === 'ellipsis' ? (
            <span
              key={i < pages.length / 2 ? 'ellipsis-left' : 'ellipsis-right'}
              className='px-1 text-sm text-gray-400 dark:text-slate-500'
            >
              ...
            </span>
          ) : (
            <button
              key={p}
              onClick={() => onPageChange(p)}
              disabled={loading}
              className={`px-2.5 py-1 text-sm rounded transition-colors ${
                p === page
                  ? 'bg-indigo-600 text-white font-medium'
                  : 'text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-700'
              } disabled:cursor-not-allowed`}
            >
              {p}
            </button>
          )
        )}
        <button
          onClick={() => onPageChange(page + 1)}
          disabled={isLastPage || loading}
          aria-label='Next page'
          className='px-2 py-1 text-sm rounded hover:bg-gray-100 dark:hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed text-gray-600 dark:text-slate-300'
        >
          Next →
        </button>
      </div>
    </div>
  );
}
