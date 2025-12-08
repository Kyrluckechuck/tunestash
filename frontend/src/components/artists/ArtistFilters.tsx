import { FilterButtonGroup, type FilterOption } from '../ui/FilterButtonGroup';

interface ArtistFiltersProps {
  currentFilter: 'all' | 'tracked' | 'untracked';
  onFilterChange: (filter: 'all' | 'tracked' | 'untracked') => void;
  onFilterHover?: (filter: 'all' | 'tracked' | 'untracked') => void;
  hasUndownloadedFilter?: boolean;
  onHasUndownloadedChange?: (value: boolean | undefined) => void;
}

const filterOptions: FilterOption<'all' | 'tracked' | 'untracked'>[] = [
  { value: 'all', label: 'Show All', color: 'indigo' },
  { value: 'tracked', label: 'Tracked Only', color: 'green' },
  { value: 'untracked', label: 'Untracked Only', color: 'orange' },
];

export function ArtistFilters({
  currentFilter,
  onFilterChange,
  onFilterHover,
  hasUndownloadedFilter,
  onHasUndownloadedChange,
}: ArtistFiltersProps) {
  return (
    <div className='flex flex-wrap items-center gap-4 mb-6'>
      <FilterButtonGroup
        value={currentFilter}
        options={filterOptions}
        onChange={onFilterChange}
        onHover={onFilterHover}
      />
      {onHasUndownloadedChange && (
        <button
          onClick={() =>
            onHasUndownloadedChange(
              hasUndownloadedFilter === true ? undefined : true
            )
          }
          className={`px-3 py-1.5 text-sm font-medium rounded-lg transition-colors ${
            hasUndownloadedFilter === true
              ? 'bg-amber-100 text-amber-800 hover:bg-amber-200'
              : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
        >
          Has Undownloaded
        </button>
      )}
    </div>
  );
}
