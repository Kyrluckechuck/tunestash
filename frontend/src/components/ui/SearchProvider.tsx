import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { SearchContext } from './SearchContext';
import type { SearchContextValue } from './SearchContext';
import { SearchModal } from './SearchModal';

export function SearchProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);

  const open = useCallback(() => {
    setIsOpen(true);
  }, []);

  const close = useCallback(() => {
    setIsOpen(false);
  }, []);

  // Global keyboard shortcut: Cmd/Ctrl + K to open search
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setIsOpen(prev => !prev);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const value = useMemo<SearchContextValue>(
    () => ({
      isOpen,
      open,
      close,
    }),
    [isOpen, open, close]
  );

  return (
    <SearchContext.Provider value={value}>
      {children}
      <SearchModal isOpen={isOpen} onClose={close} />
    </SearchContext.Provider>
  );
}
