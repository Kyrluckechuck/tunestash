import React from 'react';
import { createFileRoute } from '@tanstack/react-router';
import { useQuery, useMutation } from '@apollo/client/react';
import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { useRequestState } from '../hooks/useRequestState';
import {
  GetTaskHistoryDocument,
  CancelRunningTasksByNameDocument,
  type TaskHistory,
  type TaskHistoryEdge,
} from '../types/generated/graphql';
import EnhancedEntityDisplay from '../components/EnhancedEntityDisplay';
import { useToast } from '../components/ui/useToast';
import { useConfirm } from '../hooks/useConfirm';
import { Tabs } from '../components/ui/Tabs';
import { TaskStatsHeader } from '../components/tasks/TaskStatsHeader';
import { QueueManagementSection } from '../components/tasks/QueueManagementSection';
import { ActiveTasksSection } from '../components/tasks/ActiveTasksSection';
import { TaskHistorySection } from '../components/tasks/TaskHistorySection';
import { ScheduledTasksSection } from '../components/tasks/ScheduledTasksSection';
import { OneOffTasksSection } from '../components/tasks/OneOffTasksSection';
import { MetadataChangesSection } from '../components/tasks/MetadataChangesSection';
import type { TaskStatus, TaskType, EntityType } from '../types/shared';

type TasksTab = 'active' | 'history' | 'scheduled' | 'metadata';

const TABS = [
  { id: 'active' as TasksTab, label: 'Active' },
  { id: 'history' as TasksTab, label: 'History' },
  { id: 'scheduled' as TasksTab, label: 'Scheduled' },
  { id: 'metadata' as TasksTab, label: 'Metadata Changes' },
];

function Tasks() {
  const { tab } = Route.useSearch();
  const activeTab = tab || 'active';
  const navigate = Route.useNavigate();
  const setActiveTab = (tab: string) => {
    navigate({ search: { tab } });
  };
  const [activeTasksFilter, setActiveTasksFilter] = useState<TaskType>('all');
  const [activeTasksEntityFilter, setActiveTasksEntityFilter] =
    useState<EntityType>('all');

  const [historyFilter, setHistoryFilter] = useState<TaskStatus>('all');
  const [historyTypeFilter, setHistoryTypeFilter] = useState<TaskType>('all');
  const [historyEntityFilter, setHistoryEntityFilter] =
    useState<EntityType>('all');
  const [pageSize, setPageSize] = useState(50);
  const [searchQuery, setSearchQuery] = useState('');

  const [expandedLogs, setExpandedLogs] = useState<Record<string, boolean>>({});
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const wasRefreshingRef = useRef(false);

  const toast = useToast();
  const { confirm, ConfirmDialog } = useConfirm();

  const [cancelRunningTasksByName] = useMutation(
    CancelRunningTasksByNameDocument
  );

  const {
    data: historyData,
    loading: historyLoading,
    error: historyError,
    fetchMore,
    refetch: refetchHistory,
    networkStatus: historyNetworkStatus,
  } = useQuery(GetTaskHistoryDocument, {
    variables: {
      status: historyFilter === 'all' ? undefined : historyFilter,
      type: historyTypeFilter === 'all' ? undefined : historyTypeFilter,
      entityType:
        historyEntityFilter === 'all' ? undefined : historyEntityFilter,
      search: searchQuery || undefined,
      first: pageSize,
    },
    fetchPolicy: 'cache-first',
    notifyOnNetworkStatusChange: true,
    pollInterval: 8000,
  });

  const { isRefreshing: isHistoryRefreshing } =
    useRequestState(historyNetworkStatus);

  // Track when a refresh cycle completes (poll or manual refresh)
  useEffect(() => {
    // When we transition from refreshing to not refreshing, a fetch just completed
    if (wasRefreshingRef.current && !isHistoryRefreshing && historyData) {
      setLastUpdated(new Date());
    }
    wasRefreshingRef.current = isHistoryRefreshing;
  }, [isHistoryRefreshing, historyData]);

  const historyNodes = useMemo<TaskHistory[]>(
    () => historyData?.taskHistory?.edges?.map(edge => edge.node) || [],
    [historyData?.taskHistory?.edges]
  );

  // Single-pass filtering and categorization for better performance
  const taskCategories = useMemo(() => {
    const categories = {
      running: [] as TaskHistory[],
      completed: [] as TaskHistory[],
      failed: [] as TaskHistory[],
      allActive: [] as TaskHistory[],
    };

    for (const task of historyNodes) {
      // Only process RUNNING tasks for active tasks section
      if (task.status === 'RUNNING') {
        categories.allActive.push(task);

        // Apply type/entity filters
        const matchesTypeFilter =
          activeTasksFilter === 'all' ||
          task.type.toLowerCase() === activeTasksFilter;
        const matchesEntityFilter =
          activeTasksEntityFilter === 'all' ||
          task.entityType.toLowerCase() === activeTasksEntityFilter;

        if (matchesTypeFilter && matchesEntityFilter) {
          categories.running.push(task);
        }
      }
    }

    return categories;
  }, [historyNodes, activeTasksFilter, activeTasksEntityFilter]);

  const { running: runningTasks } = taskCategories;
  // Note: completedTasks and failedTasks were only used in filteredActiveTasks which was incorrect
  // (they filtered from realActiveTasks which were all RUNNING, so completed/failed would always be empty)
  const completedTasks: TaskHistory[] = [];
  const failedTasks: TaskHistory[] = [];

  // Memoize stats calculations for the stats cards
  const taskStats = useMemo(() => {
    const today = new Date().toDateString();
    let completedToday = 0;
    let failedToday = 0;
    let totalCompleted = 0;
    let totalFailed = 0;

    for (const task of historyNodes) {
      if (task.status === 'COMPLETED') {
        totalCompleted++;
        if (
          task.completedAt &&
          new Date(task.completedAt).toDateString() === today
        ) {
          completedToday++;
        }
      } else if (task.status === 'FAILED') {
        totalFailed++;
        if (
          task.completedAt &&
          new Date(task.completedAt).toDateString() === today
        ) {
          failedToday++;
        }
      }
    }

    const total = totalCompleted + totalFailed;
    const successRate =
      total > 0 ? Math.round((totalCompleted / total) * 100) : 0;

    return {
      completedToday,
      failedToday,
      successRate,
    };
  }, [historyNodes]);

  const handleCancelRunningTasksByName = useCallback(
    async (taskName: string) => {
      const confirmed = await confirm({
        title: 'Confirm Cancellation',
        message: `Are you sure you want to cancel all running '${taskName}' tasks? This action cannot be undone.`,
        confirmText: 'Cancel Tasks',
        cancelText: 'Keep Tasks',
        variant: 'danger',
      });

      if (!confirmed) return;

      try {
        const result = await cancelRunningTasksByName({
          variables: { taskName },
        });
        if (result.data?.cancelRunningTasksByName?.success) {
          toast.success(`Successfully cancelled running ${taskName} tasks`);
          refetchHistory();
        } else {
          toast.error(
            result.data?.cancelRunningTasksByName?.message ||
              'Failed to cancel running tasks'
          );
        }
      } catch (error) {
        toast.error(
          `Error cancelling tasks: ${error instanceof Error ? error.message : String(error)}`
        );
      }
    },
    [confirm, cancelRunningTasksByName, toast, refetchHistory]
  );

  const handleRefresh = useCallback(() => {
    refetchHistory();
  }, [refetchHistory]);

  return (
    <div className='space-y-8'>
      <TaskStatsHeader
        runningTasksCount={runningTasks.length}
        completedTodayCount={taskStats.completedToday}
        failedTodayCount={taskStats.failedToday}
        successRate={taskStats.successRate}
        historyLoading={historyLoading}
        onRefresh={handleRefresh}
      />

      <QueueManagementSection />

      <Tabs tabs={TABS} activeTab={activeTab} onChange={setActiveTab} />

      {activeTab === 'active' && (
        <ActiveTasksSection
          runningTasks={runningTasks}
          completedTasks={completedTasks}
          failedTasks={failedTasks}
          activeTasksFilter={activeTasksFilter}
          activeTasksEntityFilter={activeTasksEntityFilter}
          onActiveTasksFilterChange={setActiveTasksFilter}
          onActiveTasksEntityFilterChange={setActiveTasksEntityFilter}
          onCancelRunningTasksByName={handleCancelRunningTasksByName}
        />
      )}

      {activeTab === 'history' && (
        <>
          <TaskHistorySection
            data={historyData}
            loading={historyLoading}
            error={historyError}
            isRefreshing={isHistoryRefreshing}
            lastUpdated={lastUpdated}
            statusFilter={historyFilter}
            typeFilter={historyTypeFilter}
            entityFilter={historyEntityFilter}
            searchQuery={searchQuery}
            pageSize={pageSize}
            onStatusFilterChange={setHistoryFilter}
            onTypeFilterChange={setHistoryTypeFilter}
            onEntityFilterChange={setHistoryEntityFilter}
            onSearchChange={setSearchQuery}
            onPageSizeChange={setPageSize}
            onLoadMore={() =>
              fetchMore({
                variables: {
                  after: historyData?.taskHistory?.pageInfo?.endCursor,
                },
              })
            }
          />

          <div className='bg-white dark:bg-slate-800 rounded-lg shadow-sm dark:shadow-none border border-gray-200 dark:border-slate-700'>
            <div className='px-6 py-4 border-b border-gray-200 dark:border-slate-700'>
              <h2 className='text-lg font-semibold text-gray-900 dark:text-slate-100'>
                Task Logs
              </h2>
            </div>

            <div className='p-6'>
              {historyData?.taskHistory?.edges?.some(
                (edge: TaskHistoryEdge) =>
                  (edge.node.logMessages?.length ?? 0) > 0
              ) ? (
                <div className='space-y-1'>
                  {historyData.taskHistory.edges
                    .filter(
                      (edge: TaskHistoryEdge) =>
                        (edge.node.logMessages?.length ?? 0) > 0
                    )
                    .map((edge: TaskHistoryEdge) => {
                      const task = edge.node;
                      const isExpanded = !!expandedLogs[task.id];
                      return (
                        <div
                          key={task.id}
                          className='border border-gray-200 dark:border-slate-700 rounded p-2'
                        >
                          <div className='flex items-center justify-between gap-3'>
                            <div className='flex items-center gap-2 text-sm min-w-0 flex-1'>
                              <span className='font-medium text-gray-900 dark:text-slate-100 whitespace-nowrap'>
                                {task.type.charAt(0).toUpperCase() +
                                  task.type.slice(1)}
                              </span>
                              <div className='min-w-0 flex-1'>
                                <EnhancedEntityDisplay
                                  entityType={task.entityType}
                                  entityId={task.entityId}
                                  compact={true}
                                />
                              </div>
                              {!isExpanded && task.logMessages && (
                                <span className='text-xs text-gray-500 dark:text-slate-400 whitespace-nowrap flex-shrink-0'>
                                  ({task.logMessages.length} logs)
                                </span>
                              )}
                            </div>
                            <button
                              type='button'
                              onClick={() =>
                                setExpandedLogs(prev => ({
                                  ...prev,
                                  [task.id]: !isExpanded,
                                }))
                              }
                              aria-expanded={isExpanded}
                              className='text-xs text-indigo-600 dark:text-blue-400 hover:underline px-2 py-1 rounded hover:bg-indigo-50 dark:hover:bg-blue-950'
                            >
                              {isExpanded ? 'Hide' : 'Show logs'}
                            </button>
                          </div>
                          {isExpanded && (
                            <div className='mt-2 bg-gray-50 dark:bg-slate-900 rounded p-2 text-xs font-mono text-gray-700 dark:text-slate-300 max-h-32 overflow-y-auto'>
                              {task.logMessages?.map(
                                (log: string, idx: number) => (
                                  <div
                                    // eslint-disable-next-line react/no-array-index-key
                                    key={`task-${task.id}-log-${idx}`}
                                    className='mb-1'
                                  >
                                    {log}
                                  </div>
                                )
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                </div>
              ) : (
                <div className='text-center py-8 text-gray-500 dark:text-slate-400'>
                  <div className='text-4xl mb-4'>📝</div>
                  <p>No task logs available</p>
                  <p className='text-sm'>
                    Logs will appear here when tasks are executed
                  </p>
                </div>
              )}
            </div>
          </div>
        </>
      )}

      {activeTab === 'scheduled' && (
        <>
          <ScheduledTasksSection />
          <OneOffTasksSection />
        </>
      )}

      {activeTab === 'metadata' && <MetadataChangesSection />}

      <ConfirmDialog />
    </div>
  );
}

export const Route = createFileRoute('/tasks')({
  component: Tasks,
  validateSearch: (search: Record<string, unknown>) => ({
    tab: search.tab as string | undefined,
  }),
});
