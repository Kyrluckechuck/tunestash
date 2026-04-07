import { useState, useMemo, useCallback } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  GetPlaylistsDocument,
  TogglePlaylistDocument,
  TogglePlaylistAutoTrackDocument,
  TogglePlaylistM3uDocument,
  SyncPlaylistDocument,
  ForceSyncPlaylistDocument,
  RecheckPlaylistDocument,
  DownloadAllPlaylistsDocument,
  DeletePlaylistDocument,
  type Playlist,
  type GetPlaylistsQuery,
} from '../types/generated/graphql';
import { useToast } from '../components/ui/useToast';
import { useMutationState, useMutationLoadingState } from './useMutationState';
import { useRequestState } from './useRequestState';
import {
  usePrefetchFilters,
  generateFilterCombinations,
} from './usePrefetchFilters';
import { useQueryPrefetch } from './useQueryPrefetch';
import type { PlaylistSortField } from '../components/playlists/PlaylistsTable';
import type { SortDirection, PlaylistEnabledFilter } from '../types/shared';

export function usePlaylistsPage() {
  const toast = useToast();

  // State
  const [filter, setFilter] = useState<PlaylistEnabledFilter>('all');
  const [pageSize, setPageSize] = useState(50);
  const [sortField, setSortField] = useState<PlaylistSortField>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');
  const [searchQuery, setSearchQuery] = useState('');
  const [showPlaylistModal, setShowPlaylistModal] = useState(false);
  const [editingPlaylist, setEditingPlaylist] = useState<Playlist | null>(null);

  // Memoize query variables
  // Note: 'issues' filter is handled client-side, so we fetch all playlists
  const queryVariables = useMemo(
    () => ({
      enabled:
        filter === 'all' || filter === 'issues'
          ? undefined
          : filter === 'enabled',
      first: pageSize,
      sortBy: sortField,
      sortDirection: sortDirection,
      search: searchQuery || undefined,
    }),
    [filter, pageSize, sortField, sortDirection, searchQuery]
  );

  // Data fetching
  const { data, loading, error, fetchMore, networkStatus } = useQuery(
    GetPlaylistsDocument,
    {
      variables: queryVariables,
      fetchPolicy: 'cache-and-network',
      notifyOnNetworkStatusChange: true,
      pollInterval: 0,
      errorPolicy: 'all',
    }
  );

  // Mutations
  const [togglePlaylist] = useMutation(TogglePlaylistDocument);
  const [togglePlaylistAutoTrack] = useMutation(
    TogglePlaylistAutoTrackDocument
  );
  const [togglePlaylistM3u] = useMutation(TogglePlaylistM3uDocument);
  const [syncPlaylist] = useMutation(SyncPlaylistDocument);
  const [forceSyncPlaylist] = useMutation(ForceSyncPlaylistDocument);
  const [recheckPlaylist] = useMutation(RecheckPlaylistDocument);
  const [downloadAllPlaylists] = useMutation(DownloadAllPlaylistsDocument);
  const [deletePlaylist] = useMutation(DeletePlaylistDocument);

  // Mutation states
  const {
    mutatingIds: enabledMutatingIds,
    pulseIds: enabledPulseIds,
    handleMutation: handleEnabledMutation,
    errorById,
  } = useMutationState();

  const {
    mutatingIds: autoMutatingIds,
    pulseIds: autoPulseIds,
    handleMutation: handleAutoMutation,
  } = useMutationState();

  const {
    mutatingIds: m3uMutatingIds,
    pulseIds: m3uPulseIds,
    handleMutation: handleM3uMutation,
  } = useMutationState();

  const {
    loadingIds: syncMutatingIds,
    startLoading: startSync,
    stopLoading: stopSync,
  } = useMutationLoadingState();

  const {
    loadingIds: forceSyncMutatingIds,
    startLoading: startForceSync,
    stopLoading: stopForceSync,
  } = useMutationLoadingState();

  const {
    loadingIds: deleteMutatingIds,
    startLoading: startDelete,
    stopLoading: stopDelete,
  } = useMutationLoadingState();

  const {
    loadingIds: recheckMutatingIds,
    startLoading: startRecheck,
    stopLoading: stopRecheck,
  } = useMutationLoadingState();

  // Prefetching setup
  const createPrefetchHandler = useQueryPrefetch(
    GetPlaylistsDocument,
    queryVariables
  );

  const baseVariables = useMemo(
    () => ({
      first: pageSize,
      sortBy: sortField,
      sortDirection: sortDirection,
      search: searchQuery || undefined,
    }),
    [pageSize, sortField, sortDirection, searchQuery]
  );

  const filterCombinations = useMemo(
    () =>
      generateFilterCombinations({
        enabled: [true, false],
      }),
    []
  );

  usePrefetchFilters({
    query: GetPlaylistsDocument,
    baseVariables,
    filterCombinations,
    enabled: !!data,
    networkStatus,
  });

  // Handlers
  const handleEnabledFilterChange = createPrefetchHandler(
    setFilter,
    (newFilter: PlaylistEnabledFilter) => ({
      enabled:
        newFilter === 'all' || newFilter === 'issues'
          ? undefined
          : newFilter === 'enabled',
    })
  );

  const handlePageSizeChange = createPrefetchHandler(setPageSize, newSize => ({
    first: newSize,
  }));

  const handleSort = (field: PlaylistSortField) => {
    const newDirection: SortDirection =
      sortField === field && sortDirection === 'asc' ? 'desc' : 'asc';

    setSortField(field);
    setSortDirection(newDirection);

    createPrefetchHandler(null, () => ({
      sortBy: field,
      sortDirection: newDirection,
    }))(field);
  };

  const handleSearch = useCallback((query: string) => {
    setSearchQuery(query);
  }, []);

  // Prefetch-only handler for hover (no state update)
  const handleFilterHover = createPrefetchHandler(
    null,
    (hoverFilter: PlaylistEnabledFilter) => ({
      enabled:
        hoverFilter === 'all' || hoverFilter === 'issues'
          ? undefined
          : hoverFilter === 'enabled',
    })
  );

  const handleTogglePlaylist = async (playlist: Playlist) => {
    await handleEnabledMutation(
      playlist.id,
      async () => {
        await togglePlaylist({ variables: { playlistId: playlist.id } });
        toast.success(`Playlist ${playlist.enabled ? 'disabled' : 'enabled'}`);
      },
      { withPulse: true }
    );
  };

  const handleSyncPlaylist = async (playlistId: number) => {
    try {
      startSync(playlistId);
      await syncPlaylist({ variables: { playlistId } });
      toast.success('Playlist synced');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Sync failed');
    } finally {
      stopSync(playlistId);
    }
  };

  const handleForceSyncPlaylist = async (playlistId: number) => {
    try {
      startForceSync(playlistId);
      await forceSyncPlaylist({ variables: { playlistId } });
      toast.success('Playlist force sync started');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Force sync failed');
    } finally {
      stopForceSync(playlistId);
    }
  };

  const handleRecheckPlaylist = async (playlistId: number) => {
    try {
      startRecheck(playlistId);
      const result = await recheckPlaylist({
        variables: { playlistId },
        refetchQueries: [
          { query: GetPlaylistsDocument, variables: queryVariables },
        ],
      });
      if (result.data?.syncPlaylist?.success) {
        toast.success(
          'Playlist recheck started - status will update when complete'
        );
      } else {
        toast.error(result.data?.syncPlaylist?.message || 'Recheck failed');
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Recheck failed');
    } finally {
      stopRecheck(playlistId);
    }
  };

  const handleDeletePlaylist = async (
    playlistId: number,
    playlistName: string
  ) => {
    if (!window.confirm(`Are you sure you want to delete "${playlistName}"?`)) {
      return;
    }

    try {
      startDelete(playlistId);
      const result = await deletePlaylist({
        variables: { playlistId },
        refetchQueries: [
          { query: GetPlaylistsDocument, variables: queryVariables },
        ],
      });

      if (result.data?.deletePlaylist?.success) {
        toast.success(result.data.deletePlaylist.message || 'Playlist deleted');
      } else {
        toast.error(result.data?.deletePlaylist?.message || 'Delete failed');
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Delete failed');
    } finally {
      stopDelete(playlistId);
    }
  };

  const handleToggleAutoTrack = async (playlist: Playlist) => {
    await handleAutoMutation(
      playlist.id,
      async () => {
        await togglePlaylistAutoTrack({
          variables: { playlistId: playlist.id },
        });
        toast.success(
          `Track Artists ${playlist.autoTrackTier != null ? 'disabled' : 'enabled'}`
        );
      },
      { withPulse: true }
    );
  };

  const handleToggleM3u = async (playlist: Playlist) => {
    await handleM3uMutation(
      playlist.id,
      async () => {
        await togglePlaylistM3u({
          variables: { playlistId: playlist.id },
        });
        toast.success(
          `M3U export ${playlist.m3uEnabled ? 'disabled' : 'enabled'}`
        );
      },
      { withPulse: true }
    );
  };

  const handleEditPlaylist = useCallback((playlist: Playlist) => {
    setEditingPlaylist(playlist);
    setShowPlaylistModal(true);
  }, []);

  const handleClosePlaylistModal = useCallback(() => {
    setShowPlaylistModal(false);
    setEditingPlaylist(null);
  }, []);

  const handleCreatePlaylist = useCallback(() => {
    setShowPlaylistModal(true);
  }, []);

  const handleDownloadAllPlaylists = async () => {
    try {
      const result = await downloadAllPlaylists();

      if (result.data?.downloadAllPlaylists?.success) {
        toast.success(
          result.data.downloadAllPlaylists.message ||
            'Download started for all enabled playlists'
        );
      } else {
        const errorMessage =
          result.data?.downloadAllPlaylists?.message || 'Download failed';
        toast.error(errorMessage);
      }
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : 'Download failed';
      toast.error(errorMessage);
    }
  };

  const handleLoadMore = () => {
    if (data?.playlists?.pageInfo?.hasNextPage) {
      fetchMore({
        variables: {
          after: data.playlists.pageInfo.endCursor,
        },
        updateQuery: (
          prevResult: GetPlaylistsQuery,
          { fetchMoreResult }: { fetchMoreResult?: GetPlaylistsQuery }
        ) => {
          if (!fetchMoreResult) return prevResult;

          return {
            playlists: {
              ...fetchMoreResult.playlists,
              edges: [
                ...prevResult.playlists.edges,
                ...fetchMoreResult.playlists.edges,
              ],
            },
          };
        },
      });
    }
  };

  // Derived state
  const allPlaylists = useMemo(
    () => data?.playlists?.edges || [],
    [data?.playlists?.edges]
  );

  // Apply client-side filtering for 'issues' filter
  const playlists = useMemo(() => {
    if (filter === 'issues') {
      return allPlaylists.filter(
        p => p.status === 'spotify_api_restricted' || p.status === 'not_found'
      );
    }
    return allPlaylists;
  }, [allPlaylists, filter]);

  // Count for issues badge (always computed from all data)
  const issuesCount = useMemo(
    () =>
      allPlaylists.filter(
        p => p.status === 'spotify_api_restricted' || p.status === 'not_found'
      ).length,
    [allPlaylists]
  );

  const totalCount =
    filter === 'issues' ? playlists.length : data?.playlists?.totalCount || 0;
  const pageInfo = data?.playlists?.pageInfo;
  const { isRefreshing, isInitial: isInitialLoading } =
    useRequestState(networkStatus);

  return {
    // Data
    playlists,
    totalCount,
    pageInfo,
    loading,
    error,
    isRefreshing,
    isInitialLoading,
    issuesCount,

    // Filters & sorting
    filter,
    pageSize,
    sortField,
    sortDirection,
    searchQuery,

    // Modal state
    showPlaylistModal,
    editingPlaylist,

    // Mutation states
    enabledMutatingIds,
    enabledPulseIds,
    autoMutatingIds,
    autoPulseIds,
    m3uMutatingIds,
    m3uPulseIds,
    syncMutatingIds,
    forceSyncMutatingIds,
    deleteMutatingIds,
    recheckMutatingIds,
    errorById,

    // Handlers
    handleEnabledFilterChange,
    handlePageSizeChange,
    handleSort,
    handleSearch,
    handleFilterHover,
    handleTogglePlaylist,
    handleSyncPlaylist,
    handleForceSyncPlaylist,
    handleRecheckPlaylist,
    handleDeletePlaylist,
    handleToggleAutoTrack,
    handleToggleM3u,
    handleEditPlaylist,
    handleClosePlaylistModal,
    handleCreatePlaylist,
    handleDownloadAllPlaylists,
    handleLoadMore,
  };
}
