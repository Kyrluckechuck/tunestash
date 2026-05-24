import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PlatformLinks } from "@/features/playlist/PlatformLinks";

describe("PlatformLinks", () => {
  it("opens direct URI and URL values directly", () => {
    render(
      <PlatformLinks
        title="Bohemian Rhapsody"
        artist="Queen"
        spotifyGid="spotify:track:abc123"
        deezerId="https://www.deezer.com/track/456"
      />,
    );

    expect(screen.getByLabelText("Open on Spotify")).toHaveAttribute(
      "href",
      "https://open.spotify.com/track/abc123",
    );
    expect(screen.getByLabelText("Open on Deezer")).toHaveAttribute(
      "href",
      "https://www.deezer.com/track/456",
    );
  });

  it("falls back to search when direct platform IDs are missing", () => {
    render(<PlatformLinks title="Bohemian Rhapsody" artist="Queen" />);

    expect(screen.getByLabelText("Search on Spotify")).toHaveAttribute(
      "href",
      "https://open.spotify.com/search/Bohemian%20Rhapsody%20Queen",
    );
    expect(screen.getByLabelText("Search on Deezer")).toHaveAttribute(
      "href",
      "https://www.deezer.com/search/Bohemian%20Rhapsody%20Queen",
    );
    expect(screen.getByLabelText("Search on Apple Music")).toHaveAttribute(
      "href",
      "https://music.apple.com/search?term=Bohemian%20Rhapsody%20Queen",
    );
  });
});
