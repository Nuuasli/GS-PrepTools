// Run against the local Next.js/FastAPI applications with Playwright and Chrome installed.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.LIDAR_PLAYWRIGHT || "playwright");
const points = [];
for (let x = -10; x <= 10; x++) {
  for (let y = -10; y <= 10; y++) {
    for (let z = -10; z <= 10; z++) {
      if (Math.max(Math.abs(x), Math.abs(y), Math.abs(z)) === 10 || (x+y+z) % 3 === 0)
        points.push([x/10, y/10, z/10, 95+x*5, 150+y*5, 170+z*3, 115+z*4]);
    }
  }
}
const ply = Buffer.from([
  "ply", "format ascii 1.0", `element vertex ${points.length}`,
  ...["x", "y", "z"].map((name) => `property float ${name}`),
  ...["red", "green", "blue", "intensity"].map((name) => `property uchar ${name}`),
  "end_header", ...points.map((point) => point.join(" ")), "",
].join("\n"));

const browser = await chromium.launch({
  channel: "chrome", headless: true, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
});
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 }, acceptDownloads: true });
  const failures = [];
  page.on("pageerror", (error) => failures.push(error.message));
  await page.goto(process.env.LIDAR_FRONTEND_URL || "http://localhost:3000");
  await page.getByRole("link", { name: "LiDAR Cropper" }).click();
  await page.getByRole("heading", { name: "LiDAR Cropper" }).waitFor();
  await page.getByLabel("Point cloud file").setInputFiles({ name: "synthetic.ply", mimeType: "application/octet-stream", buffer: ply });
  const canvas = page.locator("canvas[aria-label='Interactive 3D point cloud']");
  await canvas.waitFor({ timeout: 30_000 });
  const screenshot = await canvas.screenshot();
  const b = await canvas.boundingBox();
  const cx = b.x + b.width / 2, cy = b.y + b.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx+95,cy+38,{ steps: 8 });
  await page.mouse.up();
  assert.notDeepEqual(await canvas.screenshot(), screenshot, "Orbit redraws the point cloud");
  const orbit = await canvas.screenshot();
  await page.mouse.move(cx, cy);
  await page.mouse.down({ button: "right" });
  await page.mouse.move(cx+38,cy+30,{ steps: 7 });
  await page.mouse.up({ button: "right" });
  assert.notDeepEqual(await canvas.screenshot(), orbit, "Pan redraws the point cloud");
  const pan = await canvas.screenshot();
  await page.mouse.wheel(0, 300);
  assert.notDeepEqual(await canvas.screenshot(), pan, "Zoom redraws the point cloud");
  await page.getByRole("button", { name: "Fit to Data" }).click();
  await page.getByRole("button", { name: "Reset Camera" }).click();
  await page.getByRole("button", { name: "Pick Center" }).click();
  await canvas.click({ position: { x: b.width / 2, y: b.height / 2 } });
  await page.getByText("Center picked from the preview.").waitFor();
  assert.ok((await Promise.all(["X", "Y", "Z"].map((axis) => page.getByLabel(`Center ${axis}`).inputValue()))).some((n) => Number(n) !== 0));

  await page.getByLabel("Color").selectOption("intensity");
  await page.getByLabel("Preview quality").selectOption("high");
  await page.getByLabel("Point size").focus();
  await page.keyboard.press("ArrowRight");
  for (const axis of ["X", "Y", "Z"]) await page.getByLabel(`Center ${axis}`).fill("0");
  await page.getByLabel("Radius").fill("0.62");
  await page.getByRole("button", { name: "Preview Crop" }).click();
  await page.getByText(/preview points selected/).waitFor();
  await page.getByLabel("Shape").selectOption("cylinder");
  await page.getByLabel("Height").fill("0.7");
  await page.getByLabel("Vertical axis").selectOption("y");
  await page.getByRole("button", { name: "Preview Crop" }).click();
  await page.getByText(/preview points selected/).waitFor();
  await page.getByRole("button", { name: "Export PLY" }).click();
  await page.getByText(/points exported/).waitFor({ timeout: 30_000 });

  async function downloadFrom(label) {
    const result = page.waitForEvent("download");
    await page.getByRole("button", { name: label, exact: true }).click();
    return readFile(await (await result).path());
  }
  const output = await downloadFrom("Download PLY");
  assert.ok(output.toString("ascii", 0, 100).startsWith("ply\nformat binary_little_endian"));
  const selection = await downloadFrom("Download Selection JSON");
  const data = JSON.parse(selection);
  assert.equal(data.selection.shape, "cylinder");
  assert.equal(data.selection.axis, "y");
  const selected = points.filter(([x,y,z]) => Math.abs(y)<=.35 && Math.hypot(x,z)<=.62).length;
  assert.equal(data.selected_points, selected);
  await page.getByLabel("Radius").fill("1.5");
  await page.getByLabel("Load Selection JSON").setInputFiles({
    name: "selection.json", mimeType: "application/json", buffer: selection,
  });
  await page.getByText("Selection loaded. Preview or export the crop again.").waitFor();
  assert.equal(await page.getByLabel("Radius").inputValue(), "0.62");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("link", { name: "LiDAR Cropper" }).click();
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  assert.deepEqual(failures, []);
  console.log(`PASS: WebGL, orbit/pan/zoom, picking, preview, cylinder export (${selected} points), JSON replay, mobile`);
} finally {
  await browser.close();
}
