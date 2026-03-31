interface ProviderBadgesProps {
  deezerId?: string | null;
  spotifyId?: string | null;
  deezerUrl?: string;
  spotifyUrl?: string;
  size?: 'sm' | 'xs';
}

export function ProviderBadges({
  deezerId,
  spotifyId,
  deezerUrl,
  spotifyUrl,
  size = 'xs',
}: ProviderBadgesProps) {
  const textSize = size === 'sm' ? 'text-xs' : 'text-[10px]';
  const padding = size === 'sm' ? 'px-2 py-0.5' : 'px-1.5 py-0.5';

  return (
    <span className='inline-flex items-center gap-1'>
      {deezerId && deezerUrl && (
        <a
          href={deezerUrl}
          target='_blank'
          rel='noopener noreferrer'
          className={`inline-flex items-center ${padding} rounded ${textSize} font-medium bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300 hover:bg-purple-200 dark:hover:bg-purple-900/50 transition-colors`}
          title='Open on Deezer'
        >
          Deezer
        </a>
      )}
      {spotifyId && spotifyUrl && (
        <a
          href={spotifyUrl}
          target='_blank'
          rel='noopener noreferrer'
          className={`inline-flex items-center ${padding} rounded ${textSize} font-medium bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300 hover:bg-green-200 dark:hover:bg-green-900/50 transition-colors`}
          title='Open on Spotify'
        >
          Spotify
        </a>
      )}
    </span>
  );
}
