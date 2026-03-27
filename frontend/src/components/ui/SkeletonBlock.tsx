import React from 'react';

export function SkeletonBlock({ className = '' }: { className?: string }) {
  return (
    <div
      className={`animate-pulse bg-gray-200 dark:bg-slate-600 rounded ${className}`}
    />
  );
}
