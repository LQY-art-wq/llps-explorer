import assert from "node:assert/strict";
import test from "node:test";
import { allowedApiPath, allowedRequestOrigin, upstreamApiUrl } from "../src/lib/proxy-config.ts";

test("origin checks preserve the actual local hostname without Next URL normalization", () => {
  assert.equal(allowedRequestOrigin("http://127.0.0.1:3000", "127.0.0.1:3000"), true);
  assert.equal(allowedRequestOrigin("http://localhost:3000", "localhost:3000"), true);
  assert.equal(allowedRequestOrigin("http://127.0.0.1:3000", "localhost:3000"), false);
  assert.equal(allowedRequestOrigin("http://localhost:3000", "127.0.0.1:3000"), false);
  assert.equal(allowedRequestOrigin("http://localhost:3000", "localhost:3001"), false);
});

test("origin checks normalize default ports and IPv6 authorities", () => {
  assert.equal(allowedRequestOrigin("http://proteins.example", "proteins.example:80"), true);
  assert.equal(allowedRequestOrigin("https://proteins.example:443", "proteins.example"), true);
  assert.equal(allowedRequestOrigin("https://proteins.example", "proteins.example:80"), false);
  assert.equal(allowedRequestOrigin("https://PROTEINS.EXAMPLE", "proteins.example:443"), true);
  assert.equal(allowedRequestOrigin("http://[::1]:3000", "[::1]:3000"), true);
  assert.equal(allowedRequestOrigin("http://[0:0:0:0:0:0:0:1]:80", "[::1]"), true);
  assert.equal(allowedRequestOrigin("http://[::1]:3000", "[::1]:3001"), false);
});

test("HTTPS edge termination works when the public Host is preserved", () => {
  const headers = new Headers({ origin: "https://proteins.example", host: "proteins.example", "x-forwarded-host": "foreign.example" });
  assert.equal(allowedRequestOrigin(headers.get("origin"), headers.get("host")), true);
  headers.set("origin", "https://foreign.example");
  assert.equal(allowedRequestOrigin(headers.get("origin"), headers.get("host")), false);
});

test("missing Origin retains the CLI contract, but a present Origin requires Host", () => {
  assert.equal(allowedRequestOrigin(null, "localhost:3000"), true);
  assert.equal(allowedRequestOrigin(null, null), true);
  assert.equal(allowedRequestOrigin("http://localhost:3000", null), false);
});

test("opaque, malformed, credentialed, path-bearing and foreign origins are rejected", () => {
  for (const origin of [
    "", "null", "https://foreign.example", "https://proteins.example.evil.test",
    "https://user:secret@proteins.example", "https://proteins.example/",
    "https://proteins.example/path", "https://proteins.example?x=1", "https://proteins.example#fragment",
    " https://proteins.example", "https://proteins.example ", "https://proteins.example\n", "https://proteins.example\\@foreign.example",
    "https://proteins.example,https://foreign.example", "https://%70roteins.example",
    "file://proteins.example", "https://proteins.example:65536", "https://[invalid]",
  ]) assert.equal(allowedRequestOrigin(origin, "proteins.example"), false, origin);
  for (const host of ["", "proteins.example/path", "proteins.example?x=1", "user@proteins.example", "proteins.example,foreign.example", "proteins.example ", "proteins.example\n", "proteins.example:65536", "::1"])
    assert.equal(allowedRequestOrigin("https://proteins.example", host), false, host);
});

test("proxy routes only the workspace API methods", () => {
  assert.equal(allowedApiPath(["analysis"], "POST"), true);
  assert.equal(allowedApiPath(["analysis", "history"], "GET"), true);
  assert.equal(allowedApiPath(["config", "public"], "GET"), true);
  assert.equal(allowedApiPath(["analysis", "analysis_test-id"], "GET"), true);
  assert.equal(allowedApiPath(["analysis", "analysis_test-id"], "DELETE"), true);
  for (const format of ["json", "summary.csv", "residues.csv", "regions.csv", "fasta"]) {
    assert.equal(allowedApiPath(["analysis", "analysis_test-id", "export", format], "GET"), true, format);
  }
  assert.equal(allowedApiPath(["methods", "fuzdrop", "import"], "POST"), true);
  for (const path of [["methods", "dismeta", "analyze"], ["admin"], ["analysis", ".."],
    ["analysis", "analysis_test", "export", "other.csv"], ["analysis", "analysis_test", "export", "../residues.csv"]]) {
    assert.equal(allowedApiPath(path, "POST"), false);
    assert.equal(allowedApiPath(path, "GET"), false);
  }
});

test("proxy target requires explicit private server configuration", () => {
  assert.equal(upstreamApiUrl(undefined, ["methods"]), null);
  assert.equal(upstreamApiUrl("file:///private/model", ["methods"]), null);
  assert.equal(upstreamApiUrl("https://user:secret@example.test", ["methods"]), null);
  assert.equal(upstreamApiUrl("https://example.test?secret=x", ["methods"]), null);
  assert.equal(upstreamApiUrl("https://example.test", ["..", "secrets"]), null);
  assert.equal(upstreamApiUrl("https://example.test/backend/", ["analysis", "job_test"])?.href,
    "https://example.test/backend/api/v1/analysis/job_test");
  assert.equal(upstreamApiUrl("https://example.test/backend/", ["analysis", "job_test", "export", "residues.csv"])?.href,
    "https://example.test/backend/api/v1/analysis/job_test/export/residues.csv");
  assert.equal(upstreamApiUrl("https://example.test", ["analysis", "job_test", "export", "other.csv"]), null);
});
