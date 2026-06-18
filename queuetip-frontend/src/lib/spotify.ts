export const EXPIRED_SPOTIFY_SERVICE_USER_ID = "__spotify_auth_expired__";

export function isExpiredSpotifyLink(
  link: { serviceUserId: string } | null | undefined
): boolean {
  return link?.serviceUserId === EXPIRED_SPOTIFY_SERVICE_USER_ID;
}
