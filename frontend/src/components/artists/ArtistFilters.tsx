import { FilterButtonGroup, type FilterOption } from '../ui/FilterButtonGroup';

export type TrackingFilter = 'all' | 'favourite' | 'tracked' | 'untracked';

interface ArtistFiltersProps {
  currentFilter: TrackingFilter;
  onFilterChange: (filter: TrackingFilter) => void;
  onFilterHover?: (filter: TrackingFilter) => void;
  hasUndownloadedFilter?: boolean;
  onHasUndownloadedChange?: (value: boolean | undefined) => void;
}

const filterOptions: FilterOption<TrackingFilter>[] = [
  { value: 'all', label: 'Show All', color: 'indigo' },
  { value: 'favourite', label: 'Favourites', color: 'amber' },
  { value: 'tracked', label: 'Tracked', color: 'green' },
  { value: 'untracked', label: 'Untracked', color: 'orange' },
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
              : 'bg-gray-100 dark:bg-slate-700 text-gray-600 dark:text-slate-400 hover:bg-gray-200 dark:hover:bg-slate-500'
          }`}
        >
          Has Undownloaded
        </button>
      )}
    </div>
  );
}
