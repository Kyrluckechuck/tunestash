import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MockedProvider } from "@apollo/client/testing";

import { ContributeDialog } from "@/features/playlist/ContributeDialog";
import {
  BulkImportJobDocument,
  BulkImportPlaylistDocument,
  ContributeFromLinkDocument,
  PlaylistDetailDocument,
} from "@/types/generated/graphql";

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    Link: ({
      children,
      ...props
    }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { children?: React.ReactNode }) => (
      <a {...props}>{children}</a>
    ),
    Navigate: () => <div data-testid="navigate" />,
    useRouter: () => ({ navigate: vi.fn() }),
    createFileRoute: () => () => ({ options: {}, useParams: () => ({ id: "10" }) }),
  };
});

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const PLAYLIST_ID = "42";

const playlistDetailRefetchMock = {
  request: { query: PlaylistDetailDocument, variables: { id: PLAYLIST_ID } },
  result: {
    data: {
      playlist: {
        __typename: "PlaylistType",
        id: PLAYLIST_ID,
        name: "Test Playlist",
        description: "",
        inviteToken: "tok-xyz",
        engineSettings: {
          __typename: "EngineSettings",
          minSize: 1,
          maxSize: null,
          tHigh: 3,
          tLow: 3,
          base: 0.85,
          pFloor: 0.15,
        },
        createdBy: { __typename: "AccountType", id: "1", displayName: "Owner" },
        members: [],
      },
      playlistContributions: [],
    },
  },
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function renderDialog(mocks: any[], onOpenChange = vi.fn()) {
  return {
    onOpenChange,
    ...render(
      <MockedProvider mocks={mocks}>
        <ContributeDialog playlistId={PLAYLIST_ID} open={true} onOpenChange={onOpenChange} />
      </MockedProvider>
    ),
  };
}

describe("ContributeDialog", () => {
  it("uses one field for search terms or pasted links", () => {
    renderDialog([]);

    expect(screen.getByLabelText(/search or paste a link/i)).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: /paste link/i })).not.toBeInTheDocument();
  });

  it("adds a recognized track link and closes after success", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    const contributeResult = {
      data: {
        contributeFromLink: {
          __typename: "ContributionResult",
          alreadyPresent: false,
          contribution: {
            __typename: "ContributionType",
            id: "99",
            netScore: 1,
            duplicateKind: "none",
            duplicateWithTitles: [],
            song: {
              __typename: "SongRef",
              id: "500",
              title: "Bohemian Rhapsody",
              artist: "Queen",
              isrc: "GBUM71029604",
              spotifyGid: "abc123",
              deezerId: null,
              durationSeconds: 354,
            },
            contributedBy: { __typename: "AccountType", id: "1", displayName: "Owner" },
            votes: [],
          },
        },
      },
    };

    const mocks = [
      {
        request: {
          query: ContributeFromLinkDocument,
          variables: { playlistId: PLAYLIST_ID, url: "https://open.spotify.com/track/abc" },
        },
        result: contributeResult,
      },
      playlistDetailRefetchMock,
    ];

    renderDialog(mocks, onOpenChange);

    const urlInput = screen.getByLabelText(/search or paste a link/i);
    await user.type(urlInput, "https://open.spotify.com/track/abc");

    await user.click(screen.getByRole("button", { name: /add track/i }));

    // onOpenChange(false) is called when the dialog closes after success
    await waitFor(() => {
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });

  it("offers an upvote when the recognized track is already present", async () => {
    const user = userEvent.setup();

    const contributeResult = {
      data: {
        contributeFromLink: {
          __typename: "ContributionResult",
          alreadyPresent: true,
          contribution: {
            __typename: "ContributionType",
            id: "77",
            netScore: 3,
            duplicateKind: "none",
            duplicateWithTitles: [],
            song: {
              __typename: "SongRef",
              id: "501",
              title: "Let It Be",
              artist: "The Beatles",
              isrc: "GBAYE6800013",
              spotifyGid: "xyz987",
              deezerId: null,
              durationSeconds: 243,
            },
            contributedBy: { __typename: "AccountType", id: "2", displayName: "Alice" },
            votes: [],
          },
        },
      },
    };

    const mocks = [
      {
        request: {
          query: ContributeFromLinkDocument,
          variables: { playlistId: PLAYLIST_ID, url: "https://open.spotify.com/track/xyz" },
        },
        result: contributeResult,
      },
      playlistDetailRefetchMock,
    ];

    renderDialog(mocks);

    const urlInput = screen.getByLabelText(/search or paste a link/i);
    await user.type(urlInput, "https://open.spotify.com/track/xyz");

    await user.click(screen.getByRole("button", { name: /add track/i }));

    await waitFor(() => {
      expect(screen.getByText(/already in this playlist/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /upvote/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /dismiss/i })).toBeInTheDocument();
    });
  });

  it("imports a recognized collection and displays completion summary", async () => {
    const user = userEvent.setup();
    const url = "https://open.spotify.com/album/abc";
    const mocks = [
      {
        request: {
          query: BulkImportPlaylistDocument,
          variables: { playlistId: PLAYLIST_ID, url },
        },
        result: {
          data: {
            bulkImportPlaylist: {
              __typename: "BulkImportJobType",
              id: "88",
              status: "pending",
              sourceUrl: url,
              totalTracks: null,
              addedCount: 0,
              skippedCount: 0,
              unresolvedCount: 0,
              unresolvedTitles: [],
              error: "",
            },
          },
        },
      },
      {
        request: { query: BulkImportJobDocument, variables: { id: "88" } },
        result: {
          data: {
            bulkImportJob: {
              __typename: "BulkImportJobType",
              id: "88",
              status: "succeeded",
              totalTracks: 3,
              addedCount: 2,
              skippedCount: 1,
              unresolvedCount: 0,
              unresolvedTitles: [],
              error: "",
              finishedAt: "2026-05-24T00:00:00Z",
            },
          },
        },
      },
      playlistDetailRefetchMock,
    ];

    renderDialog(mocks);
    await user.type(screen.getByLabelText(/search or paste a link/i), url);
    await user.click(screen.getByRole("button", { name: /import album/i }));

    await waitFor(() => expect(screen.getByText(/import complete/i)).toBeInTheDocument());
    expect(screen.getByText(/Added: 2/)).toBeInTheDocument();
    expect(screen.getByText(/Already present: 1/)).toBeInTheDocument();
  });

  it("does not search an unsupported pasted URL", async () => {
    const user = userEvent.setup();
    renderDialog([]);

    await user.type(screen.getByLabelText(/search or paste a link/i), "https://example.com/song/1");

    expect(screen.getByText(/unsupported link/i)).toBeInTheDocument();
  });
});
