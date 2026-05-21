import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MockedProvider } from "@apollo/client/testing";

import { ContributeDialog } from "@/features/playlist/ContributeDialog";
import {
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
        <ContributeDialog
          playlistId={PLAYLIST_ID}
          open={true}
          onOpenChange={onOpenChange}
        />
      </MockedProvider>,
    ),
  };
}

describe("ContributeDialog", () => {
  it("alreadyPresent: false — paste link add closes dialog", async () => {
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
            song: {
              __typename: "SongRef",
              id: "500",
              title: "Bohemian Rhapsody",
              artist: "Queen",
              isrc: "GBUM71029604",
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

    // Switch to the Paste link tab
    await user.click(screen.getByRole("tab", { name: /paste link/i }));

    // Fill in the URL field
    const urlInput = screen.getByPlaceholderText(/open\.spotify/i);
    await user.type(urlInput, "https://open.spotify.com/track/abc");

    // Click Add
    await user.click(screen.getByRole("button", { name: /^add$/i }));

    // onOpenChange(false) is called when the dialog closes after success
    await waitFor(() => {
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
  });

  it("alreadyPresent: true — paste link add shows upvote confirmation", async () => {
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
            song: {
              __typename: "SongRef",
              id: "501",
              title: "Let It Be",
              artist: "The Beatles",
              isrc: "GBAYE6800013",
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

    await user.click(screen.getByRole("tab", { name: /paste link/i }));

    const urlInput = screen.getByPlaceholderText(/open\.spotify/i);
    await user.type(urlInput, "https://open.spotify.com/track/xyz");

    await user.click(screen.getByRole("button", { name: /^add$/i }));

    // The "already present / upvote?" confirmation should appear
    await waitFor(() => {
      expect(screen.getByText(/already in this playlist/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /upvote/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /dismiss/i })).toBeInTheDocument();
    });
  });
});
