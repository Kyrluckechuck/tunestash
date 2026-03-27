import { useCallback, useState } from 'react';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  GetQueueStatusDocument,
  CancelTasksByNameDocument,
  CancelAllTasksDocument,
  CancelTaskByIdDocument,
} from '../../types/generated/graphql';
import { useToast } from '../ui/useToast';
import { useConfirm } from '../../hooks/useConfirm';
import type { TaskCount, PendingTask } from '../../types/common';

function formatTaskName(fullName: string): string {
  // Strip common prefixes like "library_manager.tasks." or "downloader."
  const name = fullName
    .replace(/^library_manager\.tasks\./, '')
    .replace(/^downloader\./, '');

  // Convert snake_case to Title Case
  return name
    .split('_')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

function getEntityIcon(entityType: string | null | undefined): string {
  switch (entityType?.toLowerCase()) {
    case 'artist':
      return '🎤';
    case 'album':
      return '💿';
    case 'playlist':
      return '📋';
    case 'track':
      return '🎵';
    default:
      return '📦';
  }
}

export function QueueManagementSection() {
  const [showIndividualTasks, setShowIndividualTasks] = useState(false);
  const toast = useToast();
  const { confirm, ConfirmDialog } = useConfirm();

  const {
    data: queueData,
    loading: queueLoading,
    refetch: refetchQueue,
  } = useQuery(GetQueueStatusDocument, {
    pollInterval: 5000,
  });

  const [cancelTasksByName] = useMutation(CancelTasksByNameDocument);
  const [cancelAllTasksEnhanced] = useMutation(CancelAllTasksDocument);
  const [cancelTaskById] = useMutation(CancelTaskByIdDocument);

  const totalPendingTasks = queueData?.queueStatus?.totalPendingTasks || 0;
  const taskCounts = queueData?.queueStatus?.taskCounts || [];
  const pendingTasks = queueData?.queueStatus?.pendingTasks || [];

  const handleCancelWithConfirmation = useCallback(
    async <T extends Record<string, unknown>>(
      confirmMessage: string,
      mutationFn: () => Promise<{ data?: T | null }>,
      successMessage: string,
      errorPrefix: string = 'Failed to cancel tasks'
    ) => {
      const confirmed = await confirm({
        title: 'Confirm Cancellation',
        message: confirmMessage,
        confirmText: 'Cancel Tasks',
        cancelText: 'Keep Tasks',
        variant: 'danger',
      });

      if (!confirmed) return;

      try {
        const result = await mutationFn();
        if (!result.data) {
          toast.error(`${errorPrefix}: No data returned`);
          return;
        }

        const firstKey = Object.keys(result.data)[0];
        const data = result.data[firstKey] as
          | { success?: boolean; message?: string }
          | undefined;

        if (data?.success) {
          toast.success(successMessage);
          refetchQueue();
        } else {
          toast.error(`${errorPrefix}: ${data?.message || 'Unknown error'}`);
        }
      } catch (error) {
        toast.error(
          `Error cancelling tasks: ${error instanceof Error ? error.message : String(error)}`
        );
      }
    },
    [confirm, toast, refetchQueue]
  );

  const handleCancelAllTasks = useCallback(
    () =>
      handleCancelWithConfirmation(
        'Are you sure you want to cancel all tasks (both pending and running)? This action cannot be undone.',
        () => cancelAllTasksEnhanced(),
        'Successfully cancelled all tasks'
      ),
    [handleCancelWithConfirmation, cancelAllTasksEnhanced]
  );

  const handleCancelTasksByName = useCallback(
    (taskName: string) =>
      handleCancelWithConfirmation(
        `Are you sure you want to cancel all '${taskName}' tasks? This action cannot be undone.`,
        () => cancelTasksByName({ variables: { taskName } }),
        `Successfully cancelled ${taskName} tasks`
      ),
    [handleCancelWithConfirmation, cancelTasksByName]
  );

  const handleCancelTaskById = useCallback(
    async (taskId: string, displayName: string) => {
      const confirmed = await confirm({
        title: 'Cancel Task',
        message: `Are you sure you want to cancel this "${displayName}" task?`,
        confirmText: 'Cancel Task',
        cancelText: 'Keep Task',
        variant: 'danger',
      });

      if (!confirmed) return;

      try {
        const result = await cancelTaskById({ variables: { taskId } });
        if (result.data?.cancelTaskById?.success) {
          toast.success('Task cancelled successfully');
          refetchQueue();
        } else {
          toast.error(
            result.data?.cancelTaskById?.message || 'Failed to cancel task'
          );
        }
      } catch (error) {
        toast.error(
          `Error cancelling task: ${error instanceof Error ? error.message : String(error)}`
        );
      }
    },
    [confirm, cancelTaskById, toast, refetchQueue]
  );

  return (
    <>
      <div className='bg-white dark:bg-slate-800 rounded-lg shadow-sm dark:shadow-none border border-gray-200 dark:border-slate-700'>
        <div className='px-6 py-4 border-b border-gray-200 dark:border-slate-700'>
          <div className='flex items-center justify-between'>
            <h2 className='text-lg font-semibold text-gray-900 dark:text-slate-100'>
              Celery Task Queue
            </h2>
            <div className='flex items-center gap-2'>
              <span className='text-sm text-gray-600 dark:text-slate-400'>
                {queueLoading
                  ? 'Loading...'
                  : `${totalPendingTasks} pending tasks`}
              </span>
            </div>
          </div>
        </div>

        <div className='p-6'>
          {totalPendingTasks === 0 ? (
            <div className='text-center py-8 text-gray-500 dark:text-slate-400'>
              <div className='text-4xl mb-4'>✅</div>
              <p>No tasks queued</p>
              <p className='text-sm'>
                Tasks will appear here when queued for processing
              </p>
            </div>
          ) : (
            <div className='space-y-4'>
              {/* Task Summary by Type */}
              <div className='space-y-2'>
                {taskCounts.map((taskCount: TaskCount) => (
                  <div
                    key={taskCount.taskName}
                    className='flex items-center justify-between py-2 px-3 bg-gray-50 dark:bg-slate-900 rounded-lg border border-gray-200 dark:border-slate-700'
                  >
                    <div className='flex items-center gap-3 min-w-0'>
                      <span className='text-sm font-medium text-gray-900 dark:text-slate-100 truncate'>
                        {formatTaskName(taskCount.taskName)}
                      </span>
                      <span className='flex-shrink-0 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800'>
                        {taskCount.count}
                      </span>
                    </div>
                    <button
                      onClick={() =>
                        handleCancelTasksByName(taskCount.taskName)
                      }
                      className='flex-shrink-0 ml-3 px-2 py-1 text-xs text-red-600 dark:text-red-400 hover:text-red-800 hover:bg-red-50 dark:hover:bg-red-950 rounded transition-colors'
                      title={`Cancel all ${formatTaskName(taskCount.taskName)} tasks`}
                    >
                      Cancel All
                    </button>
                  </div>
                ))}
              </div>

              {/* Toggle for Individual Tasks */}
              {pendingTasks.length > 0 && (
                <div className='pt-2'>
                  <button
                    onClick={() => setShowIndividualTasks(!showIndividualTasks)}
                    className='text-sm text-indigo-600 dark:text-blue-400 hover:text-indigo-800 dark:hover:text-blue-300 hover:underline'
                  >
                    {showIndividualTasks
                      ? '▼ Hide individual tasks'
                      : `▶ Show ${pendingTasks.length} individual tasks`}
                  </button>
                </div>
              )}

              {/* Individual Tasks List */}
              {showIndividualTasks && pendingTasks.length > 0 && (
                <div className='space-y-1 max-h-80 overflow-y-auto border border-gray-200 dark:border-slate-700 rounded-lg p-2 bg-gray-50 dark:bg-slate-900'>
                  {pendingTasks.map((task: PendingTask) => (
                    <div
                      key={task.taskId}
                      className='flex items-center justify-between py-1.5 px-2 bg-white dark:bg-slate-800 rounded border border-gray-100 dark:border-slate-700 hover:border-gray-200 dark:hover:border-slate-600 transition-colors'
                    >
                      <div className='flex items-center gap-2 min-w-0 flex-1'>
                        <span className='flex-shrink-0'>
                          {getEntityIcon(task.entityType)}
                        </span>
                        <div className='min-w-0 flex-1'>
                          <span className='text-xs font-medium text-gray-700 dark:text-slate-300 truncate block'>
                            {task.displayName}
                          </span>
                          {task.entityName && (
                            <span className='text-xs text-gray-500 dark:text-slate-400 truncate block'>
                              {task.entityName}
                            </span>
                          )}
                        </div>
                        <span
                          className={`flex-shrink-0 px-1.5 py-0.5 rounded text-xs font-medium ${
                            task.status === 'STARTED'
                              ? 'bg-yellow-100 text-yellow-800'
                              : task.status === 'RETRY'
                                ? 'bg-orange-100 text-orange-800'
                                : 'bg-gray-100 dark:bg-slate-700 text-gray-700 dark:text-slate-300'
                          }`}
                        >
                          {task.status}
                        </span>
                      </div>
                      <button
                        onClick={() =>
                          handleCancelTaskById(task.taskId, task.displayName)
                        }
                        className='flex-shrink-0 ml-2 p-1 text-gray-400 dark:text-slate-500 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-950 rounded transition-colors'
                        title='Cancel this task'
                      >
                        <svg
                          className='w-4 h-4'
                          fill='none'
                          stroke='currentColor'
                          viewBox='0 0 24 24'
                        >
                          <path
                            strokeLinecap='round'
                            strokeLinejoin='round'
                            strokeWidth={2}
                            d='M6 18L18 6M6 6l12 12'
                          />
                        </svg>
                      </button>
                    </div>
                  ))}
                </div>
              )}

              <div className='flex justify-center pt-4 border-t border-gray-200 dark:border-slate-700'>
                <button
                  onClick={handleCancelAllTasks}
                  className='px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 text-sm font-medium'
                >
                  Cancel All Tasks
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
      <ConfirmDialog />
    </>
  );
}
