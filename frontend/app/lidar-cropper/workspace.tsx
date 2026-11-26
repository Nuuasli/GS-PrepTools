"use client";

import { type ChangeEvent, type DragEvent, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Box, Crosshair, Download, Focus, FolderOpen, RotateCcw } from "lucide-react";
import {
  cancelLidarJob, closePointCloud, downloadLidarAsset, inspectPointCloud, isBusy, lidarLimits,
  readCloudPreview, readLidarJob, readLidarPreviewCount, regionSchema, requestCropPreview, selectionFileSchema,
  startLidarExport, uploadPointCloud, type DisplayMode, type Format, type Quality, type Region,
  type Session, type SourceInfo, type XYZ,
} from "@/services/lidar";

const Viewer = dynamic(() => import("./viewer"), {
  ssr: false,
  loading: () => <div className="absolute inset-0 grid place-content-center text-sm text-white/70">Loading viewer…</div>,
});

const field = "w-full min-w-0 rounded-lg border border-border bg-card px-2.5 py-2 text-sm disabled:opacity-55";
const label = "grid gap-1.5 text-xs font-medium text-muted-foreground";
const button = "secondary-action px-3 disabled:opacity-45";
const number = new Intl.NumberFormat("en-US");
const axes = ["X", "Y", "Z"] as const;
const formats: Format[] = ["las", "laz", "ply"];
const qualities: { value: Quality; text: string }[] = [
  { value: "draft", text: "Draft · up to 25,000" },
  { value: "standard", text: "Standard · up to 100,000" },
  { value: "high", text: "High · up to 250,000" },
];

type RegionDraft = {
  shape: Region["shape"];
  center: [string, string, string];
  radius: string;
  height: string;
  axis: Region["axis"];
};

function initialDraft(info: SourceInfo): RegionDraft {
  const spans = info.max_xyz.map((value, index) => value - info.min_xyz[index]);
  const radius = Number(((Math.max(...spans) || 1) / 4).toPrecision(5));
  return {
    shape: "sphere",
    center: xyzStrings(info.min_xyz.map((value, index) => value + spans[index] / 2) as XYZ),
    radius: String(radius), height: String(radius * 2), axis: "z",
  };
}

function xyzStrings(coordinates: XYZ): RegionDraft["center"] {
  return coordinates.map(String) as RegionDraft["center"];
}

function parseDraft(draft: RegionDraft | null) {
  if (!draft || [...draft.center, draft.radius].some((value) => !value.trim())) return null;
  const result = regionSchema.safeParse({
    ...draft, center: draft.center.map(Number), radius: Number(draft.radius),
    height: draft.shape === "cylinder" ? Number(draft.height) : null,
  });
  return result.success ? result.data : null;
}

function formatBytes(bytes: number) {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GiB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${bytes} bytes`;
}

export default function LidarWorkspace() {
  const [session, setSession] = useState<Session | null>(null);
  const [draft, setDraft] = useState<RegionDraft | null>(null);
  const [displayChoice, setDisplay] = useState<DisplayMode | null>(null);
  const [quality, setQuality] = useState<Quality>("standard");
  const [pointSize, setPointSize] = useState(2);
  const [picking, setPicking] = useState(false);
  const [formatChoice, setFormat] = useState<Format | null>(null);
  const [acceptDerivative, setAcceptDerivative] = useState(false);
  const [cameraCommand, setCameraCommand] = useState<{ id: number; action: "fit" | "reset" }>({ id: 0, action: "fit" });
  const [upload, setUpload] = useState<{ name: string; percent: number } | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [download, setDownload] = useState(false);
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const uploadRequest = useRef<XMLHttpRequest | null>(null);
  const dragDepth = useRef(0);
  useEffect(() => () => { uploadRequest.current?.abort(); }, []);

  const config = useQuery({ queryKey: ["lidar-limits"], queryFn: ({ signal }) => lidarLimits(signal), retry: false });
  const inspection = useQuery({
    queryKey: ["lidar-source", session?.id],
    queryFn: ({ signal }) => inspectPointCloud(session!, signal),
    enabled: Boolean(session),
    refetchInterval: ({ state }) => isBusy(state.data) ? 500 : false,
    refetchOnWindowFocus: false,
  });
  const info = inspection.data?.result ?? null;
  const baseDraft = useMemo(() => info ? initialDraft(info) : null, [info]);
  const currentDraft = draft ?? baseDraft;
  const region = useMemo(() => parseDraft(currentDraft), [currentDraft]);
  const display = displayChoice ?? (info?.has_rgb ? "rgb" : info?.has_intensity ? "intensity" : "elevation");
  const format = formatChoice ?? info?.format ?? "ply";
  const derivative = Boolean(info && info.format !== "ply" && format === "ply");
  const sessionReady = Boolean(session && info);

  const preview = useQuery({
    queryKey: ["lidar-preview", session?.id, quality],
    queryFn: ({ signal }) => readCloudPreview(session!, quality, info!.preview_counts[quality], signal),
    enabled: sessionReady, staleTime: Infinity, gcTime: 30_000, retry: false,
    placeholderData: (cloud, query) => query?.queryKey[1] === session?.id ? cloud : undefined,
  });
  const previewKey = JSON.stringify([session?.id, quality, region]);
  const cropPreview = useMutation({
    mutationFn: async ({ currentSession, currentRegion, key, currentQuality, count }: {
      currentSession: Session; currentRegion: Region; key: string; currentQuality: Quality; count: number;
    }) => {
      const { mask, countId } = await requestCropPreview(currentSession, currentQuality, currentRegion);
      if (mask.length !== count) throw new Error("Selection does not match the loaded preview.");
      return { mask, key, countId, selected: mask.reduce((sum, value) => sum + value, 0) };
    },
  });
  const previewResult = cropPreview.data?.key === previewKey ? cropPreview.data : null;
  const countId = previewResult?.countId;
  const countStatus = useQuery({
    queryKey: ["lidar-preview-count", session?.id, countId],
    queryFn: ({ signal }) => readLidarPreviewCount(session!, countId!, signal),
    enabled: Boolean(session && countId),
    staleTime: Infinity, retry: 1, refetchOnWindowFocus: false,
    refetchInterval: ({ state }) => state.status !== "error" && isBusy(state.data) ? 500 : false,
  });
  const fullCropCount = previewResult && previewResult.mask.length === info?.point_count
    ? previewResult.selected : countStatus.data?.result?.point_count;
  const isCounting = countId && !countStatus.isError && (countStatus.isPending || isBusy(countStatus.data));
  const exportCrop = useMutation({
    mutationFn: () => startLidarExport(session!, inspection.data!.sha256, region!, format, acceptDerivative),
  });
  const jobId = exportCrop.data?.id;
  const jobStatus = useQuery({
    queryKey: ["lidar-job", session?.id, jobId],
    queryFn: ({ signal }) => readLidarJob(session!, jobId!, signal),
    enabled: Boolean(session && jobId),
    initialData: exportCrop.data, initialDataUpdatedAt: 0,
    refetchInterval: ({ state }) => isBusy(state.data) ? 500 : false,
    refetchOnWindowFocus: false,
  });
  const job = jobStatus.data;
  const working = exportCrop.isPending || isBusy(job);
  const cancel = useMutation({
    mutationFn: () => cancelLidarJob(session!, jobId!),
    onSuccess: () => jobStatus.refetch(),
  });
  const busy = Boolean(upload || inspection.isPending && session || isBusy(inspection.data) || working);
  const blocked = config.data?.available === false;
  const errorText = error || inspection.error?.message || inspection.data?.error || preview.error?.message ||
    cropPreview.error?.message || exportCrop.error?.message || jobStatus.error?.message || job?.error || cancel.error?.message;

  function edit(values: Partial<RegionDraft>) {
    if (!currentDraft) return;
    setDraft({ ...currentDraft, ...values });
    setNotice("");
  }

  async function openFile(file: File) {
    if (busy || blocked || uploadRequest.current) return;
    setError(""); setNotice("");
    if (!/\.(ply|las|laz)$/i.test(file.name) || !file.size) {
      setError("Choose a non-empty PLY, LAS, or LAZ file.");
      return;
    }
    if (config.data && file.size > config.data.max_upload_bytes) {
      setError(`Maximum upload size is ${formatBytes(config.data.max_upload_bytes)}.`);
      return;
    }
    const xhr = new XMLHttpRequest();
    uploadRequest.current = xhr;
    setUpload({ name: file.name, percent: 0 });
    try {
      const opened = await uploadPointCloud(file, (percent) => setUpload({ name: file.name, percent }), xhr);
      if (session) void closePointCloud(session).catch(() => {});
      exportCrop.reset(); cropPreview.reset(); cancel.reset();
      setSession(opened); setDraft(null);
      setDisplay(null); setFormat(null); setAcceptDerivative(false); setPicking(false);
      setCameraCommand({ id: 0, action: "fit" });
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") setNotice("Upload cancelled.");
      else setError(cause instanceof Error ? cause.message : "Could not open the file.");
    } finally {
      uploadRequest.current = null;
      setUpload(null);
    }
  }

  function handleFileSelect(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (file) void openFile(file);
  }

  function handleDragEnter(event: DragEvent<HTMLDivElement>) {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    dragDepth.current++;
    setIsDraggingFile(true);
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = busy || blocked ? "none" : "copy";
  }

  function handleDragLeave() {
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (!dragDepth.current) setIsDraggingFile(false);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    const { files, types } = event.dataTransfer;
    if (!files.length && !types.includes("Files")) return;
    event.preventDefault();
    dragDepth.current = 0;
    setIsDraggingFile(false);
    if (busy || blocked || uploadRequest.current) return;
    if (files.length !== 1) {
      setNotice("");
      setError("Drop one PLY, LAS, or LAZ file at a time.");
      return;
    }
    void openFile(files[0]);
  }

  async function replaySelection(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !inspection.data || !info) return;
    setError(""); setNotice("");
    try {
      if (file.size > 65_536) throw new Error("Selection JSON exceeds 64 KiB.");
      const data = selectionFileSchema.safeParse(JSON.parse(await file.text()));
      if (!data.success) throw new Error("Choose a selection JSON exported by the web LiDAR Cropper.");
      if (data.data.source_sha256 !== inspection.data.sha256) throw new Error("Selection SHA-256 does not match this source.");
      const { selection, output_format, accept_derivative } = data.data;
      setDraft({ ...selection, center: xyzStrings(selection.center), radius: String(selection.radius),
        height: String(selection.height ?? selection.radius * 2) });
      setFormat(output_format); setAcceptDerivative(accept_derivative); setPicking(false);
      cropPreview.reset();
      setNotice("Selection loaded. Preview or export the crop again.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load this selection.");
    }
  }

  async function saveAsset(asset: "output" | "selection") {
    if (!session || !jobId) return;
    setError(""); setDownload(true);
    try { await downloadLidarAsset(session, jobId, asset); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "Download could not start."); }
    finally { setDownload(false); }
  }

  const units = info?.axis_units.filter(Boolean);
  const unitsLabel = units?.length ? [...new Set(units)].join(", ") : "Source units unknown";

  return (
    <div className="workspace-page">
      <div className="w-full">
        <div className="page-heading">
          <div>
            <h1>LiDAR Cropper</h1>
            <p className="page-heading-description">Pick a center in a point cloud and export the points inside a sphere or cylinder.</p>
          </div>
          <input ref={fileInput} type="file" accept=".ply,.las,.laz" className="sr-only" tabIndex={-1}
            aria-label="Point cloud file" onChange={handleFileSelect} />
          <button type="button" className="primary-action shrink-0 px-4 disabled:opacity-50"
            onClick={() => fileInput.current?.click()} disabled={busy || blocked}>
            <FolderOpen size={18} /> Open File
          </button>
        </div>

        {blocked && <p className="mb-4 rounded-lg border border-border bg-card p-4 text-sm">Install the LiDAR backend requirements and restart FastAPI to open a point cloud.</p>}
        {config.isError && !session && <p className="mb-4 text-sm text-muted-foreground">Could not reach the LiDAR backend. Check that FastAPI is running.</p>}
        {errorText && <p role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{errorText}</p>}
        {notice && <p role="status" className="mb-4 rounded-lg border border-border bg-card p-3 text-sm">{notice}</p>}
        {upload && (
          <div className="research-card mb-4 flex items-center gap-4 p-4" role="status">
            <div className="min-w-0 flex-1">
              <p className="mb-2 truncate text-sm font-semibold">Uploading {upload.name} · {upload.percent}%</p>
              <progress className="w-full accent-primary" max={100} value={upload.percent} aria-label="Upload progress" />
            </div>
            <button type="button" className={button} onClick={() => uploadRequest.current?.abort()}>Cancel upload</button>
          </div>
        )}
        {(session && inspection.isPending || isBusy(inspection.data)) && (
          <p role="status" className="mb-4 rounded-lg border border-border bg-card p-3 text-sm">
            Inspecting point cloud · {inspection.data?.progress ?? 0}%
          </p>
        )}

        {info && <div className="mb-4 flex flex-wrap items-center justify-between gap-2 px-1 text-xs text-muted-foreground">
          <span className="min-w-0 break-all text-sm font-semibold text-foreground">{inspection.data?.filename}</span>
          <span>{info.classification} · {number.format(info.point_count)} points · {unitsLabel}</span>
        </div>}

        <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_338px]">
          <section aria-label="Point cloud viewer" className="research-card min-w-0 overflow-hidden">
            <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
              <button type="button" className={button} disabled={!preview.data}
                onClick={() => setCameraCommand({ id: cameraCommand.id + 1, action: "reset" })}><RotateCcw size={15} /> Reset Camera</button>
              <button type="button" className={button} disabled={!preview.data}
                onClick={() => setCameraCommand({ id: cameraCommand.id + 1, action: "fit" })}><Focus size={15} /> Fit to Data</button>
              <button type="button" className={`${button} ml-auto aria-pressed:bg-soft-accent aria-pressed:text-primary`}
                aria-pressed={picking} disabled={!preview.data || preview.isPlaceholderData || working}
                onClick={() => setPicking(!picking)}><Crosshair size={15} /> Pick Center</button>
            </div>
            <div className="relative h-[clamp(360px,60svh,600px)] bg-[#202020] sm:h-[clamp(480px,64svh,720px)] xl:h-[max(560px,72svh)]"
              onDragEnter={handleDragEnter} onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop}>
              {info && preview.data ? <Viewer key={session?.id} cloud={preview.data} info={info} display={display}
                pointSize={pointSize} picking={picking}
                onPick={(center) => {
                  edit({ center: xyzStrings(center) });
                  setPicking(false);
                  setNotice("Center picked from the preview. This point is now the orbit pivot.");
                }}
                region={region} mask={previewResult?.mask} hideOutline={cropPreview.isPending || Boolean(previewResult)}
                cameraCommand={cameraCommand} /> :
                <div className="absolute inset-0 grid place-content-center px-8 text-center text-white/70">
                  <Box className="mx-auto mb-3 text-[#d17058]" size={28} aria-hidden="true" />
                  <p className="text-sm">{sessionReady && preview.isFetching ? "Loading preview…" :
                    "Drop a PLY, LAS, or LAZ file here, or use Open File."}</p>
                  {config.data && <p className="mt-1 text-xs text-white/55">Maximum upload {formatBytes(config.data.max_upload_bytes)}</p>}
                </div>}
              <div className="pointer-events-none absolute inset-x-3 top-3 flex flex-wrap items-start gap-2">
                {picking && preview.data && <p role="status" className="rounded bg-black/70 px-3 py-2 text-xs text-white">
                  Select a point to set the crop center and orbit pivot.
                </p>}
                {info && <div role="status" aria-label="Canvas point count"
                  className="ml-auto rounded-md border border-white/15 bg-black/75 px-3 py-2 text-right text-xs text-white">
                  <strong className="text-sm tabular-nums">{number.format(
                    previewResult ? fullCropCount ?? previewResult.selected : info.point_count,
                  )}</strong>{" "}
                  {previewResult ? fullCropCount === undefined ? "sampled points in crop" : "points in crop" : "source points"}
                  {previewResult && <p className="mt-0.5 text-white/75">
                    {fullCropCount !== undefined ? `of ${number.format(info.point_count)} source points` :
                      isCounting ? "Counting all points…" : "Full count unavailable"}
                  </p>}
                </div>}
              </div>
              {isDraggingFile && <div role="status"
                className="pointer-events-none absolute inset-0 grid place-content-center border-2 border-dashed border-[#dc7459] bg-black/75 px-6 text-center text-sm font-semibold text-white">
                {blocked ? "LiDAR upload is unavailable." : busy ? "Wait for the current operation to finish." :
                  "Drop to open your point cloud"}
              </div>}
            </div>
            <div className="grid gap-3 border-t border-border p-3 sm:grid-cols-3">
              <label className={label}>Color
                <select className={field} value={display} disabled={!info} onChange={(event) => setDisplay(event.target.value as DisplayMode)}>
                  <option value="elevation">Elevation</option>
                  <option value="intensity" disabled={!info?.has_intensity}>Intensity</option>
                  <option value="rgb" disabled={!info?.has_rgb}>RGB</option>
                </select>
              </label>
              <label className={label}>Preview quality
                <select className={field} value={quality} disabled={!info} onChange={(event) => setQuality(event.target.value as Quality)}>
                  {qualities.map((item) => <option key={item.value} value={item.value}>{item.text}</option>)}
                </select>
              </label>
              <label className={label}>Point size · {pointSize} px
                <input type="range" min={1} max={8} step={1} value={pointSize} onChange={(event) => setPointSize(Number(event.target.value))}
                  disabled={!info} className="h-9 w-full accent-primary" aria-label="Point size" />
              </label>
            </div>
            {preview.data && (
              <p className="px-3 pb-3 text-xs text-muted-foreground">
                {preview.isPlaceholderData ? "Loading new preview quality…" :
                  `${number.format(preview.data.count)} displayed · Drag to orbit, right-drag to pan, scroll to zoom.`}
              </p>
            )}
          </section>

          <aside className="grid min-w-0 gap-4 sm:grid-cols-2 xl:grid-cols-1">
            <section className="research-card min-w-0 p-4" aria-labelledby="crop-region">
              <h2 id="crop-region" className="mb-3 text-base font-semibold">Crop region</h2>
              <fieldset className="grid gap-3" disabled={!currentDraft || working}>
                <label className={label}>Shape
                  <select className={field} value={currentDraft?.shape ?? "sphere"} onChange={(event) => edit({ shape: event.target.value as Region["shape"] })}>
                    <option value="sphere">Sphere</option>
                    <option value="cylinder">Cylinder</option>
                  </select>
                </label>
                <fieldset className="min-w-0">
                  <legend className="mb-1 text-xs font-medium text-muted-foreground">Center XYZ</legend>
                  <div className="grid gap-1.5">
                    {axes.map((axis, index) => <label className="grid grid-cols-[16px_minmax(0,1fr)] items-center gap-2 text-xs font-medium text-muted-foreground" key={axis}>{axis}
                      <input className={field} aria-label={`Center ${axis}`} type="number" step="any"
                        value={currentDraft?.center[index] ?? ""}
                        onChange={(event) => {
                          if (!currentDraft) return;
                          const center = [...currentDraft.center] as RegionDraft["center"];
                          center[index] = event.target.value;
                          edit({ center });
                        }} />
                    </label>)}
                  </div>
                </fieldset>
                <label className={label}>Radius
                  <input className={field} type="number" step="any" value={currentDraft?.radius ?? ""} onChange={(event) => edit({ radius: event.target.value })} />
                </label>
                {currentDraft?.shape === "cylinder" && <div className="grid grid-cols-2 gap-2">
                  <label className={label}>Height
                    <input className={field} type="number" step="any" value={currentDraft.height} onChange={(event) => edit({ height: event.target.value })} />
                  </label>
                  <label className={label}>Vertical axis
                    <select className={field} value={currentDraft.axis} onChange={(event) => edit({ axis: event.target.value as Region["axis"] })}>
                      {axes.map((axis) => <option key={axis} value={axis.toLowerCase()}>{axis}</option>)}
                    </select>
                  </label>
                </div>}
              </fieldset>
              <p className="mt-2 text-xs text-muted-foreground">{unitsLabel}. {currentDraft?.shape === "cylinder" && "Height is centered on the selected axis."}</p>
              {currentDraft && !region && <p className="mt-1 text-xs text-destructive">Enter finite coordinates and positive dimensions.</p>}
              <button type="button" className={`${button} mt-3 w-full`}
                disabled={!previewResult && (!session || !region || !preview.data || preview.isPlaceholderData || cropPreview.isPending || working)}
                onClick={() => {
                  if (previewResult) {
                    cropPreview.reset();
                    return;
                  }
                  if (session && region && preview.data) cropPreview.mutate({
                    currentSession: session, currentRegion: region, key: previewKey, currentQuality: quality, count: preview.data.count,
                  });
                }}>{previewResult ? "Exit Preview" : cropPreview.isPending ? "Calculating preview…" : "Preview Crop"}</button>
              {previewResult && <p role="status" className="mt-2 text-xs font-medium text-primary">
                {number.format(previewResult.selected)} of {number.format(previewResult.mask.length)} preview points selected.
              </p>}
            </section>

            <section className="research-card min-w-0 p-4" aria-labelledby="crop-export">
              <h2 id="crop-export" className="mb-3 text-base font-semibold">Full-resolution export</h2>
              <label className={label}>Output format
                <select className={field} value={format} disabled={!info || working}
                  onChange={(event) => { setFormat(event.target.value as Format); setAcceptDerivative(false); }}>
                  {formats.map((item) => <option key={item} value={item}
                    disabled={info ? info.format === "ply" ? item !== "ply" : item === "ply" && !info.ply_derivative : false}>
                    {item.toUpperCase()}
                  </option>)}
                </select>
              </label>
              {derivative && <label className="mt-2 flex items-start gap-2 text-xs leading-5 text-muted-foreground">
                <input type="checkbox" className="mt-1 accent-primary" checked={acceptDerivative} disabled={working}
                  onChange={(event) => setAcceptDerivative(event.target.checked)} />
                Export a derived PLY. PLY cannot carry the native LAS header or CRS.
              </label>}
              <button type="button" className="primary-action mt-3 w-full px-3 disabled:opacity-45"
                disabled={!info || !region || working || upload !== null || derivative && !acceptDerivative}
                onClick={() => { setError(""); setNotice(""); setPicking(false); cancel.reset(); exportCrop.mutate(); }}>
                Export {format.toUpperCase()}
              </button>
              <label className={`mt-2 flex cursor-pointer items-center justify-center rounded-md p-2 text-xs font-medium text-muted-foreground focus-within:outline-2 focus-within:outline-primary ${!info || working ? "opacity-45" : ""}`}>
                Load Selection JSON
                <input type="file" className="sr-only" accept=".json,application/json" aria-label="Load Selection JSON"
                  disabled={!info || working} onChange={replaySelection} />
              </label>
              {job && <div className="mt-3 grid gap-2 border-t border-border pt-3">
                <p role="status" className="text-sm font-medium">
                  {job.status === "completed" && job.result ? `${number.format(job.result.point_count)} points exported · ${formatBytes(job.result.size)}` :
                    job.status === "cancelled" ? "Crop cancelled." :
                    job.status === "failed" ? "Export failed." : job.cancel_requested ? "Cancelling crop…" : `Exporting crop · ${job.progress}%`}
                </p>
                {isBusy(job) && <>
                  <progress className="w-full accent-primary" value={job.progress} max={100} aria-label="Export progress" />
                  <button type="button" className={button} disabled={cancel.isPending || job.cancel_requested}
                    onClick={() => cancel.mutate()}>Cancel crop</button>
                </>}
                {job.status === "completed" && <>
                  <button type="button" className={button} disabled={download} onClick={() => void saveAsset("output")}>
                    <Download size={16} /> Download {job.result?.output_format.toUpperCase()}
                  </button>
                  <button type="button" className={button} disabled={download} onClick={() => void saveAsset("selection")}>
                    Download Selection JSON
                  </button>
                </>}
              </div>}
            </section>
          </aside>
        </div>
      </div>
    </div>
  );
}
