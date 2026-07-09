import "@testing-library/jest-dom";
import { afterEach, beforeEach, expect, vi } from "vitest";

let consoleErrors: string[];
let restoreConsoleError: (() => void) | undefined;

beforeEach(() => {
  consoleErrors = [];
  const spy = vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
    consoleErrors.push(args.map(String).join(" "));
  });
  restoreConsoleError = () => spy.mockRestore();
});

afterEach(() => {
  restoreConsoleError?.();
  expect(consoleErrors).toEqual([]);
});

// jsdom does not implement HTMLDialogElement.showModal — polyfill so Dialog works in tests.
if (typeof HTMLDialogElement !== "undefined") {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
}
