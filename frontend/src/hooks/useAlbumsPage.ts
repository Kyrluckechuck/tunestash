import { useState, useMemo, useCallback } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  GetAlbumsDocument,
  SetAlbumWantedDocument,
  DownloadAlbumDocument,
  GetArtistDocument,
} from '../types/generated/graphql';
import { useToast } from '../components/ui/useToast';
import { useMutationState } from './useMutationState';
import { useRequestState } from './useRequestState';
import type { AlbumSortField } from '../components/albums/AlbumsTable';
import type {
  SortDirection,
  WantedFilter,
  DownloadFilter,
} from '../types/shared';

interface UseAlbumsPageOptions {
  artistId?: number;
}

export function useAlbumsPage(options: UseAlbumsPageOptions = {}) {
  const toast = useToast();
  const { artistId } = options;

  // State
  const [wantedFilter, setWantedFilter] = useState<WantedFilter>('all');
  const [downloadFilter, setDownloadFilter] = useState<DownloadFilter>('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [sortField, setSortField] = useState<AlbumSortField>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');
  const [searchQuery, setSearchQuery] = useState('');

  // Memoize query variables
  const queryVariables = useMemo(
    () => ({
      artistId: artistId || undefined,
      wanted: wantedFilter === 'all' ? undefined : wantedFilter === 'wanted',
      downloaded:
        downloadFilter === 'all' ? undefined : downloadFilter === 'downloaded',
      page,
      pageSize,
      sortBy: sortField,
      sortDirection: sortDirection,
      search: searchQuery || undefined,
    }),
    [
      artistId,
      wantedFilter,
      downloadFilter,
      page,
      pageSize,
      sortField,
      sortDirection,
      searchQuery,
    ]
  );

  // Data fetching
  const { data, loading, error, networkStatus } = useQuery(GetAlbumsDocument, {
    variables: queryVariables,
    fetchPolicy: 'cache-and-network',
    notifyOnNetworkStatusChange: true,
    pollInterval: 0,
    errorPolicy: 'all',
  });

  // Fetch artist details if filtering by artist
  const { data: artistData } = useQuery(GetArtistDocument, {
    variables: { id: artistId?.toString() ?? '0' },
    skip: !artistId,
    fetchPolicy: 'cache-first',
    nextFetchPolicy: 'cache-first',
    notifyOnNetworkStatusChange: false,
    pollInterval: 0,
  });

  // Mutations
  const [setAlbumWanted] = useMutation(SetAlbumWantedDocument);
  const [downloadAlbum] = useMutation(DownloadAlbumDocument);
  const { mutatingIds, pulseIds, handleMutation } = useMutationState();

  // Handlers
  const handleWantedFilterChange = useCallback((newFilter: WantedFilter) => {
    setWantedFilter(newFilter);
    setPage(1);
  }, []);

  const handleDownloadFilterChange = useCallback(
    (newFilter: DownloadFilter) => {
      setDownloadFilter(newFilter);
      setPage(1);
    },
    []
  );

  const handlePageSizeChange = useCallback((newSize: number) => {
    setPageSize(newSize);
    setPage(1);
  }, []);

  const handleSort = useCallback(
    (field: AlbumSortField) => {
      const newDirection: SortDirection =
        sortField === field && sortDirection === 'asc' ? 'desc' : 'asc';
      setSortField(field);
      setSortDirection(newDirection);
      setPage(1);
    },
    [sortField, sortDirection]
  );

  const handleSearch = useCallback((query: string) => {
    setSearchQuery(query);
    setPage(1);
  }, []);

  const handleWantedToggle = async (albumId: number, wanted: boolean) => {
    await handleMutation(
      albumId,
      async () => {
        await setAlbumWanted({
          variables: {
            albumId,
            wanted,
          },
        });
        toast.success(`Wanted ${wanted ? 'enabled' : 'disabled'}`);
      },
      { withPulse: true }
    );
  };

  const handleDownloadAlbum = async (albumId: number) => {
    await handleMutation(
      albumId,
      async () => {
        await downloadAlbum({
          variables: {
            albumId: albumId.toString(),
          },
        });
        toast.success('Album download queued');
      },
      { withPulse: false }
    );
  };

  // Derived state
  const albums = data?.albums?.items || [];
  const totalCount = data?.albums?.pageInfo?.totalCount || 0;
  const totalPages = data?.albums?.pageInfo?.totalPages || 1;
  const { isRefreshing, isInitial: isInitialLoading } =
    useRequestState(networkStatus);

  const artist = artistData?.artist;

  return {
    // Data
    albums,
    totalCount,
    totalPages,
    loading,
    error,
    isRefreshing,
    isInitialLoading,
    artist,

    // Pagination
    page,
    setPage,

    // Filters & sorting
    wantedFilter,
    downloadFilter,
    pageSize,
    sortField,
    sortDirection,
    searchQuery,

    // Mutation states
    mutatingIds,
    pulseIds,

    // Handlers
    handleWantedFilterChange,
    handleDownloadFilterChange,
    handlePageSizeChange,
    handleSort,
    handleSearch,
    handleWantedToggle,
    handleDownloadAlbum,
  };
}
