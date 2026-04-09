import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { useColumnPreferences } from '../useColumnPreferences';

const STORAGE_KEY = 'test:columns';
const DEFAULTS = ['lastSynced', 'lastDownloaded'];

describe('useColumnPreferences', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('returns defaults when localStorage is empty', () => {
    const { result } = renderHook(() =>
      useColumnPreferences(STORAGE_KEY, DEFAULTS)
    );
    expect(result.current.visibleColumns).toEqual(DEFAULTS);
  });

  it('reads persisted value from localStorage', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(['addedAt']));
    const { result } = renderHook(() =>
      useColumnPreferences(STORAGE_KEY, DEFAULTS)
    );
    expect(result.current.visibleColumns).toEqual(['addedAt']);
  });

  it('falls back to defaults when localStorage has invalid JSON', () => {
    localStorage.setItem(STORAGE_KEY, 'not-valid-json');
    const { result } = renderHook(() =>
      useColumnPreferences(STORAGE_KEY, DEFAULTS)
    );
    expect(result.current.visibleColumns).toEqual(DEFAULTS);
  });

  it('falls back to defaults when localStorage has non-array value', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ foo: 'bar' }));
    const { result } = renderHook(() =>
      useColumnPreferences(STORAGE_KEY, DEFAULTS)
    );
    expect(result.current.visibleColumns).toEqual(DEFAULTS);
  });

  it('falls back to defaults when localStorage has array with non-strings', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([1, 2, 3]));
    const { result } = renderHook(() =>
      useColumnPreferences(STORAGE_KEY, DEFAULTS)
    );
    expect(result.current.visibleColumns).toEqual(DEFAULTS);
  });

  it('toggleColumn adds a column that is not visible', () => {
    const { result } = renderHook(() =>
      useColumnPreferences(STORAGE_KEY, DEFAULTS)
    );
    act(() => {
      result.current.toggleColumn('addedAt');
    });
    expect(result.current.visibleColumns).toContain('addedAt');
  });

  it('toggleColumn removes a column that is already visible', () => {
    const { result } = renderHook(() =>
      useColumnPreferences(STORAGE_KEY, DEFAULTS)
    );
    act(() => {
      result.current.toggleColumn('lastSynced');
    });
    expect(result.current.visibleColumns).not.toContain('lastSynced');
  });

  it('persists to localStorage after toggle', () => {
    const { result } = renderHook(() =>
      useColumnPreferences(STORAGE_KEY, DEFAULTS)
    );
    act(() => {
      result.current.toggleColumn('addedAt');
    });
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]');
    expect(stored).toContain('addedAt');
  });

  it('isColumnVisible returns true for visible columns', () => {
    const { result } = renderHook(() =>
      useColumnPreferences(STORAGE_KEY, DEFAULTS)
    );
    expect(result.current.isColumnVisible('lastSynced')).toBe(true);
  });

  it('isColumnVisible returns false for hidden columns', () => {
    const { result } = renderHook(() =>
      useColumnPreferences(STORAGE_KEY, DEFAULTS)
    );
    expect(result.current.isColumnVisible('addedAt')).toBe(false);
  });

  it('isColumnVisible updates after toggle', () => {
    const { result } = renderHook(() =>
      useColumnPreferences(STORAGE_KEY, DEFAULTS)
    );
    act(() => {
      result.current.toggleColumn('addedAt');
    });
    expect(result.current.isColumnVisible('addedAt')).toBe(true);
    act(() => {
      result.current.toggleColumn('addedAt');
    });
    expect(result.current.isColumnVisible('addedAt')).toBe(false);
  });

  it('toggleColumn is stable across renders (referential equality)', () => {
    const { result, rerender } = renderHook(() =>
      useColumnPreferences(STORAGE_KEY, DEFAULTS)
    );
    const firstToggle = result.current.toggleColumn;
    rerender();
    expect(result.current.toggleColumn).toBe(firstToggle);
  });

  it('multiple hooks with different keys are independent', () => {
    const { result: r1 } = renderHook(() =>
      useColumnPreferences('key:a', ['col1'])
    );
    const { result: r2 } = renderHook(() =>
      useColumnPreferences('key:b', ['col2'])
    );
    act(() => {
      r1.current.toggleColumn('col1');
    });
    expect(r1.current.visibleColumns).not.toContain('col1');
    expect(r2.current.visibleColumns).toContain('col2');
  });

  it('localStorage.getItem is called with correct key during init', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem');
    renderHook(() => useColumnPreferences(STORAGE_KEY, DEFAULTS));
    expect(spy).toHaveBeenCalledWith(STORAGE_KEY);
    spy.mockRestore();
  });
});
