import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MockedProvider } from "@apollo/client/testing";

import { BulkImportDialog } from "@/features/playlist/BulkImportDialog";
import {
  BulkImportJobDocument,
  BulkImportPlaylistDocument,
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

const PLAYLIST_ID = "10";

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
        createdBy: { __typename: "AccountType", id: "1", displayName: "Owner" },
        members: [],
      },
      playlistContributions: [],
    },
  },
};

describe("BulkImportDialog", () => {
  it("renders URL input and Start import button when open", () => {
    render(
      <MockedProvider mocks={[]}>
        <BulkImportDialog playlistId={PLAYLIST_ID} open onOpenChange={() => {}} />
      </MockedProvider>,
    );

    expect(screen.getByLabelText(/playlist url/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start import/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /start import/i })).toBeDisabled();
  });

  it("enables Start import button only when URL is non-empty", async () => {
    const user = userEvent.setup();

    render(
      <MockedProvider mocks={[]}>
        <BulkImportDialog playlistId={PLAYLIST_ID} open onOpenChange={() => {}} />
      </MockedProvider>,
    );

    const startBtn = screen.getByRole("button", { name: /start import/i });
    expect(startBtn).toBeDisabled();

    await user.type(screen.getByLabelText(/playlist url/i), "https://open.spotify.com/playlist/xyz");
    expect(startBtn).not.toBeDisabled();
  });

  it("shows import-complete summary after polling reaches succeeded", async () => {
    const user = userEvent.setup();

    const mocks = [
      // Initial mutation
      {
        request: {
          query: BulkImportPlaylistDocument,
          variables: { playlistId: PLAYLIST_ID, url: "https://open.spotify.com/playlist/xyz" },
        },
        result: {
          data: {
            bulkImportPlaylist: {
              __typename: "BulkImportJobType",
              id: "99",
              status: "pending",
              sourceUrl: "https://open.spotify.com/playlist/xyz",
              addedCount: 0,
              skippedCount: 0,
              unresolvedCount: 0,
              unresolvedTitles: [],
              error: "",
            },
          },
        },
      },
      // Playlist detail refetch triggered by refetchQueries
      playlistDetailRefetchMock,
      // Poll 1: running
      {
        request: { query: BulkImportJobDocument, variables: { id: "99" } },
        result: {
          data: {
            bulkImportJob: {
              __typename: "BulkImportJobType",
              id: "99",
              status: "running",
              addedCount: 0,
              skippedCount: 0,
              unresolvedCount: 0,
              unresolvedTitles: [],
              error: "",
              finishedAt: null,
            },
          },
        },
      },
      // Poll 2: succeeded
      {
        request: { query: BulkImportJobDocument, variables: { id: "99" } },
        result: {
          data: {
            bulkImportJob: {
              __typename: "BulkImportJobType",
              id: "99",
              status: "succeeded",
              addedCount: 3,
              skippedCount: 1,
              unresolvedCount: 0,
              unresolvedTitles: [],
              error: "",
              finishedAt: "2026-05-19T00:00:00Z",
            },
          },
        },
      },
    ];

    render(
      <MockedProvider mocks={mocks}>
        <BulkImportDialog playlistId={PLAYLIST_ID} open onOpenChange={() => {}} />
      </MockedProvider>,
    );

    await user.type(
      screen.getByLabelText(/playlist url/i),
      "https://open.spotify.com/playlist/xyz",
    );
    await user.click(screen.getByRole("button", { name: /start import/i }));

    // Wait for the in-progress state to appear
    await waitFor(() => {
      expect(screen.getByText(/queued for import|importing tracks/i)).toBeInTheDocument();
    });

    // Wait for the terminal-state UI (Apollo polls BulkImportJobDocument)
    await waitFor(
      () => expect(screen.getByText(/import complete/i)).toBeInTheDocument(),
      { timeout: 10000 },
    );

    expect(screen.getByText(/Added: 3/)).toBeInTheDocument();
    expect(screen.getByText(/Already present: 1/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /done/i })).toBeInTheDocument();
  }, 15000);

  it("shows error state when import job fails", async () => {
    const user = userEvent.setup();

    const mocks = [
      {
        request: {
          query: BulkImportPlaylistDocument,
          variables: { playlistId: PLAYLIST_ID, url: "https://open.spotify.com/playlist/bad" },
        },
        result: {
          data: {
            bulkImportPlaylist: {
              __typename: "BulkImportJobType",
              id: "88",
              status: "pending",
              sourceUrl: "https://open.spotify.com/playlist/bad",
              addedCount: 0,
              skippedCount: 0,
              unresolvedCount: 0,
              unresolvedTitles: [],
              error: "",
            },
          },
        },
      },
      playlistDetailRefetchMock,
      {
        request: { query: BulkImportJobDocument, variables: { id: "88" } },
        result: {
          data: {
            bulkImportJob: {
              __typename: "BulkImportJobType",
              id: "88",
              status: "failed",
              addedCount: 0,
              skippedCount: 0,
              unresolvedCount: 0,
              unresolvedTitles: [],
              error: "Could not resolve playlist URL.",
              finishedAt: "2026-05-19T00:01:00Z",
            },
          },
        },
      },
    ];

    render(
      <MockedProvider mocks={mocks}>
        <BulkImportDialog playlistId={PLAYLIST_ID} open onOpenChange={() => {}} />
      </MockedProvider>,
    );

    await user.type(
      screen.getByLabelText(/playlist url/i),
      "https://open.spotify.com/playlist/bad",
    );
    await user.click(screen.getByRole("button", { name: /start import/i }));

    await waitFor(
      () => expect(screen.getByText(/import failed/i)).toBeInTheDocument(),
      { timeout: 10000 },
    );

    expect(screen.getByText(/could not resolve playlist url/i)).toBeInTheDocument();
  }, 15000);
});
