import { render, screen } from '@testing-library/react';
import { useMutation, useQuery } from '@apollo/client/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SpotifyConnectButton } from '../SpotifyConnectButton';

vi.mock('@apollo/client/react', () => ({
  useQuery: vi.fn(),
  useMutation: vi.fn(),
}));

describe('SpotifyConnectButton', () => {
  beforeEach(() => {
    vi.mocked(useMutation).mockReturnValue([
      vi.fn(),
      {
        loading: false,
        error: undefined,
        data: undefined,
        called: false,
        client: {},
      },
    ] as never);
  });

  it('shows reconnect action when stored Spotify auth has expired', () => {
    vi.mocked(useQuery).mockReturnValue({
      loading: false,
      refetch: vi.fn(),
      data: {
        systemHealth: {
          authentication: {
            spotifyAuthMode: 'user-authenticated',
            spotifyTokenValid: false,
            spotifyTokenExpired: true,
          },
        },
      },
    } as never);

    render(<SpotifyConnectButton />);

    expect(
      screen.getByRole('button', { name: /connect spotify/i })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /disconnect/i })
    ).not.toBeInTheDocument();
  });
});
