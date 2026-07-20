const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

test("status page includes local-only model state", () => {
  const page = fs.readFileSync(path.join(__dirname, "..", "app", "page.tsx"), "utf8");
  assert.match(page, /Model: not configured/);
  assert.match(page, /No remote APIs or credentials are enabled/);
});

test("health client defaults to loopback backend", () => {
  const client = fs.readFileSync(path.join(__dirname, "..", "lib", "health.ts"), "utf8");
  assert.match(client, /http:\/\/127\.0\.0\.1:8080/);
  assert.match(client, /cache: "no-store"/);
});
