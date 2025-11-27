import { FilterButtonGroup, type FilterOption } from '../ui/FilterButtonGroup';

export type PlaylistFilterValue = 'all' | 'enabled' | 'disabled' | 'issues';

interface PlaylistFiltersProps {
  currentEnabledFilter: PlaylistFilterValue;
  onEnabledFilterChange: (filter: PlaylistFilterValue) => void;
  onFilterHover?: (filter: PlaylistFilterValue) => void;
  issuesCount?: number;
}

export function PlaylistFilters({
  currentEnabledFilter,
  onEnabledFilterChange,
  onFilterHover,
  issuesCount = 0,
}: PlaylistFiltersProps) {
  const filterOptions: FilterOption<PlaylistFilterValue>[] = [
    { value: 'all', label: 'All Playlists', color: 'indigo' },
    { value: 'enabled', label: 'Enabled', color: 'green' },
    { value: 'disabled', label: 'Disabled', color: 'gray' },
    {
      value: 'issues',
      label: `Issues${issuesCount > 0 ? ` (${issuesCount})` : ''}`,
      color: 'amber',
    },
  ];

  return (
    <div className='flex items-center gap-4 mb-6'>
      <FilterButtonGroup
        value={currentEnabledFilter}
        options={filterOptions}
        onChange={onEnabledFilterChange}
        onHover={onFilterHover}
        label='Status'
      />
    </div>
  );
}
