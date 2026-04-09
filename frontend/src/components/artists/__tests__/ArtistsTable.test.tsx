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
      lastDownloaded: null,
      addedAt: null,
      albumCount: 5,
      downloadedAlbumCount: 3,
      songCount: 20,
      downloadedSongCount: 15,
      undownloadedCount: 2,
      failedSongCount: 0,
    },
    {
      id: 2,
      gid: 'artist2',
      name: 'Artist 2',
      trackingTier: 0,
      lastSynced: null,
      lastDownloaded: null,
      addedAt: null,
      albumCount: 0,
      downloadedAlbumCount: 0,
      songCount: 0,
      downloadedSongCount: 0,
      undownloadedCount: 0,
      failedSongCount: 0,
    },
  ];

  const mockOnTierChange = vi.fn();
  const mockOnSyncArtist = vi.fn();
  const mockOnSort = vi.fn();
  const mockOnToggleColumn = vi.fn();
  const defaultVisibleColumns = ['lastSynced', 'lastDownloaded'];

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
        visibleColumns={defaultVisibleColumns}
        onToggleColumn={mockOnToggleColumn}
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
        visibleColumns={defaultVisibleColumns}
        onToggleColumn={mockOnToggleColumn}
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
        visibleColumns={defaultVisibleColumns}
        onToggleColumn={mockOnToggleColumn}
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
        visibleColumns={defaultVisibleColumns}
        onToggleColumn={mockOnToggleColumn}
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
        visibleColumns={defaultVisibleColumns}
        onToggleColumn={mockOnToggleColumn}
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
        visibleColumns={defaultVisibleColumns}
        onToggleColumn={mockOnToggleColumn}
        loading={false}
      />
    );

    expect(screen.getByText(/no artists found/i)).toBeInTheDocument();
  });

  it('renders optional columns when they are visible', () => {
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
        visibleColumns={['albumCount', 'songCount']}
        onToggleColumn={mockOnToggleColumn}
        loading={false}
      />
    );

    expect(screen.getByText('Albums')).toBeInTheDocument();
    expect(screen.getByText('Songs')).toBeInTheDocument();
  });

  it('does not render optional columns when they are hidden', () => {
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
        visibleColumns={[]}
        onToggleColumn={mockOnToggleColumn}
        loading={false}
      />
    );

    expect(screen.queryByText('Albums')).not.toBeInTheDocument();
    expect(screen.queryByText('Last Synced')).not.toBeInTheDocument();
  });

  it('renders Columns toggle button in desktop view', () => {
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
        visibleColumns={defaultVisibleColumns}
        onToggleColumn={mockOnToggleColumn}
        loading={false}
      />
    );

    expect(
      screen.getByRole('button', { name: /toggle columns/i })
    ).toBeInTheDocument();
  });
});
