import { gql } from '@apollo/client';

export const DOWNLOAD_URL = gql`
  mutation DownloadUrl($url: String!, $autoTrackTier: Int) {
    downloadUrl(url: $url, autoTrackTier: $autoTrackTier) {
      success
      message
      artist {
        id
        name
        gid
        trackingTier
        addedAt
        lastSynced
      }
      album {
        id
        name
        spotifyGid
        deezerId
        totalTracks
        wanted
        downloaded
        albumType
        albumGroup
        artist
        artistId
      }
      playlist {
        id
        name
        url
        enabled
        autoTrackTier
        lastSyncedAt
      }
    }
  }
`;

export const CREATE_PLAYLIST = gql`
  mutation CreatePlaylistFromDownload(
    $name: String!
    $url: String!
    $autoTrackTier: Int
  ) {
    createPlaylist(name: $name, url: $url, autoTrackTier: $autoTrackTier) {
      id
      name
      url
      enabled
      autoTrackTier
      lastSyncedAt
    }
  }
`;

export const UPDATE_PLAYLIST = gql`
  mutation UpdatePlaylist(
    $playlistId: Int!
    $name: String!
    $url: String!
    $autoTrackTier: Int
  ) {
    updatePlaylist(
      playlistId: $playlistId
      name: $name
      url: $url
      autoTrackTier: $autoTrackTier
    ) {
      success
      message
    }
  }
`;
