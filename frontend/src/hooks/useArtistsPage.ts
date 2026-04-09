import { useState, useMemo } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  GetArtistsDocument,
  GetTaskHistoryDocument,
  UpdateArtistDocument,
  SyncArtistDocument,
  DownloadArtistDocument,
  RetryFailedSongsDocument,
  SyncAllTrackedArtistsDocument,
  DownloadAllTrackedArtistsDocument,
} from '../types/generated/graphql';
import { useToast } from '../components/ui/useToast';
import { useDataTable } from './useDataTable';
import { useMutationState, useMutationLoadingState } from './useMutationState';
import { useRequestState } from './useRequestState';
import type { SortField } from '../components/artists/ArtistsTable';
import type { TrackingFilter } from '../components/artists/ArtistFilters';

export function useArtistsPage() {
  const toast = useToast();

  // Table state management
  const {
    page,
    pageSize,
    sortField,
    sortDirection,
    searchQuery,
    setPage,
    setPageSize,
    setSearchQuery,
    queryVariables,
    handleSort,
  } = useDataTable<SortField>({
    initialPageSize: 50,
    initialSortField: null,
    initialSortDirection: 'asc',
    initialSearchQuery: '',
  });

  const [filter, setFilter] = useState<TrackingFilter>('tracked');
  const [hasUndownloadedFilter, setHasUndownloadedFilter] = useState<
    boolean | undefined
  >(undefined);

  // Memoize query variables with filter
  const queryVariablesWithFilter = useMemo(
    () => ({
      ...queryVariables,
      trackingTier:
        filter === 'favourite'
          ? 2
          : filter === 'tracked'
            ? 1
            : filter === 'untracked'
              ? 0
              : undefined,
      hasUndownloaded: hasUndownloadedFilter,
    }),
    [queryVariables, filter, hasUndownloadedFilter]
  );

  // Query for running artist tasks to enable smart polling
  const { data: taskData } = useQuery(GetTaskHistoryDocument, {
    variables: {
      status: 'RUNNING',
      pageSize: 100,
    },
    fetchPolicy: 'cache-first',
    pollInterval: 5000,
  });

  // Compute whether there are active artist-related tasks
  const hasActiveArtistTasks = useMemo(() => {
    const items = taskData?.taskHistory?.items || [];
    return items.some(task => {
      return (
        task.status === 'RUNNING' &&
        task.entityType === 'ARTIST' &&
        (task.type === 'SYNC' || task.type === 'DOWNLOAD')
      );
    });
  }, [taskData]);

  // Dynamic poll interval: 5s when tasks active, 0 (disabled) when idle
  const artistsPollInterval = hasActiveArtistTasks ? 5000 : 0;

  // Data fetching
  const { data, loading, error, networkStatus } = useQuery(GetArtistsDocument, {
    variables: queryVariablesWithFilter,
    fetchPolicy: 'cache-and-network',
    notifyOnNetworkStatusChange: true,
    pollInterval: artistsPollInterval,
    errorPolicy: 'all',
  });

  // Mutations
  const [updateArtist] = useMutation(UpdateArtistDocument);
  const [syncArtist] = useMutation(SyncArtistDocument);
  const [downloadArtist] = useMutation(DownloadArtistDocument);
  const [retryFailedSongs] = useMutation(RetryFailedSongsDocument);
  const [syncAllTrackedArtists] = useMutation(SyncAllTrackedArtistsDocument);
  const [downloadAllTrackedArtists] = useMutation(
    DownloadAllTrackedArtistsDocument
  );

  // Mutation state management
  const { mutatingIds, pulseIds, errorById, handleMutation } =
    useMutationState();

  const {
    loadingIds: syncMutatingIds,
    startLoading: startSync,
    stopLoading: stopSync,
  } = useMutationLoadingState();

  const {
    loadingIds: downloadMutatingIds,
    startLoading: startDownload,
    stopLoading: stopDownload,
  } = useMutationLoadingState();

  const {
    loadingIds: retryMutatingIds,
    startLoading: startRetry,
    stopLoading: stopRetry,
  } = useMutationLoadingState();

  // Handlers
  const handleFilterChange = (newFilter: TrackingFilter) => {
    setFilter(newFilter);
    setPage(1);
  };

  const tierLabels = ['Untracked', 'Tracked', 'Favourite'] as const;

  const handleTierChange = async (
    artist: { id: number; trackingTier: number },
    newTier: number
  ) => {
    if (newTier === artist.trackingTier) return;
    await handleMutation(
      artist.id,
      async () => {
        await updateArtist({
          variables: {
            input: {
              artistId: artist.id.toString(),
              trackingTier: newTier,
            },
          },
        });
        toast.success(`Artist set to ${tierLabels[newTier]}`);
      },
      { withPulse: true }
    );
  };

  const handleSyncArtist = async (artistId: number) => {
    try {
      startSync(artistId);
      await syncArtist({ variables: { artistId: artistId.toString() } });
      toast.success('Artist sync started');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Sync failed');
    } finally {
      stopSync(artistId);
    }
  };

  const handleDownloadArtist = async (artistId: number) => {
    try {
      startDownload(artistId);
      const result = await downloadArtist({
        variables: { artistId: artistId.toString() },
      });

      if (result.data?.downloadArtist?.success) {
        toast.success('Artist download started');
      } else {
        const errorMessage =
          result.data?.downloadArtist?.message || 'Download failed';
        toast.error(errorMessage);
      }
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : 'Download failed';
      toast.error(errorMessage);
    } finally {
      stopDownload(artistId);
    }
  };

  const handleRetryFailedSongs = async (artistId: number) => {
    try {
      startRetry(artistId);
      const result = await retryFailedSongs({
        variables: { artistId: artistId.toString() },
      });

      if (result.data?.retryFailedSongs?.success) {
        toast.success(
          result.data.retryFailedSongs.message ||
            'Retry started for failed songs'
        );
      } else {
        const errorMessage =
          result.data?.retryFailedSongs?.message || 'Retry failed';
        toast.error(errorMessage);
      }
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : 'Retry failed';
      toast.error(errorMessage);
    } finally {
      stopRetry(artistId);
    }
  };

  const handleSyncAllTrackedArtists = async () => {
    try {
      const result = await syncAllTrackedArtists();

      if (result.data?.syncAllTrackedArtists?.success) {
        toast.success(
          result.data.syncAllTrackedArtists.message ||
            'Sync started for all tracked artists'
        );
      } else {
        const errorMessage =
          result.data?.syncAllTrackedArtists?.message || 'Sync failed';
        toast.error(errorMessage);
      }
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : 'Sync failed';
      toast.error(errorMessage);
    }
  };

  const handleDownloadAllTrackedArtists = async () => {
    try {
      const result = await downloadAllTrackedArtists();

      if (result.data?.downloadAllTrackedArtists?.success) {
        toast.success(
          result.data.downloadAllTrackedArtists.message ||
            'Download started for all tracked artists'
        );
      } else {
        const errorMessage =
          result.data?.downloadAllTrackedArtists?.message || 'Download failed';
        toast.error(errorMessage);
      }
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : 'Download failed';
      toast.error(errorMessage);
    }
  };

  // Derived state
  const artists = data?.artists?.items || [];
  const totalCount = data?.artists?.pageInfo?.totalCount || 0;
  const totalPages = data?.artists?.pageInfo?.totalPages || 1;
  const { isRefreshing, isInitial: isInitialLoading } =
    useRequestState(networkStatus);

  return {
    // Data
    artists,
    totalCount,
    totalPages,
    loading,
    error,
    isRefreshing,
    isInitialLoading,

    // Pagination
    page,
    setPage,

    // Filters & sorting
    filter,
    hasUndownloadedFilter,
    searchQuery,
    pageSize,
    sortField,
    sortDirection,

    // Mutation states
    mutatingIds,
    pulseIds,
    errorById,
    syncMutatingIds,
    downloadMutatingIds,
    retryMutatingIds,

    // Handlers
    handleFilterChange,
    setHasUndownloadedFilter,
    setSearchQuery,
    setPageSize,
    handleSort,
    handleTierChange,
    handleSyncArtist,
    handleDownloadArtist,
    handleRetryFailedSongs,
    handleSyncAllTrackedArtists,
    handleDownloadAllTrackedArtists,
  };
}
