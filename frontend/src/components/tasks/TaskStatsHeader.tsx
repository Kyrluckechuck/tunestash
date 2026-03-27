import { InlineSpinner } from '../ui/InlineSpinner';

interface TaskStatsHeaderProps {
  runningTasksCount: number;
  completedTodayCount: number;
  failedTodayCount: number;
  successRate: number;
  historyLoading: boolean;
  onRefresh: () => void;
}

export function TaskStatsHeader({
  runningTasksCount,
  completedTodayCount,
  failedTodayCount,
  successRate,
  historyLoading,
  onRefresh,
}: TaskStatsHeaderProps) {
  return (
    <>
      <div className='flex items-center justify-between'>
        <div>
          <h1 className='text-3xl font-bold text-gray-900 dark:text-slate-100'>
            Background Tasks
          </h1>
          <p className='text-gray-600 dark:text-slate-400 mt-2'>
            Monitor active processes and view task history
          </p>
        </div>
        <div className='flex items-center gap-4'>
          <div className='flex items-center gap-3 text-sm text-blue-600 dark:text-blue-400'>
            <span className='flex items-center gap-2'>
              <span className='w-2 h-2 bg-blue-500 rounded-full animate-pulse' />
              {runningTasksCount} active tasks
            </span>
            {historyLoading && <InlineSpinner label='Refreshing…' />}
            <span className='text-xs text-gray-500 dark:text-slate-400'>
              (auto-refreshing every 5s)
            </span>
          </div>
          <button
            onClick={onRefresh}
            className='px-4 py-2 bg-blue-500 text-white rounded-md hover:bg-blue-600 text-sm'
          >
            Refresh
          </button>
        </div>
      </div>

      <div className='grid grid-cols-1 md:grid-cols-4 gap-6'>
        <div className='bg-white dark:bg-slate-800 rounded-lg shadow-sm dark:shadow-none border border-gray-200 dark:border-slate-700 p-6'>
          <div className='flex items-center'>
            <div className='p-2 bg-blue-100 dark:bg-blue-900/30 rounded-lg'>
              <div className='w-6 h-6 bg-blue-500 rounded-full animate-pulse' />
            </div>
            <div className='ml-4'>
              <p className='text-sm font-medium text-gray-600 dark:text-slate-400'>
                Active Tasks
              </p>
              <p className='text-2xl font-bold text-gray-900 dark:text-slate-100'>
                {runningTasksCount}
              </p>
            </div>
          </div>
        </div>

        <div className='bg-white dark:bg-slate-800 rounded-lg shadow-sm dark:shadow-none border border-gray-200 dark:border-slate-700 p-6'>
          <div className='flex items-center'>
            <div className='p-2 bg-green-100 dark:bg-green-900/30 rounded-lg'>
              <div className='w-6 h-6 bg-green-500 rounded-full' />
            </div>
            <div className='ml-4'>
              <p className='text-sm font-medium text-gray-600 dark:text-slate-400'>
                Completed Today
              </p>
              <p className='text-2xl font-bold text-gray-900 dark:text-slate-100'>
                {completedTodayCount}
              </p>
            </div>
          </div>
        </div>

        <div className='bg-white dark:bg-slate-800 rounded-lg shadow-sm dark:shadow-none border border-gray-200 dark:border-slate-700 p-6'>
          <div className='flex items-center'>
            <div className='p-2 bg-red-100 dark:bg-red-900/30 rounded-lg'>
              <div className='w-6 h-6 bg-red-500 rounded-full' />
            </div>
            <div className='ml-4'>
              <p className='text-sm font-medium text-gray-600 dark:text-slate-400'>
                Failed Today
              </p>
              <p className='text-2xl font-bold text-gray-900 dark:text-slate-100'>
                {failedTodayCount}
              </p>
            </div>
          </div>
        </div>

        <div className='bg-white dark:bg-slate-800 rounded-lg shadow-sm dark:shadow-none border border-gray-200 dark:border-slate-700 p-6'>
          <div className='flex items-center'>
            <div className='p-2 bg-purple-100 dark:bg-purple-900/30 rounded-lg'>
              <div className='w-6 h-6 bg-purple-500 rounded-full' />
            </div>
            <div className='ml-4'>
              <p className='text-sm font-medium text-gray-600 dark:text-slate-400'>
                Success Rate
              </p>
              <p className='text-2xl font-bold text-gray-900 dark:text-slate-100'>
                {successRate}%
              </p>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
