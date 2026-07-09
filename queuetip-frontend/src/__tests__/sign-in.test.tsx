import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MockedProvider } from "@apollo/client/testing";

import {
  MeDocument,
  PublicSettingsDocument,
  RequestMagicLinkDocument,
} from "@/types/generated/graphql";

const anonMeMock = {
  request: { query: MeDocument },
  result: { data: { me: null } },
};

const authedMeMock = {
  request: { query: MeDocument },
  result: {
    data: {
      me: {
        __typename: "AccountType",
        id: "1",
        displayName: "Already In",
        email: "already-in@example.com",
        createdAt: "2026-05-19T00:00:00Z",
        isAdmin: false,
        externalServices: [],
      },
    },
  },
};

const publicSettingsMock = (enforced: boolean) => ({
  request: { query: PublicSettingsDocument },
  result: {
    data: {
      publicSettings: {
        __typename: "PublicSettingsType",
        signupAllowlistEnforced: enforced,
      },
    },
  },
});

// Mock TanStack Router's Link + Navigate so we don't need a router context.
// Navigate becomes an observable div with data-testid so we can assert on it.
let nextSearch: { next?: string } = {};
vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    Link: ({ to, children, className }: { to: string; children: React.ReactNode; className?: string }) => (
      <a href={to} className={className}>{children}</a>
    ),
    Navigate: ({ to }: { to: string }) => (
      <div data-testid="navigate" data-to={to} />
    ),
    createFileRoute: () => () => ({
      options: {},
      useSearch: () => nextSearch,
    }),
  };
});

import { SignInPage } from "@/routes/sign-in";

describe("SignInPage", () => {
  it("shows the success card after a successful magic-link request", async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: {
          query: RequestMagicLinkDocument,
          variables: { email: "friend@example.com", displayName: null },
        },
        result: {
          data: {
            requestMagicLink: {
              __typename: "MagicLinkResult",
              sent: true,
              message: "Check your email.",
            },
          },
        },
      },
    ];

    render(
      <MockedProvider mocks={[anonMeMock, publicSettingsMock(false), ...mocks]}>
        <SignInPage />
      </MockedProvider>,
    );

    await user.type(await screen.findByLabelText(/email/i), "friend@example.com");
    await user.click(screen.getByRole("button", { name: /send sign-in link/i }));

    expect(await screen.findByRole("heading", { name: /check your email/i })).toBeInTheDocument();
  });

  it("shows an inline error and re-enables the submit button when the mutation throws", async () => {
    const user = userEvent.setup();
    const errorMock = [
      {
        request: {
          query: RequestMagicLinkDocument,
          variables: { email: "bad@example.com", displayName: null },
        },
        error: new Error("Internal server error"),
      },
    ];

    render(
      <MockedProvider mocks={[anonMeMock, publicSettingsMock(false), ...errorMock]}>
        <SignInPage />
      </MockedProvider>,
    );

    await user.type(await screen.findByLabelText(/email/i), "bad@example.com");
    await user.click(screen.getByRole("button", { name: /send sign-in link/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Internal server error");
    // Button should be re-enabled (not stuck in Sending... state)
    expect(screen.getByRole("button", { name: /send sign-in link/i })).not.toBeDisabled();
  });

  it("shows invite-only note on sign-up link when allowlist is enforced", async () => {
    render(
      <MockedProvider mocks={[anonMeMock, publicSettingsMock(true)]}>
        <SignInPage />
      </MockedProvider>,
    );

    expect(
      await screen.findByText(/invite-only during rollout/i),
    ).toBeInTheDocument();
  });

  it("does not show invite-only note when allowlist is not enforced", async () => {
    render(
      <MockedProvider mocks={[anonMeMock, publicSettingsMock(false)]}>
        <SignInPage />
      </MockedProvider>,
    );

    // Wait for query to settle
    expect(await screen.findByLabelText(/email/i)).toBeInTheDocument();
    expect(
      screen.queryByText(/invite-only during rollout/i),
    ).not.toBeInTheDocument();
  });

  it("redirects to /playlists when the user is already signed in", async () => {
    nextSearch = {};
    render(
      <MockedProvider mocks={[authedMeMock, publicSettingsMock(false)]}>
        <SignInPage />
      </MockedProvider>,
    );
    const nav = await screen.findByTestId("navigate");
    expect(nav.dataset.to).toBe("/playlists");
    // Form should NOT be rendered.
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
  });

  it("honours ?next=… when redirecting an already-signed-in user", async () => {
    nextSearch = { next: "/playlists/42" };
    render(
      <MockedProvider mocks={[authedMeMock, publicSettingsMock(false)]}>
        <SignInPage />
      </MockedProvider>,
    );
    const nav = await screen.findByTestId("navigate");
    expect(nav.dataset.to).toBe("/playlists/42");
    nextSearch = {}; // reset for other tests
  });
});
