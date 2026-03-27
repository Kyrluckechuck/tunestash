import { useMutation, useQuery } from '@apollo/client/react';
import { useCallback, useState } from 'react';
import {
  GetOneOffTasksDocument,
  RunOneOffTaskDocument,
} from '../../types/generated/graphql';
import { useToast } from '../ui/useToast';

interface OneOffTask {
  id: string;
  name: string;
  description: string;
  category: string;
}

function getCategoryStyle(category: string): {
  bg: string;
  text: string;
  border: string;
} {
  switch (category) {
    case 'data-migration':
      return {
        bg: 'bg-purple-50 dark:bg-purple-950',
        text: 'text-purple-700 dark:text-purple-400',
        border: 'border-purple-200 dark:border-purple-900',
      };
    case 'cleanup':
      return {
        bg: 'bg-orange-50 dark:bg-orange-950',
        text: 'text-orange-700 dark:text-orange-400',
        border: 'border-orange-200 dark:border-orange-900',
      };
    case 'maintenance':
    default:
      return {
        bg: 'bg-blue-50 dark:bg-blue-950',
        text: 'text-blue-700 dark:text-blue-400',
        border: 'border-blue-200 dark:border-blue-900',
      };
  }
}

function formatCategory(category: string): string {
  return category
    .split('-')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

interface RunButtonProps {
  task: OneOffTask;
  onRun: (taskId: string, taskName: string) => void;
  isRunning: boolean;
  runningTaskId: string | null;
}

function RunButton({ task, onRun, isRunning, runningTaskId }: RunButtonProps) {
  const isThisRunning = isRunning && runningTaskId === task.id;

  return (
    <button
      type='button'
      onClick={() => onRun(task.id, task.name)}
      disabled={isRunning}
      className={`
        px-4 py-2 text-sm font-medium rounded-md transition-colors
        bg-indigo-600 text-white hover:bg-indigo-700
        ${isRunning ? 'opacity-50 cursor-not-allowed' : ''}
        ${isThisRunning ? 'cursor-wait' : ''}
      `}
    >
      {isThisRunning ? 'Queuing...' : 'Run Now'}
    </button>
  );
}

export function OneOffTasksSection() {
  const toast = useToast();
  const [runningTaskId, setRunningTaskId] = useState<string | null>(null);

  const { data, loading } = useQuery(GetOneOffTasksDocument);
  const [runTask, { loading: isRunning }] = useMutation(RunOneOffTaskDocument);

  const handleRun = useCallback(
    async (taskId: string, taskName: string) => {
      setRunningTaskId(taskId);
      try {
        const result = await runTask({ variables: { taskId } });
        if (result.data?.runOneOffTask?.success) {
          toast.success(`"${taskName}" queued for execution`);
        } else {
          toast.error(
            result.data?.runOneOffTask?.message || 'Failed to queue task'
          );
        }
      } catch (error) {
        toast.error(
          `Failed to run task: ${error instanceof Error ? error.message : 'Unknown error'}`
        );
      } finally {
        setRunningTaskId(null);
      }
    },
    [runTask, toast]
  );

  const tasks: OneOffTask[] = data?.oneOffTasks || [];

  // Group tasks by category
  const tasksByCategory = tasks.reduce(
    (acc, task) => {
      const cat = task.category || 'other';
      if (!acc[cat]) acc[cat] = [];
      acc[cat].push(task);
      return acc;
    },
    {} as Record<string, OneOffTask[]>
  );

  return (
    <div className='bg-white dark:bg-slate-800 rounded-lg shadow-sm dark:shadow-none border border-gray-200 dark:border-slate-700'>
      <div className='px-6 py-4 border-b border-gray-200 dark:border-slate-700'>
        <div className='flex items-center justify-between'>
          <div>
            <h2 className='text-lg font-semibold text-gray-900 dark:text-slate-100'>
              One-Off Tasks
            </h2>
            <p className='text-sm text-gray-500 dark:text-slate-400 mt-1'>
              Manual maintenance tasks that can be run on demand
            </p>
          </div>
          <span className='text-sm text-gray-600 dark:text-slate-400'>
            {loading ? 'Loading...' : `${tasks.length} available`}
          </span>
        </div>
      </div>

      <div className='p-6'>
        {tasks.length === 0 ? (
          <div className='text-center py-8 text-gray-500 dark:text-slate-400'>
            <div className='text-4xl mb-4'>🔧</div>
            <p>No one-off tasks available</p>
            <p className='text-sm'>
              One-off maintenance tasks will appear here when configured
            </p>
          </div>
        ) : (
          <div className='space-y-4'>
            {Object.entries(tasksByCategory).map(
              ([category, categoryTasks]) => (
                <div key={category}>
                  <div className='text-xs font-medium text-gray-500 dark:text-slate-400 uppercase tracking-wider mb-2'>
                    {formatCategory(category)}
                  </div>
                  <div className='space-y-3'>
                    {categoryTasks.map(task => {
                      const style = getCategoryStyle(task.category);
                      return (
                        <div
                          key={task.id}
                          className={`flex items-center justify-between p-4 rounded-lg border ${style.bg} ${style.border}`}
                        >
                          <div className='flex-1 min-w-0 pr-4'>
                            <div className='flex items-center gap-2'>
                              <span className='font-medium text-gray-900 dark:text-slate-100'>
                                {task.name}
                              </span>
                              <span
                                className={`px-2 py-0.5 text-xs rounded-full ${style.bg} ${style.text}`}
                              >
                                {formatCategory(task.category)}
                              </span>
                            </div>
                            <p className='text-sm text-gray-600 dark:text-slate-400 mt-1'>
                              {task.description}
                            </p>
                          </div>
                          <RunButton
                            task={task}
                            onRun={handleRun}
                            isRunning={isRunning}
                            runningTaskId={runningTaskId}
                          />
                        </div>
                      );
                    })}
                  </div>
                </div>
              )
            )}
          </div>
        )}
      </div>
    </div>
  );
}
