import { useState } from 'react';
import { createFileRoute } from '@tanstack/react-router';

// Components
import { PlaylistFilters } from '../components/playlists/PlaylistFilters';
import { PlaylistsTable } from '../components/playlists/PlaylistsTable';
import { PageSizeSelector } from '../components/ui/PageSizeSelector';
import { InlineSpinner } from '../components/ui/InlineSpinner';
import { PageSpinner } from '../components/ui/PageSpinner';
import { ErrorBanner } from '../components/ui/ErrorBanner';
import { LoadMoreButton } from '../components/ui/LoadMoreButton';
import { PlaylistModal } from '../components/ui/PlaylistModal';
import { SearchInput } from '../components/ui/SearchInput';
import { ExternalListsSection } from '../components/external-lists/ExternalListsSection';

// Hooks
import { usePlaylistsPage } from '../hooks/usePlaylistsPage';

type PlaylistTab = 'synced' | 'external';

function Playlists() {
  const [activeTab, setActiveTab] = useState<PlaylistTab>('synced');

  const {
    // Data
    playlists,
    totalCount,
    pageInfo,
    loading,
    error,
    isRefreshing,
    isInitialLoading,
    issuesCount,

    // Filters & sorting
    filter,
    pageSize,
    sortField,
    sortDirection,
    searchQuery,

    // Modal state
    showPlaylistModal,
    editingPlaylist,

    // Mutation states
    enabledMutatingIds,
    enabledPulseIds,
    autoMutatingIds,
    autoPulseIds,
    syncMutatingIds,
    forceSyncMutatingIds,
    deleteMutatingIds,
    recheckMutatingIds,
    errorById,

    // Handlers
    handleEnabledFilterChange,
    handlePageSizeChange,
    handleSort,
    handleSearch,
    handleFilterHover,
    handleTogglePlaylist,
    handleSyncPlaylist,
    handleForceSyncPlaylist,
    handleRecheckPlaylist,
    handleDeletePlaylist,
    handleToggleAutoTrack,
    handleEditPlaylist,
    handleClosePlaylistModal,
    handleCreatePlaylist,
    handleDownloadAllPlaylists,
    handleLoadMore,
  } = usePlaylistsPage();

  const tabClass = (tab: PlaylistTab) =>
    `px-4 py-2 text-sm font-medium rounded-t-md border-b-2 transition-colors ${
      activeTab === tab
        ? 'border-indigo-500 text-indigo-600'
        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
    }`;

  return (
    <section>
      <h1 className='text-2xl font-semibold mb-4'>Playlists</h1>

      <div className='flex gap-1 border-b border-gray-200 mb-6'>
        <button
          className={tabClass('synced')}
          onClick={() => setActiveTab('synced')}
        >
          Synced Playlists
        </button>
        <button
          className={tabClass('external')}
          onClick={() => setActiveTab('external')}
        >
          External Lists
        </button>
      </div>

      {activeTab === 'synced' && (
        <SyncedPlaylistsTab
          playlists={playlists}
          totalCount={totalCount}
          pageInfo={pageInfo}
          loading={loading}
          error={error}
          isRefreshing={isRefreshing}
          isInitialLoading={isInitialLoading}
          issuesCount={issuesCount}
          filter={filter}
          pageSize={pageSize}
          sortField={sortField}
          sortDirection={sortDirection}
          searchQuery={searchQuery}
          showPlaylistModal={showPlaylistModal}
          editingPlaylist={editingPlaylist}
          enabledMutatingIds={enabledMutatingIds}
          enabledPulseIds={enabledPulseIds}
          autoMutatingIds={autoMutatingIds}
          autoPulseIds={autoPulseIds}
          syncMutatingIds={syncMutatingIds}
          forceSyncMutatingIds={forceSyncMutatingIds}
          deleteMutatingIds={deleteMutatingIds}
          recheckMutatingIds={recheckMutatingIds}
          errorById={errorById}
          handleEnabledFilterChange={handleEnabledFilterChange}
          handlePageSizeChange={handlePageSizeChange}
          handleSort={handleSort}
          handleSearch={handleSearch}
          handleFilterHover={handleFilterHover}
          handleTogglePlaylist={handleTogglePlaylist}
          handleSyncPlaylist={handleSyncPlaylist}
          handleForceSyncPlaylist={handleForceSyncPlaylist}
          handleRecheckPlaylist={handleRecheckPlaylist}
          handleDeletePlaylist={handleDeletePlaylist}
          handleToggleAutoTrack={handleToggleAutoTrack}
          handleEditPlaylist={handleEditPlaylist}
          handleClosePlaylistModal={handleClosePlaylistModal}
          handleCreatePlaylist={handleCreatePlaylist}
          handleDownloadAllPlaylists={handleDownloadAllPlaylists}
          handleLoadMore={handleLoadMore}
        />
      )}

      {activeTab === 'external' && <ExternalListsSection />}
    </section>
  );
}

function SyncedPlaylistsTab({
  playlists,
  totalCount,
  pageInfo,
  loading,
  error,
  isRefreshing,
  isInitialLoading,
  issuesCount,
  filter,
  pageSize,
  sortField,
  sortDirection,
  showPlaylistModal,
  editingPlaylist,
  enabledMutatingIds,
  enabledPulseIds,
  autoMutatingIds,
  autoPulseIds,
  syncMutatingIds,
  forceSyncMutatingIds,
  deleteMutatingIds,
  recheckMutatingIds,
  errorById,
  handleEnabledFilterChange,
  handlePageSizeChange,
  handleSort,
  handleSearch,
  handleFilterHover,
  handleTogglePlaylist,
  handleSyncPlaylist,
  handleForceSyncPlaylist,
  handleRecheckPlaylist,
  handleDeletePlaylist,
  handleToggleAutoTrack,
  handleEditPlaylist,
  handleClosePlaylistModal,
  handleCreatePlaylist,
  handleDownloadAllPlaylists,
  handleLoadMore,
}: ReturnType<typeof usePlaylistsPage>) {
  if (isInitialLoading && !playlists.length) {
    return <PageSpinner message='Loading playlists...' />;
  }

  if (error) {
    return (
      <ErrorBanner title='Error loading playlists' message={error.message} />
    );
  }

  return (
    <>
      <div className='flex items-center justify-between mb-4'>
        <div className='flex items-center gap-3'>
          <h2 className='text-lg font-medium text-gray-700'>
            Synced Playlists ({playlists.length} of {totalCount})
          </h2>
          {isRefreshing && <InlineSpinner label='Updating...' />}
        </div>
        <div className='flex items-center gap-4'>
          <button
            onClick={handleDownloadAllPlaylists}
            disabled={loading}
            className='px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm'
          >
            Download All Enabled Playlists
          </button>
          <button
            onClick={handleCreatePlaylist}
            className='px-4 py-2 bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors text-sm'
          >
            Create Playlist
          </button>

          <SearchInput
            placeholder='Search playlists...'
            onSearch={handleSearch}
            className='w-64'
          />
          <PageSizeSelector
            pageSize={pageSize}
            onPageSizeChange={handlePageSizeChange}
          />
          {totalCount > playlists.length && (
            <span className='text-sm text-gray-500'>
              Showing first {playlists.length} playlists
            </span>
          )}
        </div>
      </div>

      <PlaylistFilters
        currentEnabledFilter={filter}
        onEnabledFilterChange={handleEnabledFilterChange}
        onFilterHover={handleFilterHover}
        issuesCount={issuesCount}
      />

      <div className='relative'>
        <PlaylistsTable
          playlists={playlists}
          sortField={sortField}
          sortDirection={sortDirection}
          onSort={handleSort}
          onToggleEnabled={handleTogglePlaylist}
          onToggleAutoTrack={handleToggleAutoTrack}
          onSyncPlaylist={handleSyncPlaylist}
          onForceSyncPlaylist={handleForceSyncPlaylist}
          onRecheckPlaylist={handleRecheckPlaylist}
          onEditPlaylist={handleEditPlaylist}
          onDeletePlaylist={handleDeletePlaylist}
          loading={loading}
          enabledMutatingIds={enabledMutatingIds}
          autoMutatingIds={autoMutatingIds}
          syncMutatingIds={syncMutatingIds}
          forceSyncMutatingIds={forceSyncMutatingIds}
          recheckMutatingIds={recheckMutatingIds}
          deleteMutatingIds={deleteMutatingIds}
          enabledPulseIds={enabledPulseIds}
          autoPulseIds={autoPulseIds}
          errorById={errorById}
        />
      </div>

      <LoadMoreButton
        hasNextPage={!!pageInfo?.hasNextPage}
        loading={loading}
        remainingCount={totalCount - playlists.length}
        onLoadMore={handleLoadMore}
      />

      <PlaylistModal
        isOpen={showPlaylistModal}
        onClose={handleClosePlaylistModal}
        playlist={editingPlaylist}
        mode={editingPlaylist ? 'edit' : 'create'}
      />
    </>
  );
}

export const Route = createFileRoute('/playlists')({
  component: Playlists,
});
