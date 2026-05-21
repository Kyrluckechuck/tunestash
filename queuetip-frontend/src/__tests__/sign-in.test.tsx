import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MockedProvider } from "@apollo/client/testing";

import { RequestMagicLinkDocument } from "@/types/generated/graphql";

// Mock TanStack Router's Link so we don't need a full router context in tests
vi.mock("@tanstack/react-router", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-router")>();
  return {
    ...actual,
    Link: ({ to, children, className }: { to: string; children: React.ReactNode; className?: string }) => (
      <a href={to} className={className}>{children}</a>
    ),
    createFileRoute: () => () => ({
      options: {},
      useSearch: () => ({ next: undefined }),
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
      <MockedProvider mocks={mocks}>
        <SignInPage />
      </MockedProvider>,
    );

    await user.type(screen.getByLabelText(/email/i), "friend@example.com");
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
      <MockedProvider mocks={errorMock}>
        <SignInPage />
      </MockedProvider>,
    );

    await user.type(screen.getByLabelText(/email/i), "bad@example.com");
    await user.click(screen.getByRole("button", { name: /send sign-in link/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Internal server error");
    // Button should be re-enabled (not stuck in Sending... state)
    expect(screen.getByRole("button", { name: /send sign-in link/i })).not.toBeDisabled();
  });
});
