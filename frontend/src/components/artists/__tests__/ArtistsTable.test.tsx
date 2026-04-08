import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ArtistsTable } from '../ArtistsTable';
import type { Artist } from '../../../types/generated/graphql';

describe('ArtistsTable', () => {
  const mockArtists: Artist[] = [
    {
      id: 1,
      gid: 'artist1',
      name: 'Artist 1',
      trackingTier: 1,
      lastSynced: '2024-01-01T00:00:00Z',
    },
    {
      id: 2,
      gid: 'artist2',
      name: 'Artist 2',
      trackingTier: 0,
      lastSynced: null,
    },
  ];

  const mockOnTierChange = vi.fn();
  const mockOnSyncArtist = vi.fn();
  const mockOnSort = vi.fn();

  it('renders artists in table', () => {
    render(
      <ArtistsTable
        artists={mockArtists}
        sortField={null}
        sortDirection='asc'
        onSort={mockOnSort}
        onTierChange={mockOnTierChange}
        onSyncArtist={mockOnSyncArtist}
        onDownloadArtist={vi.fn()}
        onRetryFailedSongs={vi.fn()}
        loading={false}
      />
    );

    expect(screen.getAllByText('Artist 1').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Artist 2').length).toBeGreaterThan(0);
  });

  it('shows tracked status correctly', () => {
    render(
      <ArtistsTable
        artists={mockArtists}
        sortField={null}
        sortDirection='asc'
        onSort={mockOnSort}
        onTierChange={mockOnTierChange}
        onSyncArtist={mockOnSyncArtist}
        onDownloadArtist={vi.fn()}
        onRetryFailedSongs={vi.fn()}
        loading={false}
      />
    );

    const selects = screen.getAllByRole('combobox', { name: /tracking tier/i });
    expect(selects.length).toBeGreaterThan(0);
  });

  it('calls onTierChange when tier is changed', () => {
    render(
      <ArtistsTable
        artists={mockArtists}
        sortField={null}
        sortDirection='asc'
        onSort={mockOnSort}
        onTierChange={mockOnTierChange}
        onSyncArtist={mockOnSyncArtist}
        onDownloadArtist={vi.fn()}
        onRetryFailedSongs={vi.fn()}
        loading={false}
      />
    );

    const selects = screen.getAllByRole('combobox', { name: /tracking tier/i });
    fireEvent.change(selects[0], { target: { value: '2' } });

    expect(mockOnTierChange).toHaveBeenCalledWith(mockArtists[0], 2);
  });

  it('calls onSyncArtist when sync button is clicked', () => {
    render(
      <ArtistsTable
        artists={mockArtists}
        sortField={null}
        sortDirection='asc'
        onSort={mockOnSort}
        onTierChange={mockOnTierChange}
        onSyncArtist={mockOnSyncArtist}
        onDownloadArtist={vi.fn()}
        onRetryFailedSongs={vi.fn()}
        loading={false}
      />
    );

    const syncButtons = screen.getAllByRole('button', { name: /sync/i });
    fireEvent.click(syncButtons[0]);

    expect(mockOnSyncArtist).toHaveBeenCalledWith(1);
  });

  it('shows loading state', () => {
    render(
      <ArtistsTable
        artists={[]}
        sortField={null}
        sortDirection='asc'
        onSort={mockOnSort}
        onTierChange={mockOnTierChange}
        onSyncArtist={mockOnSyncArtist}
        loading={true}
      />
    );

    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it('shows empty state when no artists', () => {
    render(
      <ArtistsTable
        artists={[]}
        sortField={null}
        sortDirection='asc'
        onSort={mockOnSort}
        onTierChange={mockOnTierChange}
        onSyncArtist={mockOnSyncArtist}
        onDownloadArtist={vi.fn()}
        onRetryFailedSongs={vi.fn()}
        loading={false}
      />
    );

    expect(screen.getByText(/no artists found/i)).toBeInTheDocument();
  });
});
