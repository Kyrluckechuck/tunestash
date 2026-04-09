import { renderHook, act } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { useDataTable } from '../useDataTable';

type SortField = 'name' | 'createdAt' | 'artist';

describe('useDataTable', () => {
  describe('initial state', () => {
    it('defaults to page 1 with no sort or search', () => {
      const { result } = renderHook(() => useDataTable<SortField>());
      expect(result.current.page).toBe(1);
      expect(result.current.pageSize).toBe(50);
      expect(result.current.sortField).toBeNull();
      expect(result.current.sortDirection).toBe('asc');
      expect(result.current.searchQuery).toBe('');
    });

    it('accepts custom initial values', () => {
      const { result } = renderHook(() =>
        useDataTable<SortField>({
          initialPageSize: 25,
          initialSortField: 'name',
          initialSortDirection: 'desc',
          initialSearchQuery: 'hello',
        })
      );
      expect(result.current.pageSize).toBe(25);
      expect(result.current.sortField).toBe('name');
      expect(result.current.sortDirection).toBe('desc');
      expect(result.current.searchQuery).toBe('hello');
    });
  });

  describe('queryVariables', () => {
    it('includes page, pageSize, sortBy, sortDirection, and omits empty search', () => {
      const { result } = renderHook(() =>
        useDataTable<SortField>({ initialSortField: 'name' })
      );
      expect(result.current.queryVariables).toEqual({
        page: 1,
        pageSize: 50,
        sortBy: 'name',
        sortDirection: 'asc',
        search: undefined,
      });
    });

    it('includes search when searchQuery is set', () => {
      const { result } = renderHook(() => useDataTable<SortField>());
      act(() => {
        result.current.setSearchQuery('arctic');
      });
      expect(result.current.queryVariables.search).toBe('arctic');
    });

    it('reflects current page in queryVariables', () => {
      const { result } = renderHook(() => useDataTable<SortField>());
      act(() => {
        result.current.setPage(4);
      });
      expect(result.current.queryVariables.page).toBe(4);
    });
  });

  describe('page reset behavior', () => {
    it('resets page to 1 when searchQuery changes', () => {
      const { result } = renderHook(() => useDataTable<SortField>());
      act(() => {
        result.current.setPage(5);
      });
      expect(result.current.page).toBe(5);

      act(() => {
        result.current.setSearchQuery('radiohead');
      });
      expect(result.current.page).toBe(1);
    });

    it('resets page to 1 when sortField changes via handleSort', () => {
      const { result } = renderHook(() => useDataTable<SortField>());
      act(() => {
        result.current.setPage(3);
      });
      expect(result.current.page).toBe(3);

      act(() => {
        result.current.handleSort('name');
      });
      expect(result.current.page).toBe(1);
    });

    it('resets page to 1 when pageSize changes', () => {
      const { result } = renderHook(() => useDataTable<SortField>());
      act(() => {
        result.current.setPage(3);
      });
      expect(result.current.page).toBe(3);

      act(() => {
        result.current.setPageSize(25);
      });
      expect(result.current.page).toBe(1);
    });

    it('resets page to 1 when sortDirection changes directly', () => {
      const { result } = renderHook(() => useDataTable<SortField>());
      act(() => {
        result.current.setPage(7);
      });
      expect(result.current.page).toBe(7);

      act(() => {
        result.current.setSortDirection('desc');
      });
      expect(result.current.page).toBe(1);
    });
  });

  describe('handleSort cycling', () => {
    it('sets field and direction asc on first click', () => {
      const { result } = renderHook(() => useDataTable<SortField>());
      act(() => {
        result.current.handleSort('name');
      });
      expect(result.current.sortField).toBe('name');
      expect(result.current.sortDirection).toBe('asc');
    });

    it('cycles to desc on second click of same field', () => {
      const { result } = renderHook(() => useDataTable<SortField>());
      act(() => {
        result.current.handleSort('name');
      });
      act(() => {
        result.current.handleSort('name');
      });
      expect(result.current.sortField).toBe('name');
      expect(result.current.sortDirection).toBe('desc');
    });

    it('clears sort on third click of same field', () => {
      const { result } = renderHook(() => useDataTable<SortField>());
      act(() => {
        result.current.handleSort('name');
      });
      act(() => {
        result.current.handleSort('name');
      });
      act(() => {
        result.current.handleSort('name');
      });
      expect(result.current.sortField).toBeNull();
      expect(result.current.sortDirection).toBe('asc');
    });

    it('resets direction to asc when switching to a different field', () => {
      const { result } = renderHook(() => useDataTable<SortField>());
      act(() => {
        result.current.handleSort('name');
      });
      act(() => {
        result.current.handleSort('name');
      });
      expect(result.current.sortDirection).toBe('desc');

      act(() => {
        result.current.handleSort('createdAt');
      });
      expect(result.current.sortField).toBe('createdAt');
      expect(result.current.sortDirection).toBe('asc');
    });
  });

  describe('resetFilters', () => {
    it('resets all state back to defaults', () => {
      const { result } = renderHook(() =>
        useDataTable<SortField>({
          initialPageSize: 25,
          initialSortField: 'artist',
          initialSortDirection: 'desc',
        })
      );

      act(() => {
        result.current.setPage(4);
        result.current.setPageSize(100);
        result.current.setSortField('name');
        result.current.setSortDirection('asc');
        result.current.setSearchQuery('foo');
      });

      act(() => {
        result.current.resetFilters();
      });

      expect(result.current.page).toBe(1);
      expect(result.current.pageSize).toBe(25);
      expect(result.current.sortField).toBe('artist');
      expect(result.current.sortDirection).toBe('desc');
      expect(result.current.searchQuery).toBe('');
    });

    it('resets to default pageSize of 50 when no initialPageSize provided', () => {
      const { result } = renderHook(() => useDataTable<SortField>());
      act(() => {
        result.current.setPageSize(100);
      });
      act(() => {
        result.current.resetFilters();
      });
      expect(result.current.pageSize).toBe(50);
    });
  });
});
