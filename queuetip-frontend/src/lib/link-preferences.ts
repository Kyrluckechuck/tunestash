import * as React from "react";

export const OPEN_SPOTIFY_LINKS_IN_APP_KEY = "queuetip.openSpotifyLinksInApp";

function readOpenSpotifyLinksInApp(): boolean {
  try {
    return window.localStorage.getItem(OPEN_SPOTIFY_LINKS_IN_APP_KEY) === "true";
  } catch {
    return false;
  }
}

export function useOpenSpotifyLinksInApp(): [boolean, (enabled: boolean) => void] {
  const [enabled, setEnabled] = React.useState(readOpenSpotifyLinksInApp);

  const update = React.useCallback((value: boolean) => {
    setEnabled(value);
    try {
      window.localStorage.setItem(OPEN_SPOTIFY_LINKS_IN_APP_KEY, String(value));
    } catch {
      // Browsers may deny storage while still allowing this page-level preference.
    }
  }, []);

  return [enabled, update];
}
