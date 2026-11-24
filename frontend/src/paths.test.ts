import { describe, expect, it } from "vitest";
import { appPath } from "./paths";

describe("appPath", () => {
  it("prefixes application URLs with the configured deployment path", () => {
    expect(appPath("/api/movies", "/moviehub/")).toBe("/moviehub/api/movies");
    expect(appPath("config.json", "/moviehub/")).toBe("/moviehub/config.json");
  });

  it("keeps root deployment URLs compatible", () => {
    expect(appPath("/api/movies", "/")).toBe("/api/movies");
    expect(appPath("config.json", "/")).toBe("/config.json");
  });

  it("normalizes a base path without a trailing slash", () => {
    expect(appPath("api/health", "/moviehub")).toBe("/moviehub/api/health");
  });
});
