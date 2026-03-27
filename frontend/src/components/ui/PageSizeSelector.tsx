interface PageSizeSelectorProps {
  pageSize: number;
  onPageSizeChange: (size: number) => void;
  options?: number[];
}

export function PageSizeSelector({
  pageSize,
  onPageSizeChange,
  options = [20, 50, 100, 200],
}: PageSizeSelectorProps) {
  return (
    <div className='flex items-center gap-2'>
      <label
        htmlFor='pageSize'
        className='text-sm text-gray-600 dark:text-slate-400'
      >
        Show:
      </label>
      <select
        id='pageSize'
        value={pageSize}
        onChange={e => onPageSizeChange(Number(e.target.value))}
        className='border border-gray-300 dark:border-slate-600 rounded px-2 py-1 text-sm dark:bg-slate-800 dark:text-slate-100'
      >
        {options.map(size => (
          <option key={size} value={size}>
            {size}
          </option>
        ))}
      </select>
    </div>
  );
}
