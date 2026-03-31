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
          className={`inline-flex items-center ${padding} rounded ${textSize} font-medium bg-purple-50 dark:bg-purple-950 text-purple-600 dark:text-purple-400 hover:bg-purple-100 dark:hover:bg-purple-900 transition-colors`}
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
          className={`inline-flex items-center ${padding} rounded ${textSize} font-medium bg-green-50 dark:bg-green-950 text-green-600 dark:text-green-400 hover:bg-green-100 dark:hover:bg-green-900 transition-colors`}
          title='Open on Spotify'
        >
          Spotify
        </a>
      )}
    </span>
  );
}
