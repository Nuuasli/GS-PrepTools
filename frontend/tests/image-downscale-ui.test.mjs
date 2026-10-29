import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(
  new URL("../app/image-downscale/page.tsx", import.meta.url),
  "utf8"
);
const api = readFileSync(new URL("../services/api.ts", import.meta.url), "utf8");

test("Local Path renders separate Quick and Full actions", () => {
  assert.match(page, /"Quick Dry Run"/);
  assert.match(page, /Start Downscale \(Full Preflight\)/);
  assert.match(page, /All images will be validated before processing\./);
});

test("Full action is form-gated but does not depend on Quick Dry Run", () => {
  const click = page.indexOf("onClick={() => void startFullLocal()}");
  assert.notEqual(click, -1, "Full action button must be rendered");
  const fullButton = page.slice(
    page.lastIndexOf("<button", click),
    page.indexOf("</button>", click)
  );
  assert.match(fullButton, /!localInputPath\.trim\(\)/);
  assert.match(fullButton, /!localOutputPath\.trim\(\)/);
  assert.match(fullButton, /maxWidth <= 0/);
  assert.match(fullButton, /maxHeight <= 0/);
  assert.doesNotMatch(fullButton, /job\.can_process|quickSamples/);
  assert.match(
    page,
    /Valid input path, output path, width, and height are required\./
  );
});

test("Full action calls the dedicated full-processing endpoint", () => {
  const handler = page.match(
    /const startFullLocal = async \(\) => \{[\s\S]*?\n  \};/
  );
  assert.ok(handler, "Full action handler must exist");
  assert.match(handler[0], /startLocalImageDownscale\(/);
  assert.doesNotMatch(handler[0], /preflightLocalImageDownscale\(/);
  assert.match(api, /export async function startLocalImageDownscale/);
  assert.match(api, /"\/image-downscale\/local\/start"/);
});

test("Full progress, structured error, and completed summary remain visible", () => {
  assert.match(page, /Validating all images\.\.\./);
  assert.match(page, /Processing dataset \$\{job\.current_dataset_index\}\/\$\{job\.current_dataset_total\}/);
  assert.match(page, /Writing manifests\.\.\./);
  assert.match(page, /Full preflight failed/);
  assert.match(page, /item\.dataset_name/);
  assert.match(page, /item\.relative_path/);
  assert.match(page, /item\.error/);
  assert.match(page, /Batch completed/);
  assert.match(page, /\["Output", job\.result\.output\]/);
  assert.match(page, />Completed</);
  assert.match(page, />Input Path</);
  assert.match(page, />Output Path</);
  for (const label of [
    "Datasets",
    "Total Images",
    "Resized",
    "Unchanged",
    "Failed",
    "Input",
    "Output",
    "Status",
  ]) {
    assert.ok(page.includes(label), `Completed summary must contain ${label}`);
  }
});

test("Quick Dry Run and Browser Upload flows remain wired", () => {
  const handler = page.match(/const runDryRun = async \(\) => \{[\s\S]*?\n  \};/);
  assert.ok(handler, "Quick Dry Run handler must exist");
  assert.match(handler[0], /preflightLocalImageDownscale\(/);
  assert.match(handler[0], /quickSamples/);
  assert.match(handler[0], /preflightImageDownscale\(/);
  assert.match(page, /Start Batch Downscale/);
  assert.match(page, /Download All as ZIP/);
});
