import { useState, useMemo, useCallback, useRef, useEffect } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  GetExternalListsDocument,
  CreateExternalListDocument,
  UpdateExternalListDocument,
  ToggleExternalListDocument,
  ToggleExternalListAutoTrackDocument,
  SyncExternalListDocument,
  SyncAllExternalListsDocument,
  DeleteExternalListDocument,
  type GetExternalListsQuery,
} from '../types/generated/graphql';
import { useToast } from '../components/ui/useToast';
import { useMutationLoadingState } from './useMutationState';
import { useRequestState } from './useRequestState';
import type { ExternalListSortField } from '../components/external-lists/ExternalListsTable';
import type { ExternalListSourceFilter } from '../components/external-lists/ExternalListFilters';
import type {
  CreateExternalListFormData,
  EditExternalListFields,
  EditingExternalList,
} from '../components/external-lists/ExternalListModal';
import type { SortDirection } from '../types/shared';

export function useExternalListsPage() {
  const toast = useToast();

  // State
  const [sourceFilter, setSourceFilter] =
    useState<ExternalListSourceFilter>('all');
  const [pageSize, setPageSize] = useState(50);
  const [sortField, setSortField] = useState<ExternalListSortField>(null);
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc');
  const [searchQuery, setSearchQuery] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingList, setEditingList] = useState<EditingExternalList | null>(
    null
  );

  // Memoize query variables
  const queryVariables = useMemo(
    () => ({
      source: sourceFilter === 'all' ? undefined : sourceFilter,
      first: pageSize,
      sortBy: sortField,
      sortDirection: sortDirection,
      search: searchQuery || undefined,
    }),
    [sourceFilter, pageSize, sortField, sortDirection, searchQuery]
  );

  // Smart polling: force polling briefly after sync mutations
  const [isPollingForced, setIsPollingForced] = useState(false);
  const forcePollTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined
  );

  const startPolling = useCallback(() => {
    setIsPollingForced(true);
    if (forcePollTimerRef.current) clearTimeout(forcePollTimerRef.current);
    forcePollTimerRef.current = setTimeout(
      () => setIsPollingForced(false),
      60_000
    );
  }, []);

  useEffect(
    () => () => {
      if (forcePollTimerRef.current) clearTimeout(forcePollTimerRef.current);
    },
    []
  );

  // Derived state (declared before useQuery so pollInterval can use it)
  // We'll compute hasPendingWork after data loads; for the initial render,
  // pollInterval starts at 0 and updates reactively.
  const dataRef = useRef<GetExternalListsQuery | undefined>(undefined);

  const hasPendingWork = useMemo(() => {
    const edges = dataRef.current?.externalLists?.edges;
    if (!edges) return false;
    return edges.some(list => {
      const pending = list.totalTracks - list.mappedTracks - list.failedTracks;
      if (pending > 0) return true;
      if (!list.lastSyncedAt && list.status === 'active') return true;
      return false;
    });
  }, [dataRef.current?.externalLists?.edges]); // eslint-disable-line react-hooks/exhaustive-deps

  const pollInterval = hasPendingWork || isPollingForced ? 5000 : 0;

  // Data fetching
  const { data, loading, error, fetchMore, networkStatus } = useQuery(
    GetExternalListsDocument,
    {
      variables: queryVariables,
      fetchPolicy: 'cache-and-network',
      notifyOnNetworkStatusChange: true,
      pollInterval,
      errorPolicy: 'all',
    }
  );

  // Keep dataRef in sync for hasPendingWork computation
  dataRef.current = data;

  // Mutations
  const [createExternalList] = useMutation(CreateExternalListDocument);
  const [updateExternalList] = useMutation(UpdateExternalListDocument);
  const [toggleExternalList] = useMutation(ToggleExternalListDocument);
  const [toggleAutoTrack] = useMutation(ToggleExternalListAutoTrackDocument);
  const [syncExternalList] = useMutation(SyncExternalListDocument);
  const [syncAllExternalLists] = useMutation(SyncAllExternalListsDocument);
  const [deleteExternalList] = useMutation(DeleteExternalListDocument);

  // Mutation states
  const {
    loadingIds: enabledMutatingIds,
    startLoading: startEnabled,
    stopLoading: stopEnabled,
  } = useMutationLoadingState();

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

  // Handlers
  const handleSourceFilterChange = useCallback(
    (filter: ExternalListSourceFilter) => {
      setSourceFilter(filter);
    },
    []
  );

  const handleSort = useCallback(
    (field: ExternalListSortField) => {
      const newDirection: SortDirection =
        sortField === field && sortDirection === 'asc' ? 'desc' : 'asc';
      setSortField(field);
      setSortDirection(newDirection);
    },
    [sortField, sortDirection]
  );

  const handleSearch = useCallback((query: string) => {
    setSearchQuery(query);
  }, []);

  const handlePageSizeChange = useCallback((size: number) => {
    setPageSize(size);
  }, []);

  const handleCreateList = async (
    formData: CreateExternalListFormData
  ): Promise<boolean> => {
    try {
      const result = await createExternalList({
        variables: {
          source: formData.source,
          listType: formData.listType,
          username: formData.username,
          period: formData.period,
          listIdentifier: formData.listIdentifier,
          autoTrackArtists: formData.autoTrackArtists,
        },
        refetchQueries: [
          { query: GetExternalListsDocument, variables: queryVariables },
        ],
      });

      if (result.data?.createExternalList) {
        toast.success('External list created');
        startPolling();
        return true;
      }
      return false;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create list');
      throw err;
    }
  };

  const handleEditList = async (
    listId: number,
    fields: EditExternalListFields
  ): Promise<boolean> => {
    try {
      const result = await updateExternalList({
        variables: {
          listId,
          name: fields.name,
          username: fields.username,
          period: fields.period,
          listIdentifier: fields.listIdentifier,
        },
        refetchQueries: [
          { query: GetExternalListsDocument, variables: queryVariables },
        ],
      });

      if (result.data?.updateExternalList?.success) {
        toast.success(result.data.updateExternalList.message || 'List updated');
        if (
          fields.username !== undefined ||
          fields.listIdentifier !== undefined
        ) {
          startPolling();
        }
        return true;
      }
      toast.error(result.data?.updateExternalList?.message || 'Update failed');
      return false;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update list');
      throw err;
    }
  };

  const handleToggleEnabled = async (list: { id: number; status: string }) => {
    try {
      startEnabled(list.id);
      const result = await toggleExternalList({
        variables: { listId: list.id },
        refetchQueries: [
          { query: GetExternalListsDocument, variables: queryVariables },
        ],
      });
      if (result.data?.toggleExternalList?.success) {
        toast.success(
          list.status === 'active' ? 'List disabled' : 'List enabled'
        );
      } else {
        toast.error(
          result.data?.toggleExternalList?.message || 'Toggle failed'
        );
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Toggle failed');
    } finally {
      stopEnabled(list.id);
    }
  };

  const handleToggleAutoTrack = async (list: {
    id: number;
    autoTrackArtists: boolean;
  }) => {
    try {
      startEnabled(list.id);
      const result = await toggleAutoTrack({
        variables: { listId: list.id },
        refetchQueries: [
          { query: GetExternalListsDocument, variables: queryVariables },
        ],
      });
      if (result.data?.toggleExternalListAutoTrack?.success) {
        toast.success(
          list.autoTrackArtists ? 'Auto-track disabled' : 'Auto-track enabled'
        );
      } else {
        toast.error(
          result.data?.toggleExternalListAutoTrack?.message || 'Toggle failed'
        );
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Toggle failed');
    } finally {
      stopEnabled(list.id);
    }
  };

  const handleSyncList = async (listId: number) => {
    try {
      startSync(listId);
      const result = await syncExternalList({
        variables: { listId },
      });
      if (result.data?.syncExternalList?.success) {
        toast.success('Sync started');
        startPolling();
      } else {
        toast.error(result.data?.syncExternalList?.message || 'Sync failed');
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Sync failed');
    } finally {
      stopSync(listId);
    }
  };

  const handleForceSyncList = async (listId: number) => {
    try {
      startForceSync(listId);
      const result = await syncExternalList({
        variables: { listId, force: true },
      });
      if (result.data?.syncExternalList?.success) {
        toast.success('Force sync started');
        startPolling();
      } else {
        toast.error(result.data?.syncExternalList?.message || 'Sync failed');
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Sync failed');
    } finally {
      stopForceSync(listId);
    }
  };

  const handleSyncAll = async () => {
    try {
      const result = await syncAllExternalLists();
      if (result.data?.syncAllExternalLists?.success) {
        toast.success(
          result.data.syncAllExternalLists.message ||
            'Sync started for all active lists'
        );
        startPolling();
      } else {
        toast.error(
          result.data?.syncAllExternalLists?.message || 'Sync all failed'
        );
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Sync all failed');
    }
  };

  const handleDeleteList = async (listId: number, listName: string) => {
    if (!window.confirm(`Are you sure you want to delete "${listName}"?`)) {
      return;
    }

    try {
      startDelete(listId);
      const result = await deleteExternalList({
        variables: { listId },
        refetchQueries: [
          { query: GetExternalListsDocument, variables: queryVariables },
        ],
      });
      if (result.data?.deleteExternalList?.success) {
        toast.success(result.data.deleteExternalList.message || 'List deleted');
      } else {
        toast.error(
          result.data?.deleteExternalList?.message || 'Delete failed'
        );
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Delete failed');
    } finally {
      stopDelete(listId);
    }
  };

  const handleOpenCreateModal = useCallback(() => {
    setShowCreateModal(true);
  }, []);

  const handleCloseCreateModal = useCallback(() => {
    setShowCreateModal(false);
    setEditingList(null);
  }, []);

  const handleOpenEditModal = useCallback((list: EditingExternalList) => {
    setEditingList(list);
    setShowCreateModal(true);
  }, []);

  const handleLoadMore = () => {
    if (data?.externalLists?.pageInfo?.hasNextPage) {
      fetchMore({
        variables: {
          after: data.externalLists.pageInfo.endCursor,
        },
        updateQuery: (
          prevResult: GetExternalListsQuery,
          { fetchMoreResult }: { fetchMoreResult?: GetExternalListsQuery }
        ) => {
          if (!fetchMoreResult) return prevResult;

          return {
            externalLists: {
              ...fetchMoreResult.externalLists,
              edges: [
                ...prevResult.externalLists.edges,
                ...fetchMoreResult.externalLists.edges,
              ],
            },
          };
        },
      });
    }
  };

  // Derived state
  const lists = useMemo(
    () => data?.externalLists?.edges || [],
    [data?.externalLists?.edges]
  );

  const totalCount = data?.externalLists?.totalCount || 0;
  const pageInfo = data?.externalLists?.pageInfo;
  const { isRefreshing, isInitial: isInitialLoading } =
    useRequestState(networkStatus);

  return {
    // Data
    lists,
    totalCount,
    pageInfo,
    loading,
    error,
    isRefreshing,
    isInitialLoading,

    // Filters & sorting
    sourceFilter,
    pageSize,
    sortField,
    sortDirection,

    // Modal state
    showCreateModal,
    editingList,

    // Mutation states
    enabledMutatingIds,
    syncMutatingIds,
    forceSyncMutatingIds,
    deleteMutatingIds,

    // Handlers
    handleSourceFilterChange,
    handlePageSizeChange,
    handleSort,
    handleSearch,
    handleCreateList,
    handleEditList,
    handleToggleEnabled,
    handleToggleAutoTrack,
    handleSyncList,
    handleForceSyncList,
    handleSyncAll,
    handleDeleteList,
    handleOpenCreateModal,
    handleOpenEditModal,
    handleCloseCreateModal,
    handleLoadMore,
  };
}
