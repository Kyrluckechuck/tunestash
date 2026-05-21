import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MockedProvider } from "@apollo/client/testing";

import {
  MeDocument,
  PublicSettingsDocument,
} from "@/types/generated/graphql";

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
    Navigate: () => <div data-testid="navigate" />,
    createFileRoute: () => () => ({ options: {} }),
  };
});

import { Home } from "@/routes/index";

const anonMeMock = {
  request: { query: MeDocument },
  result: { data: { me: null } },
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

describe("Home (landing page)", () => {
  it("hides the Sign up button and shows invite-only text when allowlist is enforced", async () => {
    render(
      <MockedProvider mocks={[anonMeMock, publicSettingsMock(true)]}>
        <Home />
      </MockedProvider>,
    );

    expect(await screen.findByRole("link", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /sign up/i })).not.toBeInTheDocument();
    expect(screen.getByText(/invite-only/i)).toBeInTheDocument();
  });

  it("shows the Sign up button when allowlist is not enforced", async () => {
    render(
      <MockedProvider mocks={[anonMeMock, publicSettingsMock(false)]}>
        <Home />
      </MockedProvider>,
    );

    expect(await screen.findByRole("link", { name: /sign in/i })).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /sign up/i })).toBeInTheDocument();
    expect(screen.queryByText(/invite-only/i)).not.toBeInTheDocument();
  });
});
