import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MockedProvider } from "@apollo/client/testing";

import { SettingsPage } from "@/routes/settings";
import {
  MeDocument,
  MySubsonicConnectionDocument,
  SignOutEverywhereDocument,
} from "@/types/generated/graphql";

const mockNavigate = vi.fn();

vi.mock("@tanstack/react-router", async (orig) => {
  const actual = await (orig as () => Promise<typeof import("@tanstack/react-router")>)();
  return {
    ...actual,
    Navigate: () => <div data-testid="navigate" />,
    createFileRoute: () => () => ({ options: {} }),
    useNavigate: () => mockNavigate,
  };
});

vi.mock("@/lib/auth", async (orig) => {
  const actual = await (orig as () => Promise<typeof import("@/lib/auth")>)();
  return { ...actual, signOut: vi.fn().mockResolvedValue(undefined) };
});

const meWithSpotify = (services: Array<{ service: string; serviceUserId: string }>) => ({
  request: { query: MeDocument },
  result: {
    data: {
      me: {
        __typename: "AccountType",
        id: "1",
        displayName: "Jo",
        createdAt: "2026-05-19T00:00:00Z",
        isAdmin: false,
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

const signOutEverywhereMock = {
  request: { query: SignOutEverywhereDocument },
  result: { data: { signOutEverywhere: { __typename: "SignOutEverywhereResult", success: true } } },
};

const subsonicConnectionMock = {
  request: { query: MySubsonicConnectionDocument },
  result: { data: { mySubsonicConnection: null } },
};

describe("SettingsPage", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("shows the Link Spotify button when not linked", async () => {
    const mock = meWithSpotify([]);
    render(
      <MockedProvider mocks={[mock, mock, subsonicConnectionMock]}>
        <SettingsPage />
      </MockedProvider>
    );
    expect(await screen.findByRole("button", { name: /link spotify/i })).toBeInTheDocument();
  });

  it("shows the linked state with the service user id", async () => {
    const mock = meWithSpotify([{ service: "spotify", serviceUserId: "alice42" }]);
    render(
      <MockedProvider mocks={[mock, mock, subsonicConnectionMock]}>
        <SettingsPage />
      </MockedProvider>
    );
    expect(await screen.findByText(/linked ✓/i)).toBeInTheDocument();
    expect(screen.getByText(/alice42/)).toBeInTheDocument();
  });

  it("stores browser link preferences for Spotify, Apple Music, and Deezer app links", async () => {
    const mock = meWithSpotify([]);
    render(
      <MockedProvider mocks={[mock, mock, subsonicConnectionMock]}>
        <SettingsPage />
      </MockedProvider>
    );

    const preference = await screen.findByRole("switch", {
      name: /open spotify songs in desktop app/i,
    });
    expect(preference).toHaveAttribute("aria-checked", "false");

    fireEvent.click(preference);

    expect(preference).toHaveAttribute("aria-checked", "true");
    expect(window.localStorage.getItem("queuetip.openSpotifyLinksInApp")).toBe("true");

    const applePreference = screen.getByRole("switch", {
      name: /open apple music links in app/i,
    });
    fireEvent.click(applePreference);
    expect(applePreference).toHaveAttribute("aria-checked", "true");
    expect(window.localStorage.getItem("queuetip.openAppleLinksInApp")).toBe("true");

    const deezerPreference = screen.getByRole("switch", {
      name: /open deezer links in app/i,
    });
    fireEvent.click(deezerPreference);
    expect(deezerPreference).toHaveAttribute("aria-checked", "true");
    expect(window.localStorage.getItem("queuetip.openDeezerLinksInApp")).toBe("true");
  });

  it("sign out everywhere button calls the mutation and navigates to sign-in", async () => {
    const mock = meWithSpotify([]);
    render(
      <MockedProvider mocks={[mock, mock, subsonicConnectionMock, signOutEverywhereMock]}>
        <SettingsPage />
      </MockedProvider>
    );

    const btn = await screen.findByRole("button", { name: /sign out everywhere/i });
    fireEvent.click(btn);

    await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith({ to: "/sign-in" }));
  });
});
