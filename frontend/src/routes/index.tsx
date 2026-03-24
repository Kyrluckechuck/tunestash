import { createFileRoute, Link } from '@tanstack/react-router';
import React from 'react';
import { useQuery } from '@apollo/client/react';
import { GetSystemStatusDocument } from '../types/generated/graphql';
import { SpotifyConnectButton } from '../components/ui/SpotifyConnectButton';

function StatusSkeleton() {
  return (
    <div className='flex items-center gap-2 animate-pulse'>
      <div className='h-4 w-4 rounded-full bg-gray-200 flex-shrink-0' />
      <div className='h-3.5 w-36 rounded bg-gray-200' />
    </div>
  );
}

function Home() {
  const { data, loading } = useQuery(GetSystemStatusDocument, {
    pollInterval: 30 * 1000, // Poll every 30 seconds
  });

  return (
    <section className='space-y-6'>
      <div>
        <h1 className='text-2xl font-semibold mb-1'>TuneStash</h1>
        <p className='text-gray-700'>
          Quickly navigate and manage your library.
        </p>
      </div>

      {/* System Health Card */}
      <div className='bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg border border-blue-200 p-4'>
        <div className='flex items-center justify-between mb-3'>
          <div className='text-gray-900 font-semibold'>System Status</div>
          <Link
            to='/tasks'
            search={{}}
            className='text-sm text-blue-600 hover:text-blue-700 font-medium'
          >
            View Tasks →
          </Link>
        </div>
        <div className='grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-2'>
          {/* Spotify Access */}
          <div className='flex items-center gap-2'>
            {loading ? (
              <StatusSkeleton />
            ) : data?.systemHealth.authentication.spotifyAuthMode ===
              'user-authenticated' ? (
              <>
                <svg
                  className='h-4 w-4 text-green-500 flex-shrink-0'
                  fill='currentColor'
                  viewBox='0 0 20 20'
                >
                  <path
                    fillRule='evenodd'
                    d='M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z'
                    clipRule='evenodd'
                  />
                </svg>
                <span className='text-sm text-gray-700'>
                  Spotify OAuth:{' '}
                  <span className='text-green-700 font-medium'>Connected</span>
                </span>
              </>
            ) : (
              <>
                <svg
                  className='h-4 w-4 text-blue-500 flex-shrink-0'
                  fill='currentColor'
                  viewBox='0 0 20 20'
                >
                  <path
                    fillRule='evenodd'
                    d='M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z'
                    clipRule='evenodd'
                  />
                </svg>
                <span className='text-sm text-gray-700'>
                  Spotify OAuth:{' '}
                  <span className='text-blue-700 font-medium'>
                    Not Connected
                  </span>
                </span>
              </>
            )}
          </div>

          {/* YouTube Music Cookies */}
          <div className='flex items-center gap-2'>
            {loading ? (
              <StatusSkeleton />
            ) : data?.systemHealth.authentication.cookiesValid ? (
              <>
                <svg
                  className='h-4 w-4 text-green-500 flex-shrink-0'
                  fill='currentColor'
                  viewBox='0 0 20 20'
                >
                  <path
                    fillRule='evenodd'
                    d='M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z'
                    clipRule='evenodd'
                  />
                </svg>
                <span className='text-sm text-gray-700'>
                  YouTube Music:{' '}
                  <span className='text-green-700 font-medium'>
                    Valid
                    {data.systemHealth.authentication.cookiesExpireInDays !==
                      null &&
                      data.systemHealth.authentication.cookiesExpireInDays <
                        30 &&
                      ` (${data.systemHealth.authentication.cookiesExpireInDays}d)`}
                  </span>
                </span>
              </>
            ) : (
              <>
                <svg
                  className='h-4 w-4 text-red-500 flex-shrink-0'
                  fill='currentColor'
                  viewBox='0 0 20 20'
                >
                  <path
                    fillRule='evenodd'
                    d='M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 9.586 8.707 8.293z'
                    clipRule='evenodd'
                  />
                </svg>
                <span className='text-sm text-gray-700'>
                  YouTube Music:{' '}
                  <span className='text-red-700 font-medium'>
                    {data?.systemHealth.authentication.cookiesErrorType ||
                      'Invalid'}
                  </span>
                </span>
              </>
            )}
          </div>

          {/* Spotify Rate Limit */}
          <div className='flex items-center gap-2'>
            {loading ? (
              <StatusSkeleton />
            ) : (
              (() => {
                const rl = data?.systemHealth.spotifyRateLimit;
                const isLimited = rl?.isRateLimited;
                const isThrottling = rl?.isThrottling;
                const iconColor = isLimited
                  ? 'text-red-500'
                  : isThrottling
                    ? 'text-yellow-500'
                    : 'text-green-500';
                const statusColor = isLimited
                  ? 'text-red-700'
                  : isThrottling
                    ? 'text-yellow-700'
                    : 'text-green-700';
                const statusText = isLimited
                  ? 'Limited'
                  : isThrottling
                    ? 'Throttling'
                    : 'OK';
                const iconPath = isLimited
                  ? 'M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 9.586 8.707 8.293z'
                  : 'M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z';
                return (
                  <>
                    <svg
                      className={`h-4 w-4 ${iconColor} flex-shrink-0`}
                      fill='currentColor'
                      viewBox='0 0 20 20'
                    >
                      <path
                        fillRule='evenodd'
                        d={iconPath}
                        clipRule='evenodd'
                      />
                    </svg>
                    <span
                      className='text-sm text-gray-700'
                      title={`Burst: ${rl?.burstCalls}/${rl?.burstMax} | Sustained: ${rl?.sustainedCalls}/${rl?.sustainedMax} | Hourly: ${rl?.hourlyCalls}/${rl?.hourlyMax}`}
                    >
                      Spotify API:{' '}
                      <span className={`${statusColor} font-medium`}>
                        {statusText}
                      </span>
                      {isLimited && rl?.rateLimitedUntil ? (
                        <span className='text-gray-500 ml-1 text-xs'>
                          (until{' '}
                          {new Date(rl.rateLimitedUntil).toLocaleTimeString(
                            [],
                            {
                              hour: '2-digit',
                              minute: '2-digit',
                            }
                          )}
                          )
                        </span>
                      ) : (
                        <span className='text-gray-500 ml-1 text-xs'>
                          ({rl?.hourlyCalls}/{rl?.hourlyMax} this hour)
                        </span>
                      )}
                    </span>
                  </>
                );
              })()
            )}
          </div>

          {/* API Rate Limits (Deezer, YouTube, etc.) */}
          {!loading &&
            data?.systemHealth.apiRateLimits.map(api => {
              const displayNames: Record<string, string> = {
                deezer: 'Deezer',
                youtube_music: 'YouTube Music',
                musicbrainz: 'MusicBrainz',
                listenbrainz: 'ListenBrainz',
                listenbrainz_labs: 'ListenBrainz Labs',
                lastfm: 'Last.fm',
              };
              const name =
                displayNames[api.apiName] ||
                api.apiName.charAt(0).toUpperCase() + api.apiName.slice(1);
              return (
                <div key={api.apiName} className='flex items-center gap-2'>
                  <svg
                    className={`h-4 w-4 ${api.isRateLimited ? 'text-red-500' : 'text-green-500'} flex-shrink-0`}
                    fill='currentColor'
                    viewBox='0 0 20 20'
                  >
                    <path
                      fillRule='evenodd'
                      d={
                        api.isRateLimited
                          ? 'M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 9.586 8.707 8.293z'
                          : 'M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z'
                      }
                      clipRule='evenodd'
                    />
                  </svg>
                  <span className='text-sm text-gray-700'>
                    {name}:{' '}
                    <span
                      className={`${api.isRateLimited ? 'text-red-700' : 'text-green-700'} font-medium`}
                    >
                      {api.isRateLimited ? 'Limited' : 'OK'}
                    </span>
                    <span className='text-gray-500 ml-1 text-xs'>
                      ({api.requestCount} req, max {api.maxRequestsPerSecond}
                      /s)
                    </span>
                  </span>
                </div>
              );
            })}

          {/* Task Queue */}
          <div className='flex items-center gap-2'>
            {loading ? (
              <StatusSkeleton />
            ) : data?.queueStatus.totalPendingTasks === 0 ? (
              <>
                <svg
                  className='h-4 w-4 text-gray-400 flex-shrink-0'
                  fill='currentColor'
                  viewBox='0 0 20 20'
                >
                  <path
                    fillRule='evenodd'
                    d='M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z'
                    clipRule='evenodd'
                  />
                </svg>
                <span className='text-sm text-gray-700'>
                  Task Queue: <span className='text-gray-600'>Idle</span>
                </span>
              </>
            ) : (
              <>
                <svg
                  className='h-4 w-4 text-blue-500 animate-spin flex-shrink-0'
                  fill='none'
                  viewBox='0 0 24 24'
                >
                  <circle
                    className='opacity-25'
                    cx='12'
                    cy='12'
                    r='10'
                    stroke='currentColor'
                    strokeWidth='4'
                  />
                  <path
                    className='opacity-75'
                    fill='currentColor'
                    d='M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z'
                  />
                </svg>
                <span className='text-sm text-gray-700'>
                  Task Queue:{' '}
                  <span className='text-blue-700 font-medium'>
                    {data?.queueStatus.totalPendingTasks} pending
                  </span>
                </span>
              </>
            )}
          </div>

          {/* Storage Status */}
          <div className='flex items-center gap-2'>
            {loading ? (
              <StatusSkeleton />
            ) : !data?.systemHealth.storage.isWritable ? (
              <>
                <svg
                  className='h-4 w-4 text-red-500 flex-shrink-0'
                  fill='currentColor'
                  viewBox='0 0 20 20'
                >
                  <path
                    fillRule='evenodd'
                    d='M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z'
                    clipRule='evenodd'
                  />
                </svg>
                <span
                  className='text-sm text-gray-700'
                  title={
                    data?.systemHealth.storage.errorMessage ||
                    'Storage unavailable'
                  }
                >
                  Storage:{' '}
                  <span className='text-red-700 font-medium'>Unavailable</span>
                </span>
              </>
            ) : data?.systemHealth.storage.isCriticallyLow ? (
              <>
                <svg
                  className='h-4 w-4 text-red-500 flex-shrink-0'
                  fill='currentColor'
                  viewBox='0 0 20 20'
                >
                  <path
                    fillRule='evenodd'
                    d='M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z'
                    clipRule='evenodd'
                  />
                </svg>
                <span
                  className='text-sm text-gray-700'
                  title={`${data.systemHealth.storage.availableGb?.toFixed(1)}GB free (${data.systemHealth.storage.usagePercent?.toFixed(0)}% used)`}
                >
                  Storage:{' '}
                  <span className='text-red-700 font-medium'>
                    Critical (
                    {data.systemHealth.storage.availableGb?.toFixed(1)}GB free)
                  </span>
                </span>
              </>
            ) : data?.systemHealth.storage.isLow ? (
              <>
                <svg
                  className='h-4 w-4 text-yellow-500 flex-shrink-0'
                  fill='currentColor'
                  viewBox='0 0 20 20'
                >
                  <path
                    fillRule='evenodd'
                    d='M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z'
                    clipRule='evenodd'
                  />
                </svg>
                <span
                  className='text-sm text-gray-700'
                  title={`${data.systemHealth.storage.availableGb?.toFixed(1)}GB free (${data.systemHealth.storage.usagePercent?.toFixed(0)}% used)`}
                >
                  Storage:{' '}
                  <span className='text-yellow-700 font-medium'>
                    Low ({data.systemHealth.storage.availableGb?.toFixed(1)}GB
                    free)
                  </span>
                </span>
              </>
            ) : (
              <>
                <svg
                  className='h-4 w-4 text-green-500 flex-shrink-0'
                  fill='currentColor'
                  viewBox='0 0 20 20'
                >
                  <path
                    fillRule='evenodd'
                    d='M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z'
                    clipRule='evenodd'
                  />
                </svg>
                <span
                  className='text-sm text-gray-700'
                  title={`${data?.systemHealth.storage.availableGb?.toFixed(1)}GB free (${data?.systemHealth.storage.usagePercent?.toFixed(0)}% used)`}
                >
                  Storage:{' '}
                  <span className='text-green-700 font-medium'>
                    {data?.systemHealth.storage.availableGb?.toFixed(0)}GB free
                  </span>
                </span>
              </>
            )}
          </div>
        </div>
        {/* Spotify Connect Button */}
        <div className='mt-3'>
          <SpotifyConnectButton />
        </div>
      </div>

      <div className='grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4'>
        <Link
          to='/artists'
          search={{}}
          className='block bg-white rounded-lg border border-gray-200 p-5 hover:shadow transition-shadow'
        >
          <div className='text-gray-900 font-semibold'>Artists</div>
          <div className='text-gray-600 text-sm'>Track and sync artists</div>
        </Link>

        <Link
          to='/albums'
          search={{ artistId: undefined }}
          className='block bg-white rounded-lg border border-gray-200 p-5 hover:shadow transition-shadow'
        >
          <div className='text-gray-900 font-semibold'>Albums</div>
          <div className='text-gray-600 text-sm'>Manage wanted/downloaded</div>
        </Link>

        <Link
          to='/songs'
          search={{ artistId: undefined, search: undefined }}
          className='block bg-white rounded-lg border border-gray-200 p-5 hover:shadow transition-shadow'
        >
          <div className='text-gray-900 font-semibold'>Songs</div>
          <div className='text-gray-600 text-sm'>View downloaded tracks</div>
        </Link>

        <Link
          to='/playlists'
          search={{}}
          className='block bg-white rounded-lg border border-gray-200 p-5 hover:shadow transition-shadow'
        >
          <div className='text-gray-900 font-semibold'>Playlists</div>
          <div className='text-gray-600 text-sm'>Manage and sync playlists</div>
        </Link>
      </div>

      <div className='bg-white rounded-lg border border-gray-200 p-5'>
        <div className='text-gray-900 font-semibold mb-2'>Get started</div>
        <ol className='list-decimal pl-5 space-y-1 text-sm text-gray-700'>
          <li>Visit Playlists to add or enable syncing</li>
          <li>Use Download to fetch a Spotify or Deezer link</li>
          <li>Track artists you care about from Artists</li>
        </ol>
      </div>
    </section>
  );
}

export const Route = createFileRoute('/')({
  component: Home,
});
