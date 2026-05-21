import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MockedProvider } from "@apollo/client/testing";

import { CreateExportDialog } from "@/features/playlist/CreateExportDialog";
import { ExportPage } from "@/routes/exports.$id";
import {
  CreateExportDocument,
  ExportDocument,
  ExportToSpotifyDocument,
} from "@/types/generated/graphql";

const mockNavigate = vi.fn();

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
    useRouter: () => ({ navigate: mockNavigate }),
    createFileRoute: () => () => ({ options: {}, useParams: () => ({ id: "5" }) }),
  };
});

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

const mockAccount = {
  id: "1",
  displayName: "Owner",
  externalServices: [] as Array<{ service: string; serviceUserId: string; linkedAt: string }>,
};

vi.mock("@/lib/auth", () => ({
  useMe: () => ({
    account: mockAccount,
    loading: false,
  }),
}));

const PLAYLIST_ID = "7";
const SNAPSHOT_ID = "5";

describe("CreateExportDialog", () => {
  it("clicking Create export calls createExport mutation and navigates to snapshot page", async () => {
    const user = userEvent.setup();

    const createExportMock = {
      request: {
        query: CreateExportDocument,
        variables: {
          playlistId: PLAYLIST_ID,
          options: { excludeMyDownvotes: false },
        },
      },
      result: {
        data: {
          createExport: {
            __typename: "ExportSnapshotType",
            id: SNAPSHOT_ID,
            warningMessage: "",
          },
        },
      },
    };

    render(
      <MockedProvider mocks={[createExportMock]}>
        <CreateExportDialog playlistId={PLAYLIST_ID} open onOpenChange={vi.fn()} />
      </MockedProvider>,
    );

    await user.click(screen.getByRole("button", { name: /create export/i }));

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith({
        to: "/exports/$id",
        params: { id: SNAPSHOT_ID },
      });
    });
  });
});

describe("ExportPage", () => {
  const exportMock = {
    request: {
      query: ExportDocument,
      variables: { id: SNAPSHOT_ID },
    },
    result: {
      data: {
        export: {
          __typename: "ExportSnapshotType",
          id: SNAPSHOT_ID,
          createdAt: "2026-05-19T12:00:00Z",
          parameters: '{"exclude_my_downvotes": false}',
          rngSeed: "1234567890",
          warningMessage: "",
          requestedBy: {
            __typename: "AccountType",
            id: "1",
            displayName: "Owner",
          },
          playlist: {
            __typename: "PlaylistType",
            id: "7",
            name: "Friday Mix",
            description: "A chill set",
          },
          tracks: [
            {
              __typename: "ExportSnapshotTrackType",
              id: "101",
              position: 0,
              inclusionReason: "guaranteed",
              rollProbability: 1.0,
              song: {
                __typename: "SongRef",
                id: "500",
                title: "Bohemian Rhapsody",
                artist: "Queen",
                isrc: "GBUM71029604",
              },
            },
            {
              __typename: "ExportSnapshotTrackType",
              id: "102",
              position: 1,
              inclusionReason: "rolled",
              rollProbability: 0.72,
              song: {
                __typename: "SongRef",
                id: "501",
                title: "Let It Be",
                artist: "The Beatles",
                isrc: "GBAYE6800013",
              },
            },
          ],
        },
      },
    },
  };

  it("renders both tracks in position order", async () => {
    render(
      <MockedProvider mocks={[exportMock]}>
        <ExportPage />
      </MockedProvider>,
    );

    await waitFor(() => {
      expect(screen.getByText("Bohemian Rhapsody")).toBeInTheDocument();
    });

    // Both tracks present
    expect(screen.getByText("Bohemian Rhapsody")).toBeInTheDocument();
    expect(screen.getByText("Let It Be")).toBeInTheDocument();

    // Position labels (1-indexed)
    expect(screen.getByText("1.")).toBeInTheDocument();
    expect(screen.getByText("2.")).toBeInTheDocument();
  });

  it("shows 'Link Spotify' when Spotify is not linked", async () => {
    render(
      <MockedProvider mocks={[exportMock]}>
        <ExportPage />
      </MockedProvider>,
    );

    await screen.findByText("Bohemian Rhapsody");
    expect(screen.getByRole("button", { name: /link spotify/i })).toBeInTheDocument();
  });

  it("calls exportToSpotify mutation when 'Export to Spotify' is clicked", async () => {
    const user = userEvent.setup();
    const exportResultFn = vi.fn(() => ({
      data: {
        exportToSpotify: {
          __typename: "SpotifyExportResultType",
          spotifyPlaylistUrl: "https://open.spotify.com/playlist/abc",
          addedCount: 2,
          skippedCount: 0,
          skippedTitles: [],
          createdNew: true,
        },
      },
    }));

    const spotifyMock = {
      request: {
        query: ExportToSpotifyDocument,
        // The mutation document declares `$forceRecreate: Boolean! = false`,
        // so Apollo resolves the default and includes the variable in the
        // request. playlistName (nullable) is omitted unless the caller
        // provides it, so don't include it in the mock either.
        variables: {
          snapshotId: SNAPSHOT_ID,
          forceRecreate: false,
        },
      },
      result: exportResultFn,
    };

    // Temporarily set externalServices to include spotify
    mockAccount.externalServices = [
      { service: "spotify", serviceUserId: "alice42", linkedAt: "2026-05-19T00:00:00Z" },
    ];

    render(
      <MockedProvider mocks={[exportMock, spotifyMock]}>
        <ExportPage />
      </MockedProvider>,
    );

    await screen.findByText("Bohemian Rhapsody");
    await user.click(screen.getByRole("button", { name: /export to spotify/i }));

    await waitFor(() => expect(exportResultFn).toHaveBeenCalled());

    // Restore for isolation
    mockAccount.externalServices = [];
  });
});
