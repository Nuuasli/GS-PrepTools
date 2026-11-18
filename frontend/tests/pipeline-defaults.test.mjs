import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const store = readFileSync(
  new URL("../hooks/use-pipeline-store.ts", import.meta.url),
  "utf8"
);

test("video extraction defaults match the Processing Configuration preset", () => {
  for (const expected of [
    "extraction_fps: 2",
    "jpeg_quality: 100",
    "blur_threshold: 75",
    "duplicate_threshold: 0.98",
    "resize_width: 0",
    'duplicate_method: "orb"',
    "keep_intermediates: true",
  ]) {
    assert.ok(store.includes(expected), `Missing default: ${expected}`);
  }
});

test("persisted store version migrates stale browser defaults", () => {
  assert.match(store, /const PERSIST_VERSION = 3;/);
  assert.match(store, /if \(version < PERSIST_VERSION\)/);
  assert.match(store, /config: \{ \.\.\.DEFAULT_CONFIG \}/);
});
