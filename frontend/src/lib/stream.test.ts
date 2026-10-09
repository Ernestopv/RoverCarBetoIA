import { describe, expect, it } from "vitest";

import { buildWhepUrl, resolveSessionUrl } from "./stream";

const LOCALHOST = { protocol: "http:", hostname: "127.0.0.1" };
const PHONE = { protocol: "http:", hostname: "192.168.1.50" };

describe("buildWhepUrl", () => {
  it("uses the browser hostname and the published WebRTC port", () => {
    expect(buildWhepUrl(8889, "rover", LOCALHOST)).toBe("http://127.0.0.1:8889/rover/whep");
  });

  it("works from a phone on the LAN, without knowing the backend's host", () => {
    expect(buildWhepUrl(8889, "rover", PHONE)).toBe("http://192.168.1.50:8889/rover/whep");
  });

  it("tolerates slashes around the stream path", () => {
    expect(buildWhepUrl(8889, "/rover/", LOCALHOST)).toBe("http://127.0.0.1:8889/rover/whep");
  });

  it("lets an explicit base override win", () => {
    expect(buildWhepUrl(8889, "rover", LOCALHOST, "https://cam.example.com/")).toBe(
      "https://cam.example.com/rover/whep",
    );
  });
});

describe("resolveSessionUrl", () => {
  it("returns null without a Location header", () => {
    expect(resolveSessionUrl(null, "http://127.0.0.1:8889/rover/whep")).toBeNull();
  });

  it("resolves a relative Location against the request URL", () => {
    expect(resolveSessionUrl("/rover/whep/session/abc", "http://127.0.0.1:8889/rover/whep")).toBe(
      "http://127.0.0.1:8889/rover/whep/session/abc",
    );
  });

  it("keeps an absolute Location", () => {
    expect(resolveSessionUrl("http://host:8889/s/1", "http://127.0.0.1:8889/rover/whep")).toBe(
      "http://host:8889/s/1",
    );
  });

  it("returns null for garbage instead of throwing", () => {
    expect(resolveSessionUrl("http://", "not-a-url")).toBeNull();
  });
});
