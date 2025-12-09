import { createFileRoute } from '@tanstack/react-router';
import { useQuery } from '@apollo/client/react';
import { GetLibraryStatsDocument } from '../types/generated/graphql';

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
  const { data, loading, error } = useQuery(GetLibraryStatsDocument, {
    pollInterval: 30000,
  });

  if (loading) {
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

  if (error) {
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

  return (
    <section className='space-y-6'>
      <div>
        <h1 className='text-2xl font-semibold mb-1'>Library Dashboard</h1>
        <p className='text-gray-700'>
          Track your library completion progress and statistics.
        </p>
      </div>

      {/* Main Completion Progress */}
      <div className='bg-gradient-to-r from-indigo-50 to-purple-50 rounded-lg border border-indigo-200 p-6'>
        <div className='flex items-center justify-between mb-4'>
          <div>
            <h2 className='text-lg font-semibold text-gray-900'>
              Tracked Artists Progress
            </h2>
            <p className='text-sm text-gray-600'>
              Songs from {stats.trackedArtists.toLocaleString()} tracked artists
            </p>
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

      {/* Song Statistics */}
      <div>
        <h2 className='text-lg font-semibold text-gray-900 mb-3'>
          Song Statistics
        </h2>
        <div className='grid grid-cols-2 md:grid-cols-5 gap-4'>
          <StatCard title='Total Songs' value={stats.totalSongs} color='gray' />
          <StatCard
            title='Downloaded'
            value={stats.downloadedSongs}
            subtitle={`${stats.songCompletionPercentage}% of total`}
            color='green'
          />
          <StatCard
            title='Missing'
            value={stats.missingSongs}
            subtitle='Not yet attempted'
            color='blue'
          />
          <StatCard
            title='Failed'
            value={stats.failedSongs}
            subtitle='Download errors'
            color='red'
          />
          <StatCard
            title='Unavailable'
            value={stats.unavailableSongs}
            subtitle='Not on YouTube Music'
            color='yellow'
          />
        </div>
      </div>

      {/* Album Statistics */}
      <div>
        <h2 className='text-lg font-semibold text-gray-900 mb-3'>
          Album Statistics
        </h2>
        <div className='grid grid-cols-2 md:grid-cols-4 gap-4'>
          <StatCard
            title='Total Albums'
            value={stats.totalAlbums}
            color='gray'
          />
          <StatCard
            title='Complete'
            value={stats.downloadedAlbums}
            subtitle={`${stats.albumCompletionPercentage}% of total`}
            color='green'
          />
          <StatCard
            title='Partial'
            value={stats.partialAlbums}
            subtitle='Some songs downloaded'
            color='blue'
          />
          <StatCard
            title='Missing'
            value={stats.missingAlbums}
            subtitle='No songs downloaded'
            color='yellow'
          />
        </div>
      </div>

      {/* Artist Statistics */}
      <div>
        <h2 className='text-lg font-semibold text-gray-900 mb-3'>
          Artist Statistics
        </h2>
        <div className='grid grid-cols-2 md:grid-cols-2 gap-4'>
          <StatCard
            title='Total Artists'
            value={stats.totalArtists}
            color='gray'
          />
          <StatCard
            title='Tracked Artists'
            value={stats.trackedArtists}
            subtitle='Auto-syncing enabled'
            color='purple'
          />
        </div>
      </div>

      {/* Overall Library Progress */}
      <div className='bg-white rounded-lg border border-gray-200 p-6'>
        <h2 className='text-lg font-semibold text-gray-900 mb-4'>
          Overall Library Progress
        </h2>
        <div className='space-y-4'>
          <div>
            <div className='flex justify-between text-sm mb-1'>
              <span className='text-gray-600'>Song Completion</span>
              <span className='font-medium'>
                {stats.songCompletionPercentage}%
              </span>
            </div>
            <ProgressBar
              percentage={stats.songCompletionPercentage}
              color='green'
            />
          </div>
          <div>
            <div className='flex justify-between text-sm mb-1'>
              <span className='text-gray-600'>Album Completion</span>
              <span className='font-medium'>
                {stats.albumCompletionPercentage}%
              </span>
            </div>
            <ProgressBar
              percentage={stats.albumCompletionPercentage}
              color='blue'
            />
          </div>
        </div>
      </div>
    </section>
  );
}

export const Route = createFileRoute('/dashboard')({
  component: Dashboard,
});
