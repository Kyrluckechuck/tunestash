import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MockedProvider } from "@apollo/client/testing";

import {
  JoinPlaylistDocument,
  MeDocument,
  PlaylistByInviteTokenDocument,
} from "@/types/generated/graphql";

const mockNavigate = vi.fn();

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    Link: ({
      to,
      children,
      search,
      params,
      className,
    }: {
      to: string;
      children: React.ReactNode;
      search?: Record<string, unknown>;
      params?: Record<string, string>;
      className?: string;
    }) => {
      const href = params
        ? Object.entries(params).reduce(
            (acc, [k, v]) => acc.replace(`$${k}`, v),
            to,
          )
        : to;
      return (
        <a href={href} data-search={JSON.stringify(search)} className={className}>
          {children}
        </a>
      );
    },
    Navigate: () => <div data-testid="navigate" />,
    useRouter: () => ({ navigate: mockNavigate }),
    createFileRoute: () => () => ({
      options: {},
      useParams: () => ({ token: "invite-abc" }),
    }),
  };
});

import { JoinPage } from "@/routes/join.$token";

const inviteToken = "invite-abc";

const playlistMock = {
  request: {
    query: PlaylistByInviteTokenDocument,
    variables: { token: inviteToken },
  },
  result: {
    data: {
      playlist: {
        __typename: "PlaylistType",
        id: "42",
        name: "Friday Mix",
        description: "A chill playlist",
        members: [
          {
            __typename: "MembershipType",
            account: {
              __typename: "AccountType",
              id: "1",
              displayName: "Owner",
            },
            role: "owner",
          },
        ],
      },
    },
  },
};

const anonMeMock = {
  request: { query: MeDocument },
  result: { data: { me: null } },
};

const signedInMeMock = (id: string, displayName: string) => ({
  request: { query: MeDocument },
  result: {
    data: {
      me: {
        __typename: "AccountType",
        id,
        displayName,
        createdAt: "2026-05-19T00:00:00Z",
        externalServices: [],
      },
    },
  },
});

describe("JoinPage", () => {
  it("shows 'Sign in to join' link for anonymous user", async () => {
    render(
      <MockedProvider mocks={[anonMeMock, playlistMock]}>
        <JoinPage />
      </MockedProvider>,
    );

    expect(await screen.findByText("Friday Mix")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /sign in to join/i });
    expect(link).toBeInTheDocument();
    expect(link.getAttribute("href")).toContain("/sign-in");
    expect(link.getAttribute("data-search")).toContain(`/join/${inviteToken}`);
  });

  it("shows 'Open playlist' link when already a member", async () => {
    // Account id "1" matches the owner member
    render(
      <MockedProvider
        mocks={[
          signedInMeMock("1", "Owner"),
          signedInMeMock("1", "Owner"),
          playlistMock,
        ]}
      >
        <JoinPage />
      </MockedProvider>,
    );

    expect(await screen.findByText("Friday Mix")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /open playlist/i });
    expect(link).toBeInTheDocument();
    expect(link.getAttribute("href")).toContain("42");
  });

  it("fires JoinPlaylist mutation and navigates on success for non-member", async () => {
    const joinResult = vi.fn().mockReturnValue({
      data: {
        joinPlaylist: {
          __typename: "PlaylistType",
          id: "42",
        },
      },
    });

    const joinMock = {
      request: {
        query: JoinPlaylistDocument,
        variables: { token: inviteToken },
      },
      result: joinResult,
    };

    // Account id "99" is not in the members list
    render(
      <MockedProvider
        mocks={[
          signedInMeMock("99", "Newcomer"),
          signedInMeMock("99", "Newcomer"),
          playlistMock,
          joinMock,
        ]}
      >
        <JoinPage />
      </MockedProvider>,
    );

    expect(await screen.findByText("Friday Mix")).toBeInTheDocument();

    const user = userEvent.setup();
    const joinButton = screen.getByRole("button", { name: /join playlist/i });
    await user.click(joinButton);

    await waitFor(() => {
      expect(joinResult).toHaveBeenCalled();
    });

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith(
        expect.objectContaining({
          to: "/playlists/$id",
          params: { id: "42" },
        }),
      );
    });
  });
});
