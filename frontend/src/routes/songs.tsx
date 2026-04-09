import { createFileRoute } from '@tanstack/react-router';
import { useQuery } from '@apollo/client/react';
import { useState, useMemo } from 'react';
import { GetSongsDocument } from '../types/generated/graphql';

// Layout & shared components
import { PageContainer } from '../components/layout/PageContainer';
import { PageHeader } from '../components/layout/PageHeader';
import { DataTable } from '../components/common/DataTable';
import { InlineSpinner } from '../components/ui/InlineSpinner';
import { PageSpinner } from '../components/ui/PageSpinner';
import { useRequestState } from '../hooks/useRequestState';
import { FilterBar } from '../components/common/FilterBar';

// Songs components
import { SongsTable } from '../components/songs/SongsTable';
import type { SortField } from '../components/songs/SongsTable';
import {
  FilterButtonGroup,
  type FilterOption,
} from '../components/ui/FilterButtonGroup';

const songFilterOptions: FilterOption<
  'all' | 'downloaded' | 'failed' | 'unavailable' | 'lowQuality'
>[] = [
  { value: 'all', label: 'All Songs', color: 'blue' },
  { value: 'downloaded', label: 'Downloaded', color: 'green' },
  { value: 'failed', label: 'Failed', color: 'yellow' },
  { value: 'unavailable', label: 'Unavailable', color: 'red' },
  { value: 'lowQuality', label: 'Low Quality (<220kbps)', color: 'orange' },
];

function Songs() {
  const { artistId: artistIdFromSearch, search: initialSearch } =
    Route.useSearch() as { artistId?: number; search?: string };
  // State management
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [sortField, setSortField] = useState<SortField>(null);
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc');
  const [searchQuery, setSearchQuery] = useState(initialSearch || '');
  const [filter, setFilter] = useState<
    'all' | 'downloaded' | 'failed' | 'unavailable' | 'lowQuality'
  >('all');

  // Memoize query variables to prevent unnecessary re-renders
  const queryVariables = useMemo(
    () => ({
      page,
      pageSize,
      artistId: artistIdFromSearch || undefined,
      sortBy: sortField,
      sortDirection: sortDirection,
      search: searchQuery || undefined,
    }),
    [page, pageSize, sortField, sortDirection, searchQuery, artistIdFromSearch]
  );

  const queryVariablesWithFilter = useMemo(
    () => ({
      ...queryVariables,
      downloaded:
        filter === 'all' || filter === 'lowQuality'
          ? undefined
          : filter === 'downloaded',
      unavailable: filter === 'unavailable' ? true : undefined,
      maxBitrate: filter === 'lowQuality' ? 220 : undefined,
    }),
    [queryVariables, filter]
  );

  const { data, loading, error, networkStatus } = useQuery(GetSongsDocument, {
    variables: queryVariablesWithFilter,
    fetchPolicy: 'cache-and-network',
    notifyOnNetworkStatusChange: true,
    pollInterval: 0,
    errorPolicy: 'all',
  });

  const handleFilterChange = (
    newFilter: 'all' | 'downloaded' | 'failed' | 'unavailable' | 'lowQuality'
  ) => {
    setFilter(newFilter);
    setPage(1);
  };

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('asc');
    }
    setPage(1);
  };

  const handleSearchChange = (query: string) => {
    setSearchQuery(query);
    setPage(1);
  };

  const handlePageSizeChange = (size: number) => {
    setPageSize(size);
    setPage(1);
  };

  // Apply frontend filtering for failed songs
  const songs = useMemo(() => {
    const allSongs = data?.songs?.items || [];
    if (filter === 'failed') {
      return allSongs.filter(song => (song?.failedCount ?? 0) > 0);
    }
    return allSongs;
  }, [data?.songs?.items, filter]);
  const totalCount = data?.songs?.pageInfo?.totalCount || 0;
  const totalPages = data?.songs?.pageInfo?.totalPages || 1;
  const { isRefreshing: isRefetching, isInitial: isInitialLoading } =
    useRequestState(networkStatus);

  // Show loading state on initial load
  if (isInitialLoading && !data) {
    return (
      <PageContainer>
        <PageHeader
          title='Songs'
          subtitle='Manage and track your downloaded songs'
        />
        <PageSpinner message='Loading songs...' />
      </PageContainer>
    );
  }

  return (
    <PageContainer>
      <PageHeader
        title='Songs'
        subtitle='Manage and track your downloaded songs'
      >
        {isRefetching && <InlineSpinner label='Updating...' />}
      </PageHeader>

      <FilterBar
        searchQuery={searchQuery}
        onSearchChange={handleSearchChange}
        pageSize={pageSize}
        onPageSizeChange={handlePageSizeChange}
        totalCount={totalCount}
        currentCount={songs.length}
        searchPlaceholder='Search songs...'
      />

      <FilterButtonGroup
        value={filter}
        options={songFilterOptions}
        onChange={handleFilterChange}
        className='mb-6'
      />

      <DataTable
        data={songs}
        loading={loading}
        error={error}
        totalCount={totalCount}
        pageSize={pageSize}
        page={page}
        totalPages={totalPages}
        onPageChange={setPage}
        emptyMessage='No songs found'
        loadingMessage='Loading songs...'
        errorMessage='Error loading songs'
      >
        <SongsTable
          songs={songs}
          sortField={sortField}
          sortDirection={sortDirection}
          onSort={handleSort}
          loading={loading}
        />
      </DataTable>
    </PageContainer>
  );
}

export const Route = createFileRoute('/songs')({
  component: Songs,
  validateSearch: (search: Record<string, unknown>) => ({
    artistId: search.artistId as number | undefined,
    search: (search.search as string | undefined) || undefined,
  }),
});
