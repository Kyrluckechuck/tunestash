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
let nextSearch: { next?: string } = {};
vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    Link: ({
      to,
      children,
      className,
    }: {
      to: string;
      children: React.ReactNode;
      className?: string;
    }) => (
      <a href={to} className={className}>
        {children}
      </a>
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

import { SignUpPage } from "@/routes/sign-up";

describe("SignUpPage", () => {
  it("submits email + displayName and shows the success card", async () => {
    const user = userEvent.setup();
    const mocks = [
      {
        request: {
          query: RequestMagicLinkDocument,
          variables: { email: "new@example.com", displayName: "New Friend" },
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
        <SignUpPage />
      </MockedProvider>,
    );

    await user.type(await screen.findByLabelText(/email/i), "new@example.com");
    await user.type(screen.getByLabelText(/display name/i), "New Friend");
    await user.click(screen.getByRole("button", { name: /create account/i }));

    expect(
      await screen.findByRole("heading", { name: /check your email/i }),
    ).toBeInTheDocument();
  });

  it("keeps the Create account button disabled until both fields are filled", async () => {
    const user = userEvent.setup();
    render(
      <MockedProvider mocks={[anonMeMock, publicSettingsMock(false)]}>
        <SignUpPage />
      </MockedProvider>,
    );
    // Wait for the form to render after the Me query resolves.
    await screen.findByLabelText(/email/i);
    const submit = screen.getByRole("button", { name: /create account/i });
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText(/email/i), "new@example.com");
    expect(submit).toBeDisabled();
    await user.type(screen.getByLabelText(/display name/i), "New Friend");
    expect(submit).not.toBeDisabled();
  });

  it("shows invite-only alert when allowlist is enforced", async () => {
    render(
      <MockedProvider mocks={[anonMeMock, publicSettingsMock(true)]}>
        <SignUpPage />
      </MockedProvider>,
    );

    expect(
      await screen.findByText(/invite-only/i),
    ).toBeInTheDocument();
  });

  it("does not show invite-only alert when allowlist is not enforced", async () => {
    render(
      <MockedProvider mocks={[anonMeMock, publicSettingsMock(false)]}>
        <SignUpPage />
      </MockedProvider>,
    );

    // Wait for the form to render
    expect(await screen.findByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.queryByText(/invite-only/i)).not.toBeInTheDocument();
  });

  it("redirects to /playlists when the user is already signed in", async () => {
    nextSearch = {};
    render(
      <MockedProvider mocks={[authedMeMock, publicSettingsMock(false)]}>
        <SignUpPage />
      </MockedProvider>,
    );
    const nav = await screen.findByTestId("navigate");
    expect(nav.dataset.to).toBe("/playlists");
    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
  });

  it("honours ?next=… when redirecting an already-signed-in user", async () => {
    nextSearch = { next: "/playlists/42" };
    render(
      <MockedProvider mocks={[authedMeMock, publicSettingsMock(false)]}>
        <SignUpPage />
      </MockedProvider>,
    );
    const nav = await screen.findByTestId("navigate");
    expect(nav.dataset.to).toBe("/playlists/42");
    nextSearch = {};
  });
});
