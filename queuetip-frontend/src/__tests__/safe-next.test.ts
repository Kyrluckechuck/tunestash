import { describe, expect, it } from "vitest";

import { safeNext } from "@/lib/safe-next";

describe("safeNext", () => {
  it("keeps same-origin relative paths", () => {
    expect(safeNext("/playlists/12")).toBe("/playlists/12");
    expect(safeNext("/join/abc?x=1#y")).toBe("/join/abc?x=1#y");
  });

  it.each([
    "javascript:alert(1)",
    "https://evil.example",
    "http://evil.example/x",
    "//evil.example",
    "/\\evil.example",
    "/\t/evil.example",
    "/\n/evil.example",
    "playlists",
    "",
    " /playlists",
  ])("rejects %j", (value) => {
    expect(safeNext(value)).toBe("/playlists");
  });

  it("rejects non-strings and undefined", () => {
    expect(safeNext(undefined)).toBe("/playlists");
    expect(safeNext(["/a"])).toBe("/playlists");
  });
});
