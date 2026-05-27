export type ContentInput =
  | { kind: "search" }
  | { kind: "track"; provider: "spotify" | "apple" | "deezer" }
  | {
      kind: "collection";
      provider: "spotify" | "apple" | "deezer";
      resource: "album" | "playlist";
    }
  | { kind: "unsupported-url" };

function asContent(provider: "spotify" | "apple" | "deezer", resource: string): ContentInput {
  if (resource === "track" || resource === "song") return { kind: "track", provider };
  if (resource === "album" || resource === "playlist") {
    return { kind: "collection", provider, resource };
  }
  return { kind: "unsupported-url" };
}

export function classifyContentInput(value: string): ContentInput {
  const raw = value.trim();
  if (!raw) return { kind: "search" };

  const spotifyUri = raw.match(/^spotify:(track|album|playlist):[a-zA-Z0-9]+$/i);
  if (spotifyUri) return asContent("spotify", spotifyUri[1].toLowerCase());
  if (/^[a-z]+:/i.test(raw) && !/^https?:\/\//i.test(raw)) {
    return { kind: "unsupported-url" };
  }
  if (!/^https?:\/\//i.test(raw)) return { kind: "search" };

  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return { kind: "unsupported-url" };
  }
  const host = url.hostname.toLowerCase();
  const path = url.pathname.toLowerCase();
  if (host === "open.spotify.com") {
    const match = path.match(/\/(?:intl-[^/]+\/)?(track|album|playlist)\//);
    return match ? asContent("spotify", match[1]) : { kind: "unsupported-url" };
  }
  if (host === "music.apple.com") {
    if (/\/album\//.test(path) && url.searchParams.has("i")) {
      return { kind: "track", provider: "apple" };
    }
    const match = path.match(/\/(song|album|playlist)\//);
    return match ? asContent("apple", match[1]) : { kind: "unsupported-url" };
  }
  if (host === "www.deezer.com" || host === "deezer.com") {
    const match = path.match(/\/(?:[a-z]{2}\/)?(track|album|playlist)\//);
    return match ? asContent("deezer", match[1]) : { kind: "unsupported-url" };
  }
  return { kind: "unsupported-url" };
}
