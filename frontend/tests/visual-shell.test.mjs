import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const shell = readFileSync(
  new URL("../components/app-shell.tsx", import.meta.url),
  "utf8"
);
const tokens = readFileSync(
  new URL("../app/globals.css", import.meta.url),
  "utf8"
);

test("research workspace tokens match the light charcoal and terracotta identity", () => {
  for (const token of [
    "--background: #f6f6f6",
    "--header: #fdfdfd",
    "--card: #ffffff",
    "--primary: #b0371f",
    "--soft-accent: #f9f2ee",
    "--foreground: #262626",
  ]) {
    assert.ok(tokens.includes(token), `Missing design token: ${token}`);
  }
  assert.match(shell, /bg-\[#151515\]/);
});

test("sidebar exposes only real application routes", () => {
  assert.match(shell, /href: "\/"/);
  assert.match(shell, /href: "\/image-downscale"/);
  assert.doesNotMatch(shell, /href: "\/dashboard"|href: "\/history"/);
});

test("responsive navigation has accessible state and controls", () => {
  assert.match(shell, /aria-label="Primary navigation"/);
  assert.match(shell, /aria-current=\{active \? "page" : undefined\}/);
  assert.match(shell, /aria-label="Open navigation"/);
  assert.match(shell, /aria-expanded=\{mobileOpen\}/);
  assert.match(tokens, /@media \(prefers-reduced-motion: reduce\)/);
});
