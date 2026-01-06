import { useState } from 'react';
import { createFileRoute } from '@tanstack/react-router';
import { useQuery } from '@apollo/client/react';
import { GetLibraryStatsDocument } from '../types/generated/graphql';

function RefreshIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns='http://www.w3.org/2000/svg'
      fill='none'
      viewBox='0 0 24 24'
      strokeWidth={1.5}
      stroke='currentColor'
      className={className}
    >
      <path
        strokeLinecap='round'
        strokeLinejoin='round'
        d='M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.992 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99'
      />
    </svg>
  );
}

function ChevronIcon({
  className,
  expanded,
}: {
  className?: string;
  expanded: boolean;
}) {
  return (
    <svg
      xmlns='http://www.w3.org/2000/svg'
      fill='none'
      viewBox='0 0 24 24'
      strokeWidth={1.5}
      stroke='currentColor'
      className={`${className} transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`}
    >
      <path
        strokeLinecap='round'
        strokeLinejoin='round'
        d='m19.5 8.25-7.5 7.5-7.5-7.5'
      />
    </svg>
  );
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) {
    return `${(n / 1_000_000).toFixed(1)}M`;
  }
  if (n >= 1_000) {
    return `${(n / 1_000).toFixed(1)}K`;
  }
  return n.toLocaleString();
}

function StatCard({
  title,
  value,
  subtitle,
  color = 'gray',
}: {
  title: string;
  value: string | number;
  subtitle?: string;
  color?: 'gray' | 'green' | 'blue' | 'red' | 'yellow' | 'purple';
}) {
  const colorClasses = {
    gray: 'bg-gray-50 border-gray-200',
    green: 'bg-green-50 border-green-200',
    blue: 'bg-blue-50 border-blue-200',
    red: 'bg-red-50 border-red-200',
    yellow: 'bg-yellow-50 border-yellow-200',
    purple: 'bg-purple-50 border-purple-200',
  };

  const textColorClasses = {
    gray: 'text-gray-900',
    green: 'text-green-900',
    blue: 'text-blue-900',
    red: 'text-red-900',
    yellow: 'text-yellow-900',
    purple: 'text-purple-900',
  };

  return (
    <div className={`rounded-lg border p-4 ${colorClasses[color]}`}>
      <div className='text-sm text-gray-600 mb-1'>{title}</div>
      <div className={`text-2xl font-bold ${textColorClasses[color]}`}>
        {typeof value === 'number' ? formatNumber(value) : value}
      </div>
      {subtitle && <div className='text-xs text-gray-500 mt-1'>{subtitle}</div>}
    </div>
  );
}

function ProgressBar({
  percentage,
  color = 'blue',
}: {
  percentage: number;
  color?: 'green' | 'blue' | 'purple';
}) {
  const colorClasses = {
    green: 'bg-green-500',
    blue: 'bg-blue-500',
    purple: 'bg-purple-500',
  };

  return (
    <div className='w-full bg-gray-200 rounded-full h-3'>
      <div
        className={`h-3 rounded-full transition-all duration-500 ${colorClasses[color]}`}
        style={{ width: `${Math.min(percentage, 100)}%` }}
      />
    </div>
  );
}

function Dashboard() {
  const { data, loading, error, refetch } = useQuery(GetLibraryStatsDocument);
  const [showFullStats, setShowFullStats] = useState(false);

  const isInitialLoad = loading && !data;
  const isRefetching = loading && !!data;

  if (isInitialLoad) {
    return (
      <div className='space-y-6'>
        <h1 className='text-2xl font-semibold'>Library Dashboard</h1>
        <div className='animate-pulse space-y-4'>
          <div className='h-32 bg-gray-200 rounded-lg' />
          <div className='grid grid-cols-1 md:grid-cols-4 gap-4'>
            {[1, 2, 3, 4].map(i => (
              <div key={i} className='h-24 bg-gray-200 rounded-lg' />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className='space-y-6'>
        <h1 className='text-2xl font-semibold'>Library Dashboard</h1>
        <div className='bg-red-50 border border-red-200 rounded-lg p-4'>
          <p className='text-red-700'>
            Failed to load library stats: {error.message}
          </p>
        </div>
      </div>
    );
  }

  const stats = data?.libraryStats;
  if (!stats) return null;

  const handleRefresh = () => {
    refetch();
  };

  return (
    <section className='space-y-6'>
      <div className='flex items-start justify-between'>
        <div>
          <h1 className='text-2xl font-semibold mb-1'>Library Dashboard</h1>
          <p className='text-gray-700'>
            Download progress for your {stats.trackedArtists.toLocaleString()}{' '}
            tracked artists.
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={isRefetching}
          className='flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed'
        >
          <RefreshIcon
            className={`w-4 h-4 ${isRefetching ? 'animate-spin' : ''}`}
          />
          {isRefetching ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {/* Main Song Progress - Tracked Artists */}
      <div className='bg-gradient-to-r from-indigo-50 to-purple-50 rounded-lg border border-indigo-200 p-6'>
        <div className='flex items-center justify-between mb-4'>
          <div>
            <h2 className='text-lg font-semibold text-gray-900'>
              Song Progress
            </h2>
            <p className='text-sm text-gray-600'>Songs from tracked artists</p>
          </div>
          <div className='text-right'>
            <div className='text-3xl font-bold text-indigo-700'>
              {stats.desiredCompletionPercentage}%
            </div>
            <div className='text-sm text-gray-600'>
              {formatNumber(stats.desiredDownloaded)} /{' '}
              {formatNumber(stats.desiredSongs)}
            </div>
          </div>
        </div>
        <ProgressBar
          percentage={stats.desiredCompletionPercentage}
          color='purple'
        />
      </div>

      {/* Song Statistics - Tracked Artists */}
      <div>
        <h2 className='text-lg font-semibold text-gray-900 mb-3'>
          Song Breakdown
        </h2>
        <div className='grid grid-cols-2 md:grid-cols-5 gap-4'>
          <StatCard title='Total' value={stats.desiredSongs} color='gray' />
          <StatCard
            title='Downloaded'
            value={stats.desiredDownloaded}
            subtitle={`${stats.desiredCompletionPercentage}%`}
            color='green'
          />
          <StatCard
            title='Missing'
            value={stats.desiredMissing}
            subtitle='Not yet attempted'
            color='blue'
          />
          <StatCard
            title='Failed'
            value={stats.desiredFailed}
            subtitle='Download errors'
            color='red'
          />
          <StatCard
            title='Unavailable'
            value={stats.desiredUnavailable}
            subtitle='Not on YouTube Music'
            color='yellow'
          />
        </div>
      </div>

      {/* Album Statistics - Tracked Artists */}
      <div>
        <h2 className='text-lg font-semibold text-gray-900 mb-3'>
          Album Breakdown
        </h2>
        <div className='grid grid-cols-2 md:grid-cols-4 gap-4'>
          <StatCard title='Total' value={stats.desiredAlbums} color='gray' />
          <StatCard
            title='Complete'
            value={stats.desiredAlbumsDownloaded}
            subtitle={`${stats.desiredAlbumCompletionPercentage}%`}
            color='green'
          />
          <StatCard
            title='Partial'
            value={stats.desiredAlbumsPartial}
            subtitle='Some songs downloaded'
            color='blue'
          />
          <StatCard
            title='Missing'
            value={stats.desiredAlbumsMissing}
            subtitle='No songs downloaded'
            color='yellow'
          />
        </div>
      </div>

      {/* Overall Progress Bars */}
      <div className='bg-white rounded-lg border border-gray-200 p-6'>
        <h2 className='text-lg font-semibold text-gray-900 mb-4'>
          Completion Progress
        </h2>
        <div className='space-y-4'>
          <div>
            <div className='flex justify-between text-sm mb-1'>
              <span className='text-gray-600'>Songs</span>
              <span className='font-medium'>
                {stats.desiredCompletionPercentage}%
              </span>
            </div>
            <ProgressBar
              percentage={stats.desiredCompletionPercentage}
              color='green'
            />
          </div>
          <div>
            <div className='flex justify-between text-sm mb-1'>
              <span className='text-gray-600'>Albums</span>
              <span className='font-medium'>
                {stats.desiredAlbumCompletionPercentage}%
              </span>
            </div>
            <ProgressBar
              percentage={stats.desiredAlbumCompletionPercentage}
              color='blue'
            />
          </div>
        </div>
      </div>

      {/* Full Library Stats - Collapsible */}
      <div className='border border-gray-200 rounded-lg'>
        <button
          onClick={() => setShowFullStats(!showFullStats)}
          className='w-full flex items-center justify-between p-4 text-left hover:bg-gray-50 transition-colors'
        >
          <div>
            <h2 className='text-lg font-semibold text-gray-900'>
              Full Library Statistics
            </h2>
            <p className='text-sm text-gray-500'>
              Includes all artists, not just tracked ones
            </p>
          </div>
          <ChevronIcon
            className='w-5 h-5 text-gray-500'
            expanded={showFullStats}
          />
        </button>

        {showFullStats && (
          <div className='p-4 pt-0 space-y-6 border-t border-gray-200'>
            {/* Full Library Artist Stats */}
            <div>
              <h3 className='text-md font-medium text-gray-700 mb-3'>
                Artists
              </h3>
              <div className='grid grid-cols-2 gap-4'>
                <StatCard
                  title='Total Artists'
                  value={stats.totalArtists}
                  color='gray'
                />
                <StatCard
                  title='Tracked'
                  value={stats.trackedArtists}
                  subtitle='Auto-syncing enabled'
                  color='purple'
                />
              </div>
            </div>

            {/* Full Library Song Stats */}
            <div>
              <h3 className='text-md font-medium text-gray-700 mb-3'>
                All Songs
              </h3>
              <div className='grid grid-cols-2 md:grid-cols-5 gap-4'>
                <StatCard title='Total' value={stats.totalSongs} color='gray' />
                <StatCard
                  title='Downloaded'
                  value={stats.downloadedSongs}
                  subtitle={`${stats.songCompletionPercentage}%`}
                  color='green'
                />
                <StatCard
                  title='Missing'
                  value={stats.missingSongs}
                  color='blue'
                />
                <StatCard
                  title='Failed'
                  value={stats.failedSongs}
                  color='red'
                />
                <StatCard
                  title='Unavailable'
                  value={stats.unavailableSongs}
                  color='yellow'
                />
              </div>
            </div>

            {/* Full Library Album Stats */}
            <div>
              <h3 className='text-md font-medium text-gray-700 mb-3'>
                All Albums
              </h3>
              <div className='grid grid-cols-2 md:grid-cols-4 gap-4'>
                <StatCard
                  title='Total'
                  value={stats.totalAlbums}
                  color='gray'
                />
                <StatCard
                  title='Complete'
                  value={stats.downloadedAlbums}
                  subtitle={`${stats.albumCompletionPercentage}%`}
                  color='green'
                />
                <StatCard
                  title='Partial'
                  value={stats.partialAlbums}
                  color='blue'
                />
                <StatCard
                  title='Missing'
                  value={stats.missingAlbums}
                  color='yellow'
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

export const Route = createFileRoute('/dashboard')({
  component: Dashboard,
});
