import type { ContentType } from '../types/shared';

export interface DetectedContent {
  type: ContentType;
  icon: string;
  label: string;
  buttonText: string;
}

/**
 * Detects the type of music content from a Spotify or Deezer URL
 * @param url - URL to analyze
 * @returns Detected content information including type, icon, and labels
 */
export function detectSpotifyContentType(url: string): DetectedContent {
  const trimmedUrl = url.trim().toLowerCase();

  if (!trimmedUrl) {
    return {
      type: 'unknown',
      icon: '💡',
      label: 'Enter a Spotify or Deezer URL to detect content type',
      buttonText: 'Download',
    };
  }

  const isDeezer = trimmedUrl.includes('deezer.com');
  const providerLabel = isDeezer ? 'Deezer' : '';

  // Check for playlist
  if (trimmedUrl.includes('/playlist/') || trimmedUrl.includes('playlist:')) {
    return {
      type: 'playlist',
      icon: '📜',
      label: `${providerLabel} Playlist detected`.trim(),
      buttonText: 'Download Playlist',
    };
  }

  // Check for artist
  if (trimmedUrl.includes('/artist/') || trimmedUrl.includes('artist:')) {
    return {
      type: 'artist',
      icon: '🎤',
      label: `${providerLabel} Artist detected`.trim(),
      buttonText: 'Download Artist',
    };
  }

  // Check for album
  if (trimmedUrl.includes('/album/') || trimmedUrl.includes('album:')) {
    return {
      type: 'album',
      icon: '💿',
      label: `${providerLabel} Album detected`.trim(),
      buttonText: 'Download Album',
    };
  }

  // Check for track/song
  if (trimmedUrl.includes('/track/') || trimmedUrl.includes('track:')) {
    return {
      type: 'track',
      icon: '🎵',
      label: `${providerLabel} Track detected`.trim(),
      buttonText: 'Download Track',
    };
  }

  // If URL contains spotify or deezer but not recognized
  if (trimmedUrl.includes('spotify') || trimmedUrl.includes('deezer')) {
    return {
      type: 'unknown',
      icon: '❌',
      label: 'URL not recognized - please check format',
      buttonText: 'Download',
    };
  }

  // Generic URL
  return {
    type: 'unknown',
    icon: '❓',
    label: 'Unknown URL format',
    buttonText: 'Download',
  };
}

/**
 * Extracts a playlist name from a Spotify URL
 * @param url - Spotify playlist URL
 * @returns Extracted or default playlist name
 */
export function extractPlaylistName(url: string): string {
  // Try to extract a reasonable name from the URL
  const match = url.match(/playlist\/([a-zA-Z0-9]+)/);
  if (match) {
    return `Playlist ${match[1]}`;
  }
  return 'Downloaded Playlist';
}
