import React from 'react';

interface EmptyStateProps {
  title: string;
  description?: string;
  action?: React.ReactNode;
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className='bg-white dark:bg-slate-800 rounded shadow dark:shadow-none p-8 text-center space-y-2'>
      <div className='text-gray-600 dark:text-slate-400'>{title}</div>
      {description ? (
        <div className='text-sm text-gray-400 dark:text-slate-500'>
          {description}
        </div>
      ) : null}
      {action ? <div className='pt-2'>{action}</div> : null}
    </div>
  );
}
