import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MockedProvider } from "@apollo/client/testing";

import { PlaylistDetail } from "@/routes/playlists.$id";
import { CastVoteDocument, MeDocument, PlaylistDetailDocument } from "@/types/generated/graphql";

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

const meMock = {
  request: { query: MeDocument },
  result: {
    data: {
      me: {
        __typename: "AccountType",
        id: "1",
        displayName: "Owner",
        createdAt: "2026-05-19T00:00:00Z",
        externalServices: [],
        isAdmin: false,
      },
    },
  },
};

const playlistDetailMock = {
  request: {
    query: PlaylistDetailDocument,
    variables: { id: "10" },
  },
  result: {
    data: {
      playlist: {
        __typename: "PlaylistType",
        id: "10",
        name: "Friday Mix",
        description: "A chill playlist",
        inviteToken: "tok-abc",
        engineSettings: {
          __typename: "EngineSettings",
          minSize: 5,
          maxSize: null,
          tHigh: 20,
          tLow: 5,
          base: 0.5,
          pFloor: 0.1,
        },
        createdBy: { __typename: "AccountType", id: "1", displayName: "Owner" },
        members: [
          {
            __typename: "MembershipType",
            account: { __typename: "AccountType", id: "1", displayName: "Owner" },
            role: "owner",
          },
          {
            __typename: "MembershipType",
            account: { __typename: "AccountType", id: "2", displayName: "Alice" },
            role: "member",
          },
        ],
      },
      playlistContributions: [
        {
          __typename: "ContributionType",
          id: "100",
          netScore: 2,
          duplicateKind: "none",
          duplicateWithTitles: [],
          createdAt: "2026-05-19T10:00:00Z",
          contributedBy: { __typename: "AccountType", id: "2", displayName: "Alice" },
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
          votes: [
            { __typename: "VoteType", account: { __typename: "AccountType", id: "1" }, value: 1 },
            { __typename: "VoteType", account: { __typename: "AccountType", id: "2" }, value: 1 },
          ],
        },
      ],
    },
  },
};

describe("PlaylistDetail", () => {
  it("renders the playlist name, members, and a contribution", async () => {
    render(
      <MockedProvider mocks={[meMock, meMock, playlistDetailMock]}>
        <PlaylistDetail />
      </MockedProvider>
    );

    expect(await screen.findByText("Friday Mix")).toBeInTheDocument();
    expect(await screen.findByText("Bohemian Rhapsody")).toBeInTheDocument();
    expect(await screen.findByText(/Queen/)).toBeInTheDocument();
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    expect(await screen.findByText("+2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add songs/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /bulk import/i })).not.toBeInTheDocument();
  });

  it("calls castVote mutation with correct variables when upvote is clicked", async () => {
    const user = userEvent.setup();

    const castVoteResult = vi.fn().mockReturnValue({
      data: {
        castVote: {
          __typename: "ContributionType",
          id: "100",
          netScore: 3,
          votes: [
            { __typename: "VoteType", account: { __typename: "AccountType", id: "1" }, value: 1 },
            { __typename: "VoteType", account: { __typename: "AccountType", id: "2" }, value: 1 },
            { __typename: "VoteType", account: { __typename: "AccountType", id: "3" }, value: 1 },
          ],
        },
      },
    });

    // Me returns account id "3" so their vote is not already cast (netScore stays optimistic).
    const meForVote = {
      request: { query: MeDocument },
      result: {
        data: {
          me: {
            __typename: "AccountType",
            id: "3",
            displayName: "Bob",
            createdAt: "2026-05-19T00:00:00Z",
            externalServices: [],
            isAdmin: false,
          },
        },
      },
    };

    const castVoteMock = {
      request: {
        query: CastVoteDocument,
        variables: { contributionId: "100", value: 1 },
      },
      result: castVoteResult,
    };

    render(
      <MockedProvider mocks={[meForVote, meForVote, playlistDetailMock, castVoteMock]}>
        <PlaylistDetail />
      </MockedProvider>
    );

    // Wait for the contribution to appear
    await screen.findByText("Bohemian Rhapsody");

    // Click the upvote button
    const upvoteButton = screen.getByRole("button", { name: /upvote/i });
    await user.click(upvoteButton);

    await waitFor(() => {
      expect(castVoteResult).toHaveBeenCalled();
    });
  });
});
