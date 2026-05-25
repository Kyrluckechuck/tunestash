import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { PlatformLinks } from "@/features/playlist/PlatformLinks";

describe("PlatformLinks", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("uses web destinations by default for direct stored values", () => {
    render(
      <PlatformLinks
        title="Bohemian Rhapsody"
        artist="Queen"
        spotifyGid="spotify:track:abc123"
        deezerId="https://www.deezer.com/track/456"
      />
    );

    expect(screen.getByLabelText("Open on Spotify")).toHaveAttribute(
      "href",
      "https://open.spotify.com/track/abc123"
    );
    expect(screen.getByLabelText("Open on Spotify")).toHaveAttribute("target", "_blank");
    expect(screen.getByLabelText("Open on Deezer")).toHaveAttribute(
      "href",
      "https://www.deezer.com/track/456"
    );
  });

  it("uses a Spotify protocol link for a direct URI when app links are enabled", () => {
    window.localStorage.setItem("queuetip.openSpotifyLinksInApp", "true");

    render(
      <PlatformLinks title="Bohemian Rhapsody" artist="Queen" spotifyGid="spotify:track:abc123" />
    );

    expect(screen.getByLabelText("Open on Spotify")).toHaveAttribute(
      "href",
      "spotify:track:abc123"
    );
    expect(screen.getByLabelText("Open on Spotify")).not.toHaveAttribute("target");
  });

  it("normalizes a Spotify web track link to a protocol link in app mode", () => {
    window.localStorage.setItem("queuetip.openSpotifyLinksInApp", "true");

    render(
      <PlatformLinks
        title="Bohemian Rhapsody"
        artist="Queen"
        spotifyGid="https://open.spotify.com/track/abc123?si=from-share"
      />
    );

    expect(screen.getByLabelText("Open on Spotify")).toHaveAttribute(
      "href",
      "spotify:track:abc123"
    );
  });

  it("falls back to web search for every platform when direct IDs are missing", () => {
    window.localStorage.setItem("queuetip.openSpotifyLinksInApp", "true");

    render(<PlatformLinks title="Bohemian Rhapsody" artist="Queen" />);

    expect(screen.getByLabelText("Search on Spotify")).toHaveAttribute(
      "href",
      "https://open.spotify.com/search/Bohemian%20Rhapsody%20Queen"
    );
    expect(screen.getByLabelText("Search on Spotify")).toHaveAttribute("target", "_blank");
    expect(screen.getByLabelText("Search on Deezer")).toHaveAttribute(
      "href",
      "https://www.deezer.com/search/Bohemian%20Rhapsody%20Queen"
    );
    expect(screen.getByLabelText("Search on Apple Music")).toHaveAttribute(
      "href",
      "https://music.apple.com/search?term=Bohemian%20Rhapsody%20Queen"
    );
  });
});
