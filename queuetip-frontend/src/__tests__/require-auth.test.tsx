import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MockedProvider } from "@apollo/client/testing";

import { RequireAuth } from "@/components/RequireAuth";
import { MeDocument } from "@/types/generated/graphql";

vi.mock("@tanstack/react-router", async (orig) => {
  const actual = await (orig as () => Promise<typeof import("@tanstack/react-router")>)();
  return {
    ...actual,
    Navigate: ({ to }: { to: string }) => <div data-testid="navigate" data-to={to} />,
  };
});

describe("RequireAuth", () => {
  it("renders children for a signed-in account", async () => {
    const mocks = [
      {
        request: { query: MeDocument },
        result: {
          data: {
            me: {
              __typename: "AccountType",
              id: "1",
              displayName: "Jo",
              createdAt: "2026-05-19T00:00:00Z",
            },
          },
        },
      },
    ];
    render(
      <MockedProvider mocks={mocks}>
        <RequireAuth>
          <div>secret</div>
        </RequireAuth>
      </MockedProvider>,
    );
    expect(await screen.findByText("secret")).toBeInTheDocument();
  });

  it("redirects to /sign-in when anonymous", async () => {
    const mocks = [
      { request: { query: MeDocument }, result: { data: { me: null } } },
    ];
    render(
      <MockedProvider mocks={mocks}>
        <RequireAuth>
          <div>secret</div>
        </RequireAuth>
      </MockedProvider>,
    );
    const nav = await screen.findByTestId("navigate");
    expect(nav.getAttribute("data-to")).toBe("/sign-in");
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });
});
