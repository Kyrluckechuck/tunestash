import { useState } from 'react';
import type { TaskCount, PendingTask } from '../../types/common';

interface QueueManagementSectionProps {
  queueLoading: boolean;
  totalPendingTasks: number;
  taskCounts: TaskCount[];
  pendingTasks: PendingTask[];
  onCancelTasksByName: (taskName: string) => void;
  onCancelTaskById: (taskId: string, displayName: string) => void;
  onCancelAllTasks: () => void;
}

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

export function QueueManagementSection({
  queueLoading,
  totalPendingTasks,
  taskCounts,
  pendingTasks,
  onCancelTasksByName,
  onCancelTaskById,
  onCancelAllTasks,
}: QueueManagementSectionProps) {
  const [showIndividualTasks, setShowIndividualTasks] = useState(false);

  return (
    <div className='bg-white rounded-lg shadow-sm border border-gray-200'>
      <div className='px-6 py-4 border-b border-gray-200'>
        <div className='flex items-center justify-between'>
          <h2 className='text-lg font-semibold text-gray-900'>
            Celery Task Queue
          </h2>
          <div className='flex items-center gap-2'>
            <span className='text-sm text-gray-600'>
              {queueLoading
                ? 'Loading...'
                : `${totalPendingTasks} pending tasks`}
            </span>
          </div>
        </div>
      </div>

      <div className='p-6'>
        {totalPendingTasks === 0 ? (
          <div className='text-center py-8 text-gray-500'>
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
                  className='flex items-center justify-between py-2 px-3 bg-gray-50 rounded-lg border border-gray-200'
                >
                  <div className='flex items-center gap-3 min-w-0'>
                    <span className='text-sm font-medium text-gray-900 truncate'>
                      {formatTaskName(taskCount.taskName)}
                    </span>
                    <span className='flex-shrink-0 inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800'>
                      {taskCount.count}
                    </span>
                  </div>
                  <button
                    onClick={() => onCancelTasksByName(taskCount.taskName)}
                    className='flex-shrink-0 ml-3 px-2 py-1 text-xs text-red-600 hover:text-red-800 hover:bg-red-50 rounded transition-colors'
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
                  className='text-sm text-indigo-600 hover:text-indigo-800 hover:underline'
                >
                  {showIndividualTasks
                    ? '▼ Hide individual tasks'
                    : `▶ Show ${pendingTasks.length} individual tasks`}
                </button>
              </div>
            )}

            {/* Individual Tasks List */}
            {showIndividualTasks && pendingTasks.length > 0 && (
              <div className='space-y-1 max-h-80 overflow-y-auto border border-gray-200 rounded-lg p-2 bg-gray-50'>
                {pendingTasks.map((task: PendingTask) => (
                  <div
                    key={task.taskId}
                    className='flex items-center justify-between py-1.5 px-2 bg-white rounded border border-gray-100 hover:border-gray-200 transition-colors'
                  >
                    <div className='flex items-center gap-2 min-w-0 flex-1'>
                      <span className='flex-shrink-0'>
                        {getEntityIcon(task.entityType)}
                      </span>
                      <div className='min-w-0 flex-1'>
                        <span className='text-xs font-medium text-gray-700 truncate block'>
                          {task.displayName}
                        </span>
                        {task.entityName && (
                          <span className='text-xs text-gray-500 truncate block'>
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
                              : 'bg-gray-100 text-gray-700'
                        }`}
                      >
                        {task.status}
                      </span>
                    </div>
                    <button
                      onClick={() =>
                        onCancelTaskById(task.taskId, task.displayName)
                      }
                      className='flex-shrink-0 ml-2 p-1 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors'
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

            <div className='flex justify-center pt-4 border-t border-gray-200'>
              <button
                onClick={onCancelAllTasks}
                className='px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 text-sm font-medium'
              >
                Cancel All Tasks
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
