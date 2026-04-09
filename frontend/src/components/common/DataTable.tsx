import React from 'react';
import { PaginationBar } from '../ui/PaginationBar';
import { ErrorBanner } from '../ui/ErrorBanner';
import { EmptyState } from '../ui/EmptyState';
import { SkeletonTable } from '../ui/SkeletonTable';

interface DataTableProps<T> {
  data: T[];
  loading: boolean;
  error?: Error | null;
  totalCount: number;
  pageSize: number;
  page?: number;
  totalPages?: number;
  onPageChange?: (page: number) => void;
  /** @deprecated Use page/totalPages/onPageChange instead */
  hasNextPage?: boolean;
  /** @deprecated Use page/totalPages/onPageChange instead */
  onLoadMore?: () => void;
  children: React.ReactNode;
  emptyMessage?: string;
  loadingMessage?: string;
  errorMessage?: string;
}

export function DataTable<T>({
  data,
  loading,
  error,
  totalCount,
  pageSize,
  page = 1,
  totalPages = 1,
  onPageChange,
  children,
  emptyMessage = 'No data found',
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  loadingMessage = 'Loading...',
  errorMessage = 'Error loading data',
}: DataTableProps<T>) {
  if (loading && data.length === 0) {
    // Skeletons for initial loads
    return <SkeletonTable columns={4} rows={10} />;
  }

  if (error) {
    return (
      <ErrorBanner
        title={errorMessage}
        message={error.message}
        onRetry={onPageChange ? () => onPageChange(page) : undefined}
      />
    );
  }

  if (data.length === 0) {
    return <EmptyState title={emptyMessage} />;
  }

  return (
    <div className='space-y-4'>
      <div className='text-sm text-gray-500 dark:text-slate-400'>
        Page {page} of {totalPages} — {totalCount.toLocaleString()} total items
      </div>
      <div className='bg-white dark:bg-slate-800 rounded shadow overflow-hidden'>
        {children}
        {onPageChange && (
          <PaginationBar
            page={page}
            totalPages={totalPages}
            totalCount={totalCount}
            pageSize={pageSize}
            onPageChange={onPageChange}
            loading={loading}
          />
        )}
      </div>
    </div>
  );
}
