import { useCallback, useEffect, useRef } from 'react';

interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  variant?: 'danger' | 'warning' | 'info';
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  isOpen,
  title,
  message,
  confirmText = 'Confirm',
  cancelText = 'Cancel',
  variant = 'warning',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const confirmButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (isOpen) {
      confirmButtonRef.current?.focus();
    }
  }, [isOpen]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Escape') {
        onCancel();
      } else if (e.key === 'Enter') {
        onConfirm();
      }
    },
    [onConfirm, onCancel]
  );

  if (!isOpen) return null;

  const variantStyles = {
    danger: {
      bg: 'bg-red-50 dark:bg-red-950',
      border: 'border-red-200 dark:border-red-800',
      text: 'text-red-800 dark:text-red-300',
      button: 'bg-red-600 hover:bg-red-700 focus:ring-red-500',
    },
    warning: {
      bg: 'bg-yellow-50 dark:bg-yellow-950',
      border: 'border-yellow-200 dark:border-yellow-800',
      text: 'text-yellow-800 dark:text-yellow-300',
      button: 'bg-yellow-600 hover:bg-yellow-700 focus:ring-yellow-500',
    },
    info: {
      bg: 'bg-blue-50 dark:bg-blue-950',
      border: 'border-blue-200 dark:border-blue-800',
      text: 'text-blue-800 dark:text-blue-300',
      button: 'bg-blue-600 hover:bg-blue-700 focus:ring-blue-500',
    },
  };

  const styles = variantStyles[variant];

  return (
    <div
      className='fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50'
      onClick={onCancel}
    >
      <div
        className='bg-white dark:bg-slate-800 rounded-lg shadow-xl max-w-md w-full mx-4'
        onClick={e => e.stopPropagation()}
        onKeyDown={handleKeyDown}
        role='dialog'
        aria-modal='true'
        aria-labelledby='dialog-title'
        aria-describedby='dialog-description'
      >
        <div className={`px-6 py-4 border-b ${styles.border}`}>
          <h3
            id='dialog-title'
            className={`text-lg font-semibold ${styles.text}`}
          >
            {title}
          </h3>
        </div>

        <div className='px-6 py-4'>
          <p
            id='dialog-description'
            className='text-gray-700 dark:text-slate-300'
          >
            {message}
          </p>
        </div>

        <div className='px-6 py-4 bg-gray-50 dark:bg-slate-900 rounded-b-lg flex justify-end gap-3'>
          <button
            type='button'
            onClick={onCancel}
            className='px-4 py-2 text-sm font-medium text-gray-700 dark:text-slate-300 bg-white dark:bg-slate-800 border border-gray-300 dark:border-slate-600 rounded-md hover:bg-gray-50 dark:hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-gray-500'
          >
            {cancelText}
          </button>
          <button
            ref={confirmButtonRef}
            type='button'
            onClick={onConfirm}
            className={`px-4 py-2 text-sm font-medium text-white border border-transparent rounded-md focus:outline-none focus:ring-2 focus:ring-offset-2 ${styles.button}`}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
