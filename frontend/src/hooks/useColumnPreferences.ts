import { useState, useCallback } from 'react';

export function useColumnPreferences(
  storageKey: string,
  defaultColumns: string[]
): {
  visibleColumns: string[];
  toggleColumn: (key: string) => void;
  isColumnVisible: (key: string) => boolean;
} {
  const [visibleColumns, setVisibleColumns] = useState<string[]>(() => {
    const stored = localStorage.getItem(storageKey);
    if (stored) {
      try {
        const parsed: unknown = JSON.parse(stored);
        if (
          Array.isArray(parsed) &&
          parsed.every((v): v is string => typeof v === 'string')
        ) {
          return parsed;
        }
      } catch {
        // Invalid JSON, use defaults
      }
    }
    return defaultColumns;
  });

  const toggleColumn = useCallback(
    (key: string) => {
      setVisibleColumns(prev => {
        const next = prev.includes(key)
          ? prev.filter(k => k !== key)
          : [...prev, key];
        localStorage.setItem(storageKey, JSON.stringify(next));
        return next;
      });
    },
    [storageKey]
  );

  const isColumnVisible = useCallback(
    (key: string) => visibleColumns.includes(key),
    [visibleColumns]
  );

  return { visibleColumns, toggleColumn, isColumnVisible };
}
