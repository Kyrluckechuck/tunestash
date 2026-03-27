import { useMutation, useQuery } from '@apollo/client/react';
import { useCallback, useState } from 'react';
import {
  GetPendingMetadataUpdatesDocument,
  ApplyMetadataUpdateDocument,
  DismissMetadataUpdateDocument,
  ApplyAllMetadataUpdatesDocument,
  type MetadataUpdateStatus,
  type MetadataEntityType,
} from '../../types/generated/graphql';
import { useToast } from '../ui/useToast';
import { useConfirm } from '../../hooks/useConfirm';
import { FilterButtonGroup } from '../ui/FilterButtonGroup';

type StatusFilter = 'pending' | 'applied' | 'dismissed' | 'all';

const STATUS_FILTER_OPTIONS = [
  {
    value: 'pending' as StatusFilter,
    label: 'Pending',
    color: 'orange' as const,
  },
  {
    value: 'applied' as StatusFilter,
    label: 'Applied',
    color: 'green' as const,
  },
  {
    value: 'dismissed' as StatusFilter,
    label: 'Dismissed',
    color: 'gray' as const,
  },
  { value: 'all' as StatusFilter, label: 'All', color: 'indigo' as const },
];

function formatRelativeTime(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString();
}

function getEntityTypeIcon(entityType: MetadataEntityType): string {
  switch (entityType) {
    case 'ARTIST':
      return '🎤';
    case 'ALBUM':
      return '💿';
    case 'SONG':
      return '🎵';
    default:
      return '📝';
  }
}

function getEntityTypeLabel(entityType: MetadataEntityType): string {
  switch (entityType) {
    case 'ARTIST':
      return 'Artist';
    case 'ALBUM':
      return 'Album';
    case 'SONG':
      return 'Song';
    default:
      return 'Unknown';
  }
}

function getStatusBadge(status: MetadataUpdateStatus): {
  className: string;
  label: string;
} {
  switch (status) {
    case 'PENDING':
      return {
        className: 'bg-orange-100 text-orange-700',
        label: 'Pending',
      };
    case 'APPLIED':
      return {
        className:
          'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400',
        label: 'Applied',
      };
    case 'DISMISSED':
      return {
        className:
          'bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-slate-300',
        label: 'Dismissed',
      };
    default:
      return {
        className:
          'bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-slate-300',
        label: 'Unknown',
      };
  }
}

export function MetadataChangesSection() {
  const toast = useToast();
  const { confirm, ConfirmDialog } = useConfirm();
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('pending');
  const [actionInProgress, setActionInProgress] = useState<number | null>(null);

  const graphqlStatus: MetadataUpdateStatus | undefined =
    statusFilter === 'all'
      ? undefined
      : statusFilter === 'pending'
        ? 'PENDING'
        : statusFilter === 'applied'
          ? 'APPLIED'
          : 'DISMISSED';

  const { data, loading, refetch } = useQuery(
    GetPendingMetadataUpdatesDocument,
    {
      variables: {
        status: graphqlStatus,
        includeResolved: statusFilter !== 'pending',
      },
      pollInterval: 30000,
    }
  );

  const [applyUpdate] = useMutation(ApplyMetadataUpdateDocument, {
    refetchQueries: [{ query: GetPendingMetadataUpdatesDocument }],
  });

  const [dismissUpdate] = useMutation(DismissMetadataUpdateDocument, {
    refetchQueries: [{ query: GetPendingMetadataUpdatesDocument }],
  });

  const [applyAllUpdates, { loading: isApplyingAll }] = useMutation(
    ApplyAllMetadataUpdatesDocument,
    {
      refetchQueries: [{ query: GetPendingMetadataUpdatesDocument }],
    }
  );

  const updates = data?.pendingMetadataUpdates?.edges || [];
  const summary = data?.pendingMetadataUpdates?.summary;

  const handleApply = useCallback(
    async (updateId: number, entityName: string) => {
      setActionInProgress(updateId);
      try {
        const result = await applyUpdate({ variables: { updateId } });
        if (result.data?.applyMetadataUpdate?.success) {
          toast.success(`Applied update for "${entityName}"`);
          refetch();
        } else {
          toast.error(
            result.data?.applyMetadataUpdate?.message ||
              'Failed to apply update'
          );
        }
      } catch (error) {
        toast.error(
          `Error applying update: ${error instanceof Error ? error.message : String(error)}`
        );
      } finally {
        setActionInProgress(null);
      }
    },
    [applyUpdate, toast, refetch]
  );

  const handleDismiss = useCallback(
    async (updateId: number, entityName: string) => {
      setActionInProgress(updateId);
      try {
        const result = await dismissUpdate({ variables: { updateId } });
        if (result.data?.dismissMetadataUpdate?.success) {
          toast.success(`Dismissed update for "${entityName}"`);
          refetch();
        } else {
          toast.error(
            result.data?.dismissMetadataUpdate?.message ||
              'Failed to dismiss update'
          );
        }
      } catch (error) {
        toast.error(
          `Error dismissing update: ${error instanceof Error ? error.message : String(error)}`
        );
      } finally {
        setActionInProgress(null);
      }
    },
    [dismissUpdate, toast, refetch]
  );

  const handleApplyAll = useCallback(async () => {
    const pendingCount =
      (summary?.artistUpdates || 0) +
      (summary?.albumUpdates || 0) +
      (summary?.songUpdates || 0);

    if (pendingCount === 0) {
      toast.info('No pending updates to apply');
      return;
    }

    const confirmed = await confirm({
      title: 'Apply All Metadata Updates',
      message: `This will apply ${pendingCount} pending update${pendingCount === 1 ? '' : 's'}, affecting approximately ${summary?.totalAffectedSongs || 0} song${summary?.totalAffectedSongs === 1 ? '' : 's'}. Files will be re-downloaded with the new names.`,
      confirmText: 'Apply All',
      cancelText: 'Cancel',
      variant: 'warning',
    });

    if (!confirmed) return;

    try {
      const result = await applyAllUpdates();
      if (result.data?.applyAllMetadataUpdates?.success) {
        toast.success(
          result.data.applyAllMetadataUpdates.message ||
            'All updates applied successfully'
        );
        refetch();
      } else {
        toast.error(
          result.data?.applyAllMetadataUpdates?.message ||
            'Failed to apply all updates'
        );
      }
    } catch (error) {
      toast.error(
        `Error applying updates: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  }, [applyAllUpdates, confirm, toast, refetch, summary]);

  // Group updates by entity type
  const groupedUpdates = updates.reduce(
    (acc, update) => {
      const type = update.entityType;
      if (!acc[type]) {
        acc[type] = [];
      }
      acc[type].push(update);
      return acc;
    },
    {} as Record<MetadataEntityType, typeof updates>
  );

  const pendingCount =
    statusFilter === 'pending'
      ? updates.length
      : (summary?.artistUpdates || 0) +
        (summary?.albumUpdates || 0) +
        (summary?.songUpdates || 0);

  // Entity types in display order
  const entityTypeOrder: MetadataEntityType[] = ['ARTIST', 'ALBUM', 'SONG'];

  return (
    <div className='bg-white dark:bg-slate-800 rounded-lg shadow-sm dark:shadow-none border border-gray-200 dark:border-slate-700'>
      <div className='px-6 py-4 border-b border-gray-200 dark:border-slate-700'>
        <div className='flex items-center justify-between'>
          <h2 className='text-lg font-semibold text-gray-900 dark:text-slate-100'>
            Metadata Changes
          </h2>
          {statusFilter === 'pending' && pendingCount > 0 && (
            <button
              type='button'
              onClick={handleApplyAll}
              disabled={isApplyingAll}
              className='px-4 py-2 text-sm font-medium rounded-md bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors'
            >
              {isApplyingAll ? 'Applying...' : `Apply All (${pendingCount})`}
            </button>
          )}
        </div>
        <p className='text-sm text-gray-600 dark:text-slate-400 mt-1'>
          Name changes detected from Spotify that can be applied to your library
        </p>
      </div>

      <div className='px-6 py-4 border-b border-gray-200 dark:border-slate-700'>
        <FilterButtonGroup
          value={statusFilter}
          options={STATUS_FILTER_OPTIONS}
          onChange={setStatusFilter}
          label='Filter by Status'
        />
      </div>

      {summary && statusFilter === 'pending' && (
        <div className='px-6 py-4 bg-gray-50 dark:bg-slate-900 border-b border-gray-200 dark:border-slate-700'>
          <div className='flex gap-6 text-sm'>
            <div className='flex items-center gap-2'>
              <span className='text-2xl'>🎤</span>
              <span className='text-gray-600 dark:text-slate-400'>
                Artists:
              </span>
              <span className='font-medium text-gray-900 dark:text-slate-100'>
                {summary.artistUpdates}
              </span>
            </div>
            <div className='flex items-center gap-2'>
              <span className='text-2xl'>💿</span>
              <span className='text-gray-600 dark:text-slate-400'>Albums:</span>
              <span className='font-medium text-gray-900 dark:text-slate-100'>
                {summary.albumUpdates}
              </span>
            </div>
            <div className='flex items-center gap-2'>
              <span className='text-2xl'>🎵</span>
              <span className='text-gray-600 dark:text-slate-400'>Songs:</span>
              <span className='font-medium text-gray-900 dark:text-slate-100'>
                {summary.songUpdates}
              </span>
            </div>
            <div className='border-l border-gray-300 dark:border-slate-600 pl-6 flex items-center gap-2'>
              <span className='text-gray-600 dark:text-slate-400'>
                Total affected songs:
              </span>
              <span className='font-semibold text-gray-900 dark:text-slate-100'>
                {summary.totalAffectedSongs}
              </span>
            </div>
          </div>
        </div>
      )}

      <div className='p-6'>
        {loading ? (
          <div className='text-center py-8 text-gray-500 dark:text-slate-400'>
            <div className='animate-spin text-4xl mb-4'>⏳</div>
            <p>Loading metadata changes...</p>
          </div>
        ) : updates.length === 0 ? (
          <div className='text-center py-8 text-gray-500 dark:text-slate-400'>
            <div className='text-4xl mb-4'>✅</div>
            <p>
              {statusFilter === 'pending'
                ? 'No pending metadata changes'
                : `No ${statusFilter} metadata changes`}
            </p>
            <p className='text-sm'>
              {statusFilter === 'pending'
                ? 'Changes will be detected during downloads and playlist syncs'
                : 'Try a different filter to see other updates'}
            </p>
          </div>
        ) : (
          <div className='space-y-6'>
            {entityTypeOrder.map(entityType => {
              const typeUpdates = groupedUpdates[entityType];
              if (!typeUpdates || typeUpdates.length === 0) return null;

              return (
                <div key={entityType}>
                  <h3 className='text-sm font-medium text-gray-700 dark:text-slate-300 mb-3 flex items-center gap-2'>
                    <span>{getEntityTypeIcon(entityType)}</span>
                    {getEntityTypeLabel(entityType)} Changes (
                    {typeUpdates.length})
                  </h3>
                  <div className='space-y-2'>
                    {typeUpdates.map(update => {
                      const statusBadge = getStatusBadge(update.status);
                      const isPending = update.status === 'PENDING';
                      const isLoading = actionInProgress === update.id;

                      return (
                        <div
                          key={update.id}
                          className={`flex items-center justify-between p-4 rounded-lg border ${
                            isPending
                              ? 'bg-orange-50 dark:bg-orange-950 border-orange-200 dark:border-orange-900'
                              : 'bg-gray-50 dark:bg-slate-900 border-gray-200 dark:border-slate-700'
                          }`}
                        >
                          <div className='flex-1 min-w-0'>
                            <div className='flex items-center gap-2'>
                              <span
                                className={`px-2 py-0.5 text-xs rounded-full ${statusBadge.className}`}
                              >
                                {statusBadge.label}
                              </span>
                              <span className='text-sm text-gray-500 dark:text-slate-400'>
                                {formatRelativeTime(update.detectedAt)}
                              </span>
                            </div>
                            <div className='mt-2 flex items-center gap-2 text-sm'>
                              <span className='text-gray-600 dark:text-slate-400 line-through'>
                                {update.oldValue}
                              </span>
                              <span className='text-gray-400 dark:text-slate-500'>
                                →
                              </span>
                              <span className='font-medium text-gray-900 dark:text-slate-100'>
                                {update.newValue}
                              </span>
                            </div>
                            {update.affectedSongsCount > 0 && isPending && (
                              <div className='mt-1 text-xs text-gray-500 dark:text-slate-400'>
                                {update.affectedSongsCount} song
                                {update.affectedSongsCount === 1
                                  ? ''
                                  : 's'}{' '}
                                will be re-downloaded
                              </div>
                            )}
                          </div>

                          {isPending && (
                            <div className='flex items-center gap-2 ml-4'>
                              <button
                                type='button'
                                onClick={() =>
                                  handleApply(update.id, update.entityName)
                                }
                                disabled={isLoading}
                                className='px-3 py-1.5 text-xs font-medium rounded-md bg-indigo-100 dark:bg-blue-950 text-indigo-700 dark:text-blue-400 hover:bg-indigo-200 dark:hover:bg-blue-900 disabled:opacity-50 disabled:cursor-not-allowed transition-colors'
                              >
                                {isLoading ? 'Applying...' : 'Apply'}
                              </button>
                              <button
                                type='button'
                                onClick={() =>
                                  handleDismiss(update.id, update.entityName)
                                }
                                disabled={isLoading}
                                className='px-3 py-1.5 text-xs font-medium rounded-md bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors'
                              >
                                Dismiss
                              </button>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
      <ConfirmDialog />
    </div>
  );
}
