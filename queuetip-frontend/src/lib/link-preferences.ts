import * as React from "react";

export const OPEN_SPOTIFY_LINKS_IN_APP_KEY = "queuetip.openSpotifyLinksInApp";
export const OPEN_APPLE_LINKS_IN_APP_KEY = "queuetip.openAppleLinksInApp";
export const OPEN_DEEZER_LINKS_IN_APP_KEY = "queuetip.openDeezerLinksInApp";

function readOpenSpotifyLinksInApp(): boolean {
  try {
    return window.localStorage.getItem(OPEN_SPOTIFY_LINKS_IN_APP_KEY) === "true";
  } catch {
    return false;
  }
}

export function useOpenSpotifyLinksInApp(): [boolean, (enabled: boolean) => void] {
  const [enabled, setEnabled] = React.useState(readOpenSpotifyLinksInApp);
  return useStoredPreference(OPEN_SPOTIFY_LINKS_IN_APP_KEY, enabled, setEnabled);
}

function readOpenAppleLinksInApp(): boolean {
  try {
    return window.localStorage.getItem(OPEN_APPLE_LINKS_IN_APP_KEY) === "true";
  } catch {
    return false;
  }
}

export function useOpenAppleLinksInApp(): [boolean, (enabled: boolean) => void] {
  const [enabled, setEnabled] = React.useState(readOpenAppleLinksInApp);
  return useStoredPreference(OPEN_APPLE_LINKS_IN_APP_KEY, enabled, setEnabled);
}

function readOpenDeezerLinksInApp(): boolean {
  try {
    return window.localStorage.getItem(OPEN_DEEZER_LINKS_IN_APP_KEY) === "true";
  } catch {
    return false;
  }
}

export function useOpenDeezerLinksInApp(): [boolean, (enabled: boolean) => void] {
  const [enabled, setEnabled] = React.useState(readOpenDeezerLinksInApp);
  return useStoredPreference(OPEN_DEEZER_LINKS_IN_APP_KEY, enabled, setEnabled);
}

function useStoredPreference(
  key: string,
  enabled: boolean,
  setEnabled: React.Dispatch<React.SetStateAction<boolean>>
): [boolean, (enabled: boolean) => void] {
  const update = React.useCallback(
    (value: boolean) => {
      setEnabled(value);
      try {
        window.localStorage.setItem(key, String(value));
      } catch {
        // Browsers may deny storage while still allowing this page-level preference.
      }
    },
    [key, setEnabled]
  );

  return [enabled, update];
}
