import { describe, expect, it } from "vitest";

import { companionEntryUrl } from "./companionNavigation";

const LOCAL = "http://127.0.0.1:5180/admin/";

describe("explicit exhibit navigation configuration", () => {
  it.each([
    ["/exhibit/", "http://127.0.0.1:5180/exhibit/"],
    ["http://127.0.0.1:4174/", "http://127.0.0.1:4174/"],
    ["https://exhibit.example.com/", "https://exhibit.example.com/"],
    ["/%E5%B1%95%E5%8E%85", "http://127.0.0.1:5180/%E5%B1%95%E5%8E%85"],
  ])("resolves safe config %s", (value, expected) => {
    expect(companionEntryUrl(value, LOCAL)).toBe(expected);
  });

  it.each([
    undefined,
    null,
    false,
    {},
    1,
    "",
    " ",
    " /exhibit",
    "/exhibit ",
    "/exhibit\n",
    "/\u0000",
    "/\u007f",
    "exhibit/",
    "../exhibit/",
    "//example.com/",
    "/\\example.com",
    "javascript:alert(1)",
    "data:text/html,hello",
    "file:///index.html",
    "ftp://example.com/",
    "https:example.com/",
    "https:///example.com/",
    "https://",
    "http://[broken/",
    "http://127.0.0.1:65536/",
    "https://user:password@example.com/",
    "https://user@example.com/",
    "https://@example.com/",
    "https://example.com\\@other.example.com/",
    "/?returnTo=other",
    "/?",
    "/#section",
    "/#",
    "/%",
    "/%xx",
    "/%0a",
    "/%00",
    "/%7f",
    "/%5c",
    "/%20",
    "/%E0%A4",
    "/" + "a".repeat(2048),
  ])("hides unsafe or absent config %j", (value) => {
    expect(companionEntryUrl(value, LOCAL)).toBeNull();
  });

  it("accepts the bounded length and refuses downgrade or non-web page origins", () => {
    expect(companionEntryUrl("/" + "a".repeat(2047), LOCAL)).not.toBeNull();
    expect(
      companionEntryUrl(
        "http://example.com/",
        "https://admin.example.com/admin/",
      ),
    ).toBeNull();
    expect(companionEntryUrl("/exhibit/", "file:///index.html")).toBeNull();
    expect(companionEntryUrl("/exhibit/", "invalid")).toBeNull();
  });

  it("requires consistent loopback hostnames without restricting HTTPS companion sites", () => {
    expect(companionEntryUrl("http://localhost:4174/", LOCAL)).toBeNull();
    expect(companionEntryUrl("http://[::1]:4174/", LOCAL)).toBeNull();
    expect(
      companionEntryUrl("http://127.0.0.1:4174/", "http://admin.example.com/"),
    ).toBeNull();
    expect(
      companionEntryUrl(
        "http://localhost:4174/",
        "http://localhost:5180/admin/",
      ),
    ).toBe("http://localhost:4174/");
    expect(
      companionEntryUrl("http://[::1]:4174/", "http://[::1]:5180/admin/"),
    ).toBe("http://[::1]:4174/");
  });
});
