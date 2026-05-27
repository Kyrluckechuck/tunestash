import { describe, expect, it } from "vitest";

import { classifyContentInput } from "@/features/playlist/content-input";

describe("classifyContentInput", () => {
  it.each([
    ["spotify:track:abc", { kind: "track", provider: "spotify" }],
    [
      "https://open.spotify.com/album/abc",
      { kind: "collection", provider: "spotify", resource: "album" },
    ],
    ["https://open.spotify.com/intl-en/track/abc", { kind: "track", provider: "spotify" }],
    [
      "https://open.spotify.com/intl-en/album/abc",
      { kind: "collection", provider: "spotify", resource: "album" },
    ],
    ["https://music.apple.com/us/album/record/123?i=456", { kind: "track", provider: "apple" }],
    [
      "https://music.apple.com/us/playlist/mix/pl.abc",
      { kind: "collection", provider: "apple", resource: "playlist" },
    ],
    [
      "https://www.deezer.com/album/42",
      { kind: "collection", provider: "deezer", resource: "album" },
    ],
    ["https://www.deezer.com/track/42", { kind: "track", provider: "deezer" }],
  ])("recognizes %s", (input, expected) => {
    expect(classifyContentInput(input)).toEqual(expected);
  });

  it("treats ordinary text as search input and arbitrary URLs as unsupported", () => {
    expect(classifyContentInput("Queen Bohemian Rhapsody")).toEqual({ kind: "search" });
    expect(classifyContentInput("https://example.com/track/1")).toEqual({
      kind: "unsupported-url",
    });
  });
});
