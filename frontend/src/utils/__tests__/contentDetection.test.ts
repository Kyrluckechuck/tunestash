import { describe, it, expect } from 'vitest';
import { detectContentType, extractPlaylistName } from '../contentDetection';

describe('detectContentType', () => {
  it('detects Spotify playlist from web URL', () => {
    const result = detectContentType(
      'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M'
    );
    expect(result.type).toBe('playlist');
    expect(result.label).toBe('Playlist detected');
  });

  it('detects Spotify playlist from URI', () => {
    const result = detectContentType('spotify:playlist:37i9dQZF1DXcBWIGoYBM5M');
    expect(result.type).toBe('playlist');
  });

  it('detects Deezer playlist', () => {
    const result = detectContentType(
      'https://www.deezer.com/playlist/1234567890'
    );
    expect(result.type).toBe('playlist');
    expect(result.label).toBe('Deezer Playlist detected');
  });

  it('detects Spotify artist', () => {
    const result = detectContentType(
      'https://open.spotify.com/artist/4Z8W4fKeB5YxbusRsdQVPb'
    );
    expect(result.type).toBe('artist');
    expect(result.label).toBe('Artist detected');
  });

  it('detects Spotify album', () => {
    const result = detectContentType(
      'https://open.spotify.com/album/6dVIqQ8qmQ5GBnJ9shOYGE'
    );
    expect(result.type).toBe('album');
  });

  it('detects Spotify track', () => {
    const result = detectContentType(
      'https://open.spotify.com/track/11dFghVXANMlKmJXsNCbNl'
    );
    expect(result.type).toBe('track');
  });

  it('detects Deezer album with provider label', () => {
    const result = detectContentType('https://www.deezer.com/album/12345');
    expect(result.type).toBe('album');
    expect(result.label).toBe('Deezer Album detected');
  });

  it('returns unknown for empty string', () => {
    const result = detectContentType('');
    expect(result.type).toBe('unknown');
    expect(result.icon).toBe('💡');
  });

  it('returns unknown for unrecognized Spotify URL', () => {
    const result = detectContentType('https://open.spotify.com/show/abc123');
    expect(result.type).toBe('unknown');
    expect(result.icon).toBe('❌');
  });

  it('returns unknown for generic URL', () => {
    const result = detectContentType('https://example.com/music');
    expect(result.type).toBe('unknown');
    expect(result.icon).toBe('❓');
  });

  it('is case insensitive', () => {
    const result = detectContentType(
      'HTTPS://OPEN.SPOTIFY.COM/PLAYLIST/ABC123'
    );
    expect(result.type).toBe('playlist');
  });

  it('trims whitespace', () => {
    const result = detectContentType('  https://open.spotify.com/track/abc  ');
    expect(result.type).toBe('track');
  });
});

describe('extractPlaylistName', () => {
  it('extracts playlist ID from URL', () => {
    const name = extractPlaylistName(
      'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M'
    );
    expect(name).toBe('Playlist 37i9dQZF1DXcBWIGoYBM5M');
  });

  it('returns default name for non-playlist URL', () => {
    const name = extractPlaylistName('https://example.com/something');
    expect(name).toBe('Downloaded Playlist');
  });
});
