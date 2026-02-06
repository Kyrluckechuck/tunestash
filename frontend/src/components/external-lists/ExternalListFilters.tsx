import { FilterButtonGroup, type FilterOption } from '../ui/FilterButtonGroup';

export type ExternalListSourceFilter =
  | 'all'
  | 'lastfm'
  | 'listenbrainz'
  | 'youtube_music';

interface ExternalListFiltersProps {
  currentSourceFilter: ExternalListSourceFilter;
  onSourceFilterChange: (filter: ExternalListSourceFilter) => void;
}

export function ExternalListFilters({
  currentSourceFilter,
  onSourceFilterChange,
}: ExternalListFiltersProps) {
  const filterOptions: FilterOption<ExternalListSourceFilter>[] = [
    { value: 'all', label: 'All Sources', color: 'indigo' },
    { value: 'lastfm', label: 'Last.fm', color: 'red' },
    { value: 'listenbrainz', label: 'ListenBrainz', color: 'orange' },
    { value: 'youtube_music', label: 'YouTube Music', color: 'amber' },
  ];

  return (
    <div className='flex items-center gap-4 mb-6'>
      <FilterButtonGroup
        value={currentSourceFilter}
        options={filterOptions}
        onChange={onSourceFilterChange}
        label='Source'
      />
    </div>
  );
}
