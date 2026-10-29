"use client";

import Link from "next/link";
import { ChangeEvent, useMemo, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  Download,
  FolderOpen,
  ImageDown,
  Loader2,
  Play,
  RotateCcw,
  SearchCheck,
  TriangleAlert,
} from "lucide-react";
import {
  deleteImageDownscaleJob,
  getImageDownscaleManifestUrl,
  getImageDownscaleStatus,
  getImageDownscaleSummaryUrl,
  getImageDownscaleZipUrl,
  preflightImageDownscale,
  preflightLocalImageDownscale,
  startImageDownscale,
} from "@/services/api";
import type {
  DownscaleInputMode,
  DownscaleJobResponse,
} from "@/types";

const SUPPORTED_EXTENSIONS = new Set(["jpg", "jpeg", "png"]);

interface SelectedDataset {
  name: string;
  images: number;
}

interface FolderSelection {
  files: File[];
  relativePaths: string[];
  rootName: string;
  datasets: SelectedDataset[];
  supportedImages: number;
  ignoredFiles: number;
}

function isSupportedImage(path: string): boolean {
  const extension = path.split(".").pop()?.toLowerCase() ?? "";
  return SUPPORTED_EXTENSIONS.has(extension);
}

function normalizeFolderSelection(
  list: FileList,
  mode: Exclude<DownscaleInputMode, "local">
): FolderSelection {
  const files = Array.from(list);
  if (files.length === 0) throw new Error("The selected folder is empty.");

  const rawParts = files.map((file) => {
    const relativePath = file.webkitRelativePath || file.name;
    return relativePath.split("/").filter(Boolean);
  });
  const firstRoot = rawParts[0][0];
  const hasDirectoryRoot =
    rawParts[0].length > 1 &&
    rawParts.every((parts) => parts.length > 1 && parts[0] === firstRoot);
  if (mode === "root" && !hasDirectoryRoot) {
    throw new Error(
      "This browser did not preserve directory paths. Use a browser with directory upload support."
    );
  }

  const rootName = hasDirectoryRoot ? firstRoot : "selected_folder";
  const relativePaths = rawParts.map((parts) =>
    (hasDirectoryRoot ? parts.slice(1) : parts).join("/")
  );
  const expectedDepth = mode === "root" ? 2 : 1;
  const nested = relativePaths.find(
    (path) =>
      isSupportedImage(path) &&
      path.split("/").filter(Boolean).length !== expectedDepth
  );
  if (nested) {
    const expected = mode === "root" ? "dataset/image" : "image";
    throw new Error(
      `Nested directories are not supported in this phase. Expected ${expected}, received: ${nested}`
    );
  }

  const counts = new Map<string, number>();
  let supportedImages = 0;
  relativePaths.forEach((path) => {
    if (!isSupportedImage(path)) return;
    supportedImages += 1;
    const dataset = mode === "root" ? path.split("/")[0] : rootName;
    counts.set(dataset, (counts.get(dataset) ?? 0) + 1);
  });
  if (supportedImages === 0) {
    throw new Error("No supported .jpg, .jpeg, or .png images were found.");
  }

  return {
    files,
    relativePaths,
    rootName,
    datasets: Array.from(counts, ([name, images]) => ({ name, images })).sort(
      (left, right) => left.name.localeCompare(right.name)
    ),
    supportedImages,
    ignoredFiles: files.length - supportedImages,
  };
}

const wait = (milliseconds: number) =>
  new Promise((resolve) => window.setTimeout(resolve, milliseconds));

export default function ImageDownscalePage() {
  const [inputMode, setInputMode] = useState<DownscaleInputMode>("single");
  const [selection, setSelection] = useState<FolderSelection | null>(null);
  const [localInputPath, setLocalInputPath] = useState("");
  const [localOutputPath, setLocalOutputPath] = useState("");
  const [quickSamples, setQuickSamples] = useState(2);
  const [resolutionMode, setResolutionMode] = useState<"full-hd" | "custom">(
    "full-hd"
  );
  const [customWidth, setCustomWidth] = useState(1920);
  const [customHeight, setCustomHeight] = useState(1080);
  const [job, setJob] = useState<DownscaleJobResponse | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isPreflighting, setIsPreflighting] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const maxWidth = resolutionMode === "full-hd" ? 1920 : customWidth;
  const maxHeight = resolutionMode === "full-hd" ? 1080 : customHeight;
  const isBusy = isPreflighting || isProcessing;
  const totalDetected = useMemo(
    () => selection?.datasets.reduce((sum, item) => sum + item.images, 0) ?? 0,
    [selection]
  );

  const clearJob = async () => {
    if (job && job.status !== "running") {
      await deleteImageDownscaleJob(job.job_id).catch(() => undefined);
    }
    setJob(null);
  };

  const reset = async () => {
    await clearJob();
    setSelection(null);
    setLocalInputPath("");
    setLocalOutputPath("");
    setQuickSamples(2);
    setUploadProgress(0);
    setError(null);
    const input = document.getElementById("image-folder-input") as HTMLInputElement | null;
    if (input) input.value = "";
  };

  const changeMode = async (mode: DownscaleInputMode) => {
    await reset();
    setInputMode(mode);
  };

  const handleFolder = (event: ChangeEvent<HTMLInputElement>) => {
    setError(null);
    setJob(null);
    if (!event.target.files || inputMode === "local") return;
    try {
      setSelection(normalizeFolderSelection(event.target.files, inputMode));
    } catch (caught) {
      setSelection(null);
      event.target.value = "";
      setError(caught instanceof Error ? caught.message : "Invalid folder selection");
    }
  };

  const runDryRun = async () => {
    if (inputMode === "local") {
      if (!localInputPath.trim() || !localOutputPath.trim()) {
        setError("Input Dataset Path and Output Dataset Path are required.");
        return;
      }
      if (!Number.isInteger(quickSamples) || quickSamples < 1) {
        setError("Quick Dry Run Samples Per Dataset must be a positive integer.");
        return;
      }
    } else if (!selection) {
      return;
    }
    if (maxWidth <= 0 || maxHeight <= 0) {
      setError("Maximum width and height must be greater than zero.");
      return;
    }
    await clearJob();
    setIsPreflighting(true);
    setUploadProgress(0);
    setError(null);
    try {
      const response =
        inputMode === "local"
          ? await preflightLocalImageDownscale(
              localInputPath.trim(),
              localOutputPath.trim(),
              maxWidth,
              maxHeight,
              quickSamples
            )
          : await preflightImageDownscale(
              selection!.files,
              selection!.relativePaths,
              inputMode,
              selection!.rootName,
              maxWidth,
              maxHeight,
              setUploadProgress
            );
      setJob(response);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Dry run failed");
    } finally {
      setIsPreflighting(false);
    }
  };

  const startBatch = async () => {
    if (!job?.can_process) return;
    setIsProcessing(true);
    setError(null);
    try {
      let status = await startImageDownscale(job.job_id);
      setJob(status);
      while (status.status === "running") {
        await wait(1000);
        status = await getImageDownscaleStatus(job.job_id);
        setJob(status);
      }
      if (status.status !== "completed") {
        throw new Error(status.error || "Batch downscale failed");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Batch downscale failed");
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <main className="flex-1 p-6 sm:p-10">
      <div className="mx-auto w-full max-w-5xl space-y-6 animate-fade-in">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <Link
              href="/"
              className="mb-3 inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              <ArrowLeft className="h-4 w-4" /> Back to Video Preparation
            </Link>
            <div className="flex items-center gap-3">
              <ImageDown className="h-8 w-8 text-primary" />
              <div>
                <h1 className="text-3xl font-bold">Image Downscale</h1>
                <p className="text-muted-foreground">
                  Standalone post-processing for already extracted images
                </p>
              </div>
            </div>
          </div>
          <div className="rounded-full border border-success/30 bg-success/10 px-4 py-2 text-xs font-medium text-success">
            Preserve aspect ratio · No upscale
          </div>
        </div>

        <section className="glass-card p-6 space-y-5">
          <div>
            <h2 className="text-lg font-semibold">Input Mode</h2>
            <p className="text-sm text-muted-foreground">
              Local Path reads trusted localhost filesystem paths without upload.
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            {(["single", "root", "local"] as DownscaleInputMode[]).map((mode) => (
              <label
                key={mode}
                className={`cursor-pointer rounded-xl border p-4 transition-colors ${
                  inputMode === mode
                    ? "border-primary bg-primary/10"
                    : "border-border bg-secondary/30 hover:border-primary/40"
                }`}
              >
                <input
                  type="radio"
                  name="input-mode"
                  className="mr-3 accent-primary"
                  checked={inputMode === mode}
                  disabled={isBusy}
                  onChange={() => void changeMode(mode)}
                />
                <span className="font-medium">
                  {mode === "single"
                    ? "Single Image Folder"
                    : mode === "root"
                      ? "Dataset Root Folder"
                      : "Local Path"}
                </span>
              </label>
            ))}
          </div>

          {inputMode === "local" ? (
            <div className="grid gap-4">
              <label className="grid gap-2 text-sm font-medium">
                Input Dataset Path
                <input
                  type="text"
                  value={localInputPath}
                  disabled={isBusy || Boolean(job)}
                  placeholder={String.raw`G:\DATA_PATUNG`}
                  onChange={(event) => setLocalInputPath(event.target.value)}
                  className="h-12 rounded-lg border border-border bg-secondary px-4 font-mono text-sm outline-none focus:border-primary disabled:opacity-50"
                />
              </label>
              <label className="grid gap-2 text-sm font-medium">
                Output Dataset Path
                <input
                  type="text"
                  value={localOutputPath}
                  disabled={isBusy || Boolean(job)}
                  placeholder={String.raw`D:\DATA_PATUNG_1080p`}
                  onChange={(event) => setLocalOutputPath(event.target.value)}
                  className="h-12 rounded-lg border border-border bg-secondary px-4 font-mono text-sm outline-none focus:border-primary disabled:opacity-50"
                />
              </label>
              <label className="grid gap-2 text-sm font-medium">
                Quick Dry Run Samples Per Dataset
                <input
                  type="number"
                  min={1}
                  step={1}
                  value={quickSamples}
                  disabled={isBusy || Boolean(job)}
                  onChange={(event) => setQuickSamples(Number(event.target.value))}
                  className="h-12 rounded-lg border border-border bg-secondary px-4 outline-none focus:border-primary disabled:opacity-50"
                />
              </label>
              <p className="text-xs text-muted-foreground">
                Trusted localhost mode. The backend reads and writes these paths directly;
                the browser does not access the drive.
              </p>
              <div className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
                Quick Dry Run inspects {quickSamples || 0} sampled image(s) per dataset.
                A full preflight of all images will run before processing.
              </div>
            </div>
          ) : (
            <>
              <button
                type="button"
                disabled={isBusy || Boolean(job)}
                onClick={() => document.getElementById("image-folder-input")?.click()}
                className="flex min-h-40 w-full flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border bg-secondary/20 p-6 text-center transition-colors hover:border-primary/50 hover:bg-primary/5 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <FolderOpen className="h-10 w-10 text-primary" />
                <div>
                  <p className="font-semibold">
                    {selection ? selection.rootName : "Choose a folder"}
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Supported images: .jpg, .jpeg, .png
                  </p>
                </div>
              </button>
              <input
                id="image-folder-input"
                type="file"
                multiple
                className="hidden"
                ref={(element) => {
                  if (element) {
                    element.setAttribute("webkitdirectory", "");
                    element.setAttribute("directory", "");
                  }
                }}
                onChange={handleFolder}
              />
            </>
          )}
        </section>

        {selection && (
          <section className="glass-card p-6 space-y-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold">Detected datasets</h2>
                <p className="text-sm text-muted-foreground">Root: {selection.rootName}</p>
              </div>
              <div className="text-right">
                <p className="text-2xl font-bold text-primary">{totalDetected}</p>
                <p className="text-xs text-muted-foreground">supported images</p>
              </div>
            </div>
            <div className="overflow-hidden rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead className="bg-secondary/70 text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 text-left font-medium">Dataset</th>
                    <th className="px-4 py-3 text-right font-medium">Images</th>
                  </tr>
                </thead>
                <tbody>
                  {selection.datasets.map((dataset) => (
                    <tr key={dataset.name} className="border-t border-border">
                      <td className="px-4 py-3 font-medium">{dataset.name}</td>
                      <td className="px-4 py-3 text-right">{dataset.images}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {selection.ignoredFiles > 0 && (
              <p className="text-sm text-warning">
                {selection.ignoredFiles} non-image file(s) will be ignored and reported.
              </p>
            )}
          </section>
        )}

        <section className="glass-card p-6 space-y-4">
          <div>
            <h2 className="text-lg font-semibold">Maximum Resolution</h2>
            <p className="text-sm text-muted-foreground">
              Images fit inside this bounding box without crop or stretch.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            <select
              value={resolutionMode}
              disabled={isBusy || Boolean(job)}
              onChange={(event) =>
                setResolutionMode(event.target.value as "full-hd" | "custom")
              }
              className="h-11 rounded-lg border border-border bg-secondary px-3 outline-none focus:border-primary"
            >
              <option value="full-hd">Full HD · 1920×1080</option>
              <option value="custom">Custom resolution</option>
            </select>
            <input
              type="number"
              aria-label="Maximum width"
              min={1}
              value={maxWidth}
              disabled={resolutionMode === "full-hd" || isBusy || Boolean(job)}
              onChange={(event) => setCustomWidth(Number(event.target.value))}
              className="h-11 rounded-lg border border-border bg-secondary px-3 outline-none focus:border-primary disabled:opacity-50"
            />
            <input
              type="number"
              aria-label="Maximum height"
              min={1}
              value={maxHeight}
              disabled={resolutionMode === "full-hd" || isBusy || Boolean(job)}
              onChange={(event) => setCustomHeight(Number(event.target.value))}
              className="h-11 rounded-lg border border-border bg-secondary px-3 outline-none focus:border-primary disabled:opacity-50"
            />
          </div>
        </section>

        {error && (
          <div className="flex gap-3 rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
            <TriangleAlert className="h-5 w-5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {job && (
          <section className="glass-card p-6 space-y-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="flex items-center gap-2 text-lg font-semibold">
                  <SearchCheck className="h-5 w-5 text-primary" />
                  {job.input_mode === "local" ? "Quick Dry Run" : "Dry Run"}
                </h2>
                <p className="text-sm text-muted-foreground">
                  {job.dataset_count} dataset(s) · {job.total_images} total image(s)
                  {job.input_mode === "local" && ` · ${job.total_sampled} sampled`}
                </p>
              </div>
              <span
                className={`rounded-full px-3 py-1 text-xs font-medium ${
                  job.can_process
                    ? "bg-success/10 text-success"
                    : "bg-destructive/10 text-destructive"
                }`}
              >
                {job.can_process
                  ? job.input_mode === "local"
                    ? "SAMPLE READY"
                    : "READY"
                  : job.input_mode === "local"
                    ? "SAMPLE ERROR"
                    : "BLOCKED"}
              </span>
            </div>
            {job.input_mode === "local" && (
              <div className="grid gap-3 rounded-lg border border-border bg-secondary/30 p-4 text-sm">
                <div>
                  <p className="text-xs text-muted-foreground">Input Path</p>
                  <p className="break-all font-mono">{job.input_path}</p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Output Path</p>
                  <p className="break-all font-mono">{job.output_path}</p>
                </div>
              </div>
            )}
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[640px] text-sm">
                <thead className="bg-secondary/70 text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 text-left font-medium">Dataset</th>
                    <th className="px-4 py-3 text-right font-medium">
                      {job.input_mode === "local" ? "Total Images" : "Images"}
                    </th>
                    {job.input_mode === "local" && (
                      <th className="px-4 py-3 text-right font-medium">Sampled</th>
                    )}
                    <th className="px-4 py-3 text-right font-medium">
                      {job.input_mode === "local" ? "Sample Resize" : "Resize"}
                    </th>
                    <th className="px-4 py-3 text-right font-medium">
                      {job.input_mode === "local" ? "Sample Unchanged" : "Unchanged"}
                    </th>
                    <th className="px-4 py-3 text-right font-medium">
                      {job.input_mode === "local" ? "Sample Errors" : "Corrupt"}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {job.datasets.map((dataset) => (
                    <tr key={dataset.dataset_id} className="border-t border-border">
                      <td className="px-4 py-3 font-medium">{dataset.dataset_name}</td>
                      <td className="px-4 py-3 text-right">{dataset.images}</td>
                      {job.input_mode === "local" && (
                        <td className="px-4 py-3 text-right">{dataset.sampled}</td>
                      )}
                      <td className="px-4 py-3 text-right">{dataset.resize}</td>
                      <td className="px-4 py-3 text-right">{dataset.unchanged}</td>
                      <td className="px-4 py-3 text-right">
                        {job.input_mode === "local" ? dataset.sample_errors : dataset.corrupt}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {job.input_mode === "local" && (
              <div className="grid gap-4">
                <div className="rounded-lg border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
                  Quick Dry Run inspects {job.samples_per_dataset} sampled image(s) per
                  dataset. It is not full dataset validation. A full preflight of all
                  images will run before processing.
                </div>
                {job.datasets.map((dataset) => (
                  <div
                    key={`${dataset.dataset_id}-samples`}
                    className="rounded-lg border border-border p-4"
                  >
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <p className="font-semibold">{dataset.dataset_name}</p>
                      <p className="text-xs text-muted-foreground">
                        {dataset.sampled} of {dataset.images} inspected
                      </p>
                    </div>
                    <div className="grid gap-2 sm:grid-cols-2">
                      {dataset.samples?.map((sample, index) => (
                        <div
                          key={sample.filename}
                          className="rounded-lg bg-secondary/50 p-3 text-sm"
                        >
                          <p className="font-medium">
                            Sample {index + 1}: {sample.filename}
                          </p>
                          {sample.error ? (
                            <p className="mt-1 text-destructive">Error: {sample.error}</p>
                          ) : (
                            <>
                              <p className="mt-1 text-muted-foreground">
                                Source: {sample.source_width}×{sample.source_height}
                              </p>
                              <p className="text-muted-foreground">
                                Planned: {sample.output_width}×{sample.output_height}
                              </p>
                              <p
                                className={
                                  sample.action === "resize"
                                    ? "text-primary"
                                    : "text-success"
                                }
                              >
                                Action: {sample.action}
                              </p>
                            </>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {job.corrupt_images.length > 0 && (
              <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-4">
                <p className="mb-2 font-medium text-destructive">
                  {job.input_mode === "local"
                    ? "Quick Dry Run sampled image errors:"
                    : "Actual batch is blocked by corrupt images:"}
                </p>
                {job.corrupt_images.map((item) => (
                  <p key={item.relative_path} className="font-mono text-xs text-destructive">
                    {item.relative_path} — {item.error || "CORRUPT IMAGE"}
                  </p>
                ))}
              </div>
            )}
            {job.ignored_files.length > 0 && (
              <p className="text-sm text-warning">
                Ignored non-image files: {job.ignored_files.length}
              </p>
            )}
          </section>
        )}

        {job?.status === "running" && (
          <section className="glass-card p-6 space-y-3">
            <div className="flex justify-between text-sm">
              <span>{job.current_dataset ? `Processing ${job.current_dataset}` : "Preparing batch"}</span>
              <span>{Math.round(job.progress)}%</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-secondary">
              <div
                className="h-full bg-gradient-to-r from-primary to-accent transition-all"
                style={{ width: `${job.progress}%` }}
              />
            </div>
          </section>
        )}

        {job?.status === "completed" && job.result && (
          <section className="glass-card p-6 space-y-5">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-7 w-7 text-success" />
              <div>
                <h2 className="text-xl font-semibold">Batch completed</h2>
                <p className="text-sm text-muted-foreground">
                  {job.result.datasets_processed} datasets · {job.result.total_images} images · {job.result.failed} failed
                </p>
              </div>
            </div>
            {job.input_mode === "local" && (
              <div className="rounded-lg border border-success/30 bg-success/10 p-4">
                <p className="font-medium text-success">Direct filesystem output ready</p>
                <p className="mt-1 break-all font-mono text-sm">{job.output_path}</p>
                <p className="mt-2 text-xs text-muted-foreground">
                  No ZIP download or extraction is required.
                </p>
              </div>
            )}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
              {[
                ["Datasets", job.result.datasets_processed],
                ["Total Images", job.result.total_images],
                ["Resized", job.result.resized],
                ["Unchanged", job.result.unchanged],
                ["Failed", job.result.failed],
              ].map(([label, value]) => (
                <div key={label} className="rounded-lg border border-border bg-secondary/30 p-3">
                  <p className="text-xs text-muted-foreground">{label}</p>
                  <p className="mt-1 text-xl font-semibold">{value}</p>
                </div>
              ))}
            </div>
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[640px] text-sm">
                <thead className="bg-secondary/70 text-muted-foreground">
                  <tr>
                    <th className="px-4 py-3 text-left">Dataset</th>
                    <th className="px-4 py-3 text-right">Input</th>
                    <th className="px-4 py-3 text-right">Resized</th>
                    <th className="px-4 py-3 text-right">Unchanged</th>
                    <th className="px-4 py-3 text-right">Output</th>
                    <th className="px-4 py-3 text-right">Status</th>
                    <th className="px-4 py-3 text-right">Manifest</th>
                  </tr>
                </thead>
                <tbody>
                  {job.result.datasets.map((dataset) => (
                    <tr key={dataset.dataset_id} className="border-t border-border">
                      <td className="px-4 py-3 font-medium">{dataset.dataset_name}</td>
                      <td className="px-4 py-3 text-right">{dataset.input}</td>
                      <td className="px-4 py-3 text-right">{dataset.resized}</td>
                      <td className="px-4 py-3 text-right">{dataset.unchanged}</td>
                      <td className="px-4 py-3 text-right">{dataset.output}</td>
                      <td className="px-4 py-3 text-right text-success">{dataset.status}</td>
                      <td className="px-4 py-3 text-right">
                        <a
                          href={getImageDownscaleManifestUrl(job.job_id, dataset.dataset_id)}
                          className="text-primary hover:underline"
                        >
                          CSV
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className={`grid gap-3 ${job.input_mode === "local" ? "" : "sm:grid-cols-2"}`}>
              {job.input_mode !== "local" && (
                <a
                  href={getImageDownscaleZipUrl(job.job_id)}
                  className="flex h-12 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-primary to-accent font-semibold text-primary-foreground"
                >
                  <Download className="h-5 w-5" /> Download All as ZIP
                </a>
              )}
              <a
                href={getImageDownscaleSummaryUrl(job.job_id)}
                className="flex h-12 items-center justify-center gap-2 rounded-xl border border-border bg-secondary font-semibold hover:border-primary/50"
              >
                <Download className="h-5 w-5" /> Download Batch Summary
              </a>
            </div>
          </section>
        )}

        <div className="grid gap-3 sm:grid-cols-2">
          <button
            type="button"
            disabled={
              isBusy ||
              (!selection && !job && !localInputPath && !localOutputPath)
            }
            onClick={() => void reset()}
            className="flex h-13 items-center justify-center gap-2 rounded-xl border border-border bg-secondary font-semibold transition-colors hover:border-destructive/50 hover:text-destructive disabled:cursor-not-allowed disabled:opacity-30"
          >
            <RotateCcw className="h-5 w-5" /> Reset
          </button>
          {!job || job.status === "preflight_ready" || job.status === "preflight_blocked" ? (
            job ? (
              <button
                type="button"
                disabled={!job.can_process || isBusy}
                onClick={() => void startBatch()}
                className="flex h-13 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-primary to-accent font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-30"
              >
                {isProcessing ? <Loader2 className="h-5 w-5 animate-spin" /> : <Play className="h-5 w-5" />}
                {job.input_mode === "local"
                  ? "Start Downscale (Full Preflight)"
                  : "Start Batch Downscale"}
              </button>
            ) : (
              <button
                type="button"
                disabled={
                  isBusy ||
                  (inputMode === "local"
                    ? !localInputPath.trim() ||
                      !localOutputPath.trim() ||
                      !Number.isInteger(quickSamples) ||
                      quickSamples < 1
                    : !selection)
                }
                onClick={() => void runDryRun()}
                className="flex h-13 items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-primary to-accent font-semibold text-primary-foreground disabled:cursor-not-allowed disabled:opacity-30"
              >
                {isPreflighting ? <Loader2 className="h-5 w-5 animate-spin" /> : <SearchCheck className="h-5 w-5" />}
                {isPreflighting
                  ? inputMode === "local"
                    ? "Inspecting samples..."
                    : `Uploading ${uploadProgress}%`
                  : inputMode === "local"
                    ? "Run Quick Dry Run"
                    : "Run Dry Run"}
              </button>
            )
          ) : (
            <button
              type="button"
              disabled
              className="flex h-13 items-center justify-center gap-2 rounded-xl bg-secondary font-semibold opacity-50"
            >
              {isProcessing && <Loader2 className="h-5 w-5 animate-spin" />}
              {job.status === "completed" ? "Completed" : "Processing batch"}
            </button>
          )}
        </div>
      </div>
    </main>
  );
}
