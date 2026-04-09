import { useState, useRef, useEffect } from 'react';

interface ColumnDefinition {
  key: string;
  label: string;
}

interface ColumnToggleProps {
  columns: ColumnDefinition[];
  visibleColumns: string[];
  onToggle: (key: string) => void;
}

export function ColumnToggle({
  columns,
  visibleColumns,
  onToggle,
}: ColumnToggleProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function handleEscape(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('keydown', handleEscape);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [open]);

  return (
    <div ref={ref} className='relative'>
      <button
        onClick={() => setOpen(prev => !prev)}
        className='px-3 py-1.5 text-xs font-medium text-gray-600 dark:text-slate-300 border border-gray-300 dark:border-slate-600 rounded hover:bg-gray-50 dark:hover:bg-slate-700 transition-colors'
        aria-label='Toggle columns'
      >
        Columns
      </button>
      {open && (
        <div className='absolute right-0 top-full mt-1 bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-600 rounded-lg shadow-lg py-2 px-3 min-w-[180px] z-20'>
          <div className='text-xs font-semibold text-gray-500 dark:text-slate-400 mb-2'>
            Show Columns
          </div>
          {columns.map(col => (
            <label
              key={col.key}
              className='flex items-center gap-2 py-1 text-sm text-gray-700 dark:text-slate-300 cursor-pointer hover:text-gray-900 dark:hover:text-white'
            >
              <input
                type='checkbox'
                checked={visibleColumns.includes(col.key)}
                onChange={() => onToggle(col.key)}
                className='rounded border-gray-300 dark:border-slate-600 text-indigo-600 focus:ring-indigo-500'
              />
              {col.label}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
