/* eslint-disable @typescript-eslint/no-empty-function */
import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useMutationState, useMutationLoadingState } from '../useMutationState';

describe('useMutationState', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('initializes with empty state', () => {
    const { result } = renderHook(() => useMutationState());
    expect(result.current.mutatingIds.size).toBe(0);
    expect(result.current.pulseIds.size).toBe(0);
    expect(result.current.errorById).toEqual({});
  });

  it('tracks mutating ID during mutation', async () => {
    const { result } = renderHook(() => useMutationState());
    let resolveMutation = () => {};
    const mutationPromise = new Promise<void>(r => {
      resolveMutation = r;
    });

    let mutationDone = Promise.resolve();
    act(() => {
      mutationDone = result.current.handleMutation(42, () => mutationPromise);
    });

    // ID should be in mutating set during execution
    expect(result.current.mutatingIds.has(42)).toBe(true);

    // Complete mutation
    await act(async () => {
      resolveMutation();
      await mutationDone;
    });

    // ID should be removed after completion
    expect(result.current.mutatingIds.has(42)).toBe(false);
  });

  it('handles concurrent mutations independently', async () => {
    const { result } = renderHook(() => useMutationState());

    let resolve1 = () => {};
    let resolve2 = () => {};
    const p1 = new Promise<void>(r => {
      resolve1 = r;
    });
    const p2 = new Promise<void>(r => {
      resolve2 = r;
    });

    let d1 = Promise.resolve();
    let d2 = Promise.resolve();
    act(() => {
      d1 = result.current.handleMutation(1, () => p1);
      d2 = result.current.handleMutation(2, () => p2);
    });

    expect(result.current.mutatingIds.has(1)).toBe(true);
    expect(result.current.mutatingIds.has(2)).toBe(true);

    // Complete only the first
    await act(async () => {
      resolve1();
      await d1;
    });

    expect(result.current.mutatingIds.has(1)).toBe(false);
    expect(result.current.mutatingIds.has(2)).toBe(true);

    await act(async () => {
      resolve2();
      await d2;
    });

    expect(result.current.mutatingIds.has(2)).toBe(false);
  });

  it('shows pulse on success when withPulse is true', async () => {
    const { result } = renderHook(() => useMutationState());

    await act(async () => {
      await result.current.handleMutation(10, async () => {}, {
        withPulse: true,
        pulseDuration: 500,
      });
    });

    // Pulse should be active immediately after mutation
    expect(result.current.pulseIds.has(10)).toBe(true);

    // Advance timer past pulse duration
    act(() => {
      vi.advanceTimersByTime(600);
    });

    expect(result.current.pulseIds.has(10)).toBe(false);
  });

  it('does not show pulse when withPulse is false', async () => {
    const { result } = renderHook(() => useMutationState());

    await act(async () => {
      await result.current.handleMutation(10, async () => {});
    });

    expect(result.current.pulseIds.has(10)).toBe(false);
  });

  it('stores error on mutation failure', async () => {
    const { result } = renderHook(() => useMutationState());

    await act(async () => {
      await result.current.handleMutation(5, async () => {
        throw new Error('Network error');
      });
    });

    expect(result.current.errorById[5]).toBe('Network error');
    // Should not be in mutating set after failure
    expect(result.current.mutatingIds.has(5)).toBe(false);
  });

  it('stores generic error for non-Error throws', async () => {
    const { result } = renderHook(() => useMutationState());

    await act(async () => {
      await result.current.handleMutation(5, async () => {
        throw 'string error';
      });
    });

    expect(result.current.errorById[5]).toBe('Action failed');
  });

  it('clears previous error before new mutation', async () => {
    const { result } = renderHook(() => useMutationState());

    // First: fail
    await act(async () => {
      await result.current.handleMutation(5, async () => {
        throw new Error('First error');
      });
    });
    expect(result.current.errorById[5]).toBe('First error');

    // Second: succeed
    await act(async () => {
      await result.current.handleMutation(5, async () => {});
    });
    expect(result.current.errorById[5]).toBe('');
  });

  it('clearError removes error for specific ID', async () => {
    const { result } = renderHook(() => useMutationState());

    await act(async () => {
      await result.current.handleMutation(1, async () => {
        throw new Error('err1');
      });
      await result.current.handleMutation(2, async () => {
        throw new Error('err2');
      });
    });

    act(() => {
      result.current.clearError(1);
    });

    expect(result.current.errorById[1]).toBe('');
    expect(result.current.errorById[2]).toBe('err2');
  });

  it('clearAllErrors removes all errors', async () => {
    const { result } = renderHook(() => useMutationState());

    await act(async () => {
      await result.current.handleMutation(1, async () => {
        throw new Error('err1');
      });
      await result.current.handleMutation(2, async () => {
        throw new Error('err2');
      });
    });

    act(() => {
      result.current.clearAllErrors();
    });

    expect(result.current.errorById).toEqual({});
  });

  it('cleans up timeouts on unmount', async () => {
    const { result, unmount } = renderHook(() => useMutationState());

    await act(async () => {
      await result.current.handleMutation(1, async () => {}, {
        withPulse: true,
        pulseDuration: 1000,
      });
    });

    // Pulse timeout is pending
    expect(result.current.pulseIds.has(1)).toBe(true);

    // Unmount before timeout fires — should not throw
    unmount();

    // Advance time past the pulse duration — no error
    act(() => {
      vi.advanceTimersByTime(1500);
    });
  });
});

describe('useMutationLoadingState', () => {
  it('initializes with empty loading set', () => {
    const { result } = renderHook(() => useMutationLoadingState());
    expect(result.current.loadingIds.size).toBe(0);
    expect(result.current.isLoading(1)).toBe(false);
  });

  it('tracks loading state', () => {
    const { result } = renderHook(() => useMutationLoadingState());

    act(() => {
      result.current.startLoading(42);
    });

    expect(result.current.isLoading(42)).toBe(true);
    expect(result.current.isLoading(99)).toBe(false);

    act(() => {
      result.current.stopLoading(42);
    });

    expect(result.current.isLoading(42)).toBe(false);
  });

  it('handles multiple concurrent loading states', () => {
    const { result } = renderHook(() => useMutationLoadingState());

    act(() => {
      result.current.startLoading(1);
      result.current.startLoading(2);
    });

    expect(result.current.isLoading(1)).toBe(true);
    expect(result.current.isLoading(2)).toBe(true);

    act(() => {
      result.current.stopLoading(1);
    });

    expect(result.current.isLoading(1)).toBe(false);
    expect(result.current.isLoading(2)).toBe(true);
  });
});
