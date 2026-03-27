import React from 'react';

interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export function LoadingSpinner({
  size = 'md',
  className = '',
}: LoadingSpinnerProps) {
  const sizeClasses = {
    sm: 'w-4 h-4',
    md: 'w-6 h-6',
    lg: 'w-8 h-8',
  };

  return (
    <div
      className={`animate-spin rounded-full border-2 border-gray-300 border-t-blue-500 ${sizeClasses[size]} ${className}`}
    />
  );
}

interface LoadingOverlayProps {
  message?: string;
  className?: string;
}

export function LoadingOverlay({
  message = 'Loading...',
  className = '',
}: LoadingOverlayProps) {
  return (
    <div
      className={`absolute inset-0 bg-white dark:bg-slate-800 bg-opacity-50 dark:bg-opacity-50 flex items-center justify-center pointer-events-none ${className}`}
    >
      <div className='flex items-center gap-2 text-sm text-gray-600 dark:text-slate-400'>
        <LoadingSpinner size='sm' />
        <span>{message}</span>
      </div>
    </div>
  );
}

interface LoadingCardProps {
  message?: string;
  className?: string;
}

export function LoadingCard({
  message = 'Loading...',
  className = '',
}: LoadingCardProps) {
  return (
    <div
      className={`bg-white dark:bg-slate-800 rounded shadow p-6 min-h-[200px] flex items-center justify-center text-gray-400 dark:text-slate-500 ${className}`}
    >
      <div className='flex items-center gap-2'>
        <LoadingSpinner size='sm' />
        <span>{message}</span>
      </div>
    </div>
  );
}
