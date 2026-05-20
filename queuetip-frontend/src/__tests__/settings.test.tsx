import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MockedProvider } from "@apollo/client/testing";

import { SettingsPage } from "@/routes/settings";
import { MeDocument } from "@/types/generated/graphql";

vi.mock("@tanstack/react-router", async (orig) => {
  const actual = await (orig as () => Promise<typeof import("@tanstack/react-router")>)();
  return {
    ...actual,
    Navigate: () => <div data-testid="navigate" />,
    createFileRoute: () => () => ({ options: {} }),
  };
});

const meWithSpotify = (
  services: Array<{ service: string; serviceUserId: string }>,
) => ({
  request: { query: MeDocument },
  result: {
    data: {
      me: {
        __typename: "AccountType",
        id: "1",
        displayName: "Jo",
        createdAt: "2026-05-19T00:00:00Z",
        externalServices: services.map((s) => ({
          __typename: "ExternalServiceLinkType",
          service: s.service,
          serviceUserId: s.serviceUserId,
          linkedAt: "2026-05-19T00:00:00Z",
        })),
      },
    },
  },
});

describe("SettingsPage", () => {
  it("shows the Link Spotify button when not linked", async () => {
    const mock = meWithSpotify([]);
    render(
      <MockedProvider mocks={[mock, mock]}>
        <SettingsPage />
      </MockedProvider>,
    );
    expect(
      await screen.findByRole("button", { name: /link spotify/i }),
    ).toBeInTheDocument();
  });

  it("shows the linked state with the service user id", async () => {
    const mock = meWithSpotify([{ service: "spotify", serviceUserId: "alice42" }]);
    render(
      <MockedProvider mocks={[mock, mock]}>
        <SettingsPage />
      </MockedProvider>,
    );
    expect(await screen.findByText(/linked ✓/i)).toBeInTheDocument();
    expect(screen.getByText(/alice42/)).toBeInTheDocument();
  });
});
