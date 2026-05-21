import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MockedProvider } from "@apollo/client/testing";

import { PlaylistsIndex } from "@/routes/playlists.index";
import { MyPlaylistsDocument, MeDocument } from "@/types/generated/graphql";

vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    Link: ({ children, ...props }: React.AnchorHTMLAttributes<HTMLAnchorElement> & { children?: React.ReactNode }) => (
      <a {...props}>{children}</a>
    ),
    Navigate: () => <div data-testid="navigate" />,
    useRouter: () => ({ navigate: vi.fn() }),
    createFileRoute: () => () => ({ options: {} }),
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
      },
    },
  },
};

const playlistsMock = {
  request: { query: MyPlaylistsDocument },
  result: {
    data: {
      myPlaylists: [
        {
          __typename: "PlaylistType",
          id: "10",
          name: "Friday Mix",
          description: "",
          createdAt: "2026-05-19T00:00:00Z",
          members: [
            {
              __typename: "MembershipType",
              account: { __typename: "AccountType", id: "1", displayName: "Owner" },
              role: "owner",
            },
          ],
        },
      ],
    },
  },
};

describe("PlaylistsIndex", () => {
  it("renders the user's playlists", async () => {
    render(
      <MockedProvider mocks={[meMock, playlistsMock]}>
        <PlaylistsIndex />
      </MockedProvider>,
    );
    expect(await screen.findByText("Friday Mix")).toBeInTheDocument();
  });

  it("shows member count for a playlist", async () => {
    render(
      <MockedProvider mocks={[meMock, playlistsMock]}>
        <PlaylistsIndex />
      </MockedProvider>,
    );
    expect(await screen.findByText(/1 member$/)).toBeInTheDocument();
  });

  it("opens the new-playlist dialog when the button is clicked", async () => {
    const user = userEvent.setup();
    render(
      <MockedProvider
        mocks={[
          meMock,
          { ...playlistsMock, result: { data: { myPlaylists: [] } } },
        ]}
      >
        <PlaylistsIndex />
      </MockedProvider>,
    );
    await screen.findByText(/no playlists yet/i);
    await user.click(screen.getByRole("button", { name: /new playlist/i }));
    expect(await screen.findByText(/name it/i)).toBeInTheDocument();
  });

  it("shows the empty state when there are no playlists", async () => {
    render(
      <MockedProvider
        mocks={[
          meMock,
          { ...playlistsMock, result: { data: { myPlaylists: [] } } },
        ]}
      >
        <PlaylistsIndex />
      </MockedProvider>,
    );
    expect(await screen.findByText(/no playlists yet/i)).toBeInTheDocument();
  });
});
