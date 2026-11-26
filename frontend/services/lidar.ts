import { z } from "zod";
import { API_BASE_URL } from "@/services/api";

const root = `${API_BASE_URL}/lidar`;
export type XYZ = [number, number, number];
export type Quality = "draft" | "standard" | "high";
export type Format = "ply" | "las" | "laz";
export type DisplayMode = "rgb" | "intensity" | "elevation";
export interface Session { id: string; token: string }
type Status = "queued" | "running" | "completed" | "cancelled" | "failed";
interface Operation<T> { id: string; status: Status; progress: number; error: string | null; result: T | null }
export interface SourceInfo {
  format: Format;
  classification: string;
  point_count: number;
  min_xyz: XYZ;
  max_xyz: XYZ;
  attributes: string[];
  has_rgb: boolean;
  has_intensity: boolean;
  preview_counts: Record<Quality, number>;
  axis_units: string[];
  crs: string | null;
  ply_derivative: boolean;
}
export interface Source extends Operation<SourceInfo> { filename: string; size: number; sha256: string }
export interface Job extends Operation<{ point_count: number; output_format: Format; size: number }> {
  cancel_requested?: boolean;
}
export type PreviewCount = Operation<{ point_count: number }>;
export const regionSchema = z.object({
  shape: z.enum(["sphere", "cylinder"]),
  center: z.tuple([z.number(), z.number(), z.number()]),
  radius: z.number().positive(),
  height: z.number().positive().nullish(),
  axis: z.enum(["x", "y", "z"]),
}).refine((region) => region.shape === "sphere" || region.height != null);
export type Region = z.infer<typeof regionSchema>;
export const selectionFileSchema = z.object({
  schema_version: z.literal(1),
  source_sha256: z.string().regex(/^[a-f0-9]{64}$/),
  selection: regionSchema,
  output_format: z.enum(["ply", "las", "laz"]),
  accept_derivative: z.boolean(),
});

type Asset = "output" | "selection";
export const isBusy = (state?: { status: Status } | null) =>
  state?.status === "queued" || state?.status === "running";

function errorMessage(body: unknown, fallback: string) {
  if (!body || typeof body !== "object") return fallback;
  if ("detail" in body && typeof body.detail === "string") return body.detail;
  if ("message" in body && typeof body.message === "string") return body.message;
  if ("detail" in body && Array.isArray(body.detail))
    return body.detail.map((entry) => String(entry.msg ?? "Invalid request")).join(" ");
  return fallback;
}

async function request(path: string, options?: RequestInit, session?: Session) {
  const headers = new Headers(options?.headers);
  if (session) headers.set("Authorization", `Bearer ${session.token}`);
  const response = await fetch(`${root}${path}`, { ...options, headers, cache: "no-store" });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(errorMessage(body, `LiDAR request failed (${response.status}).`));
  }
  return response;
}

function post(body?: unknown): RequestInit {
  return body === undefined ? { method: "POST" } : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  };
}

const sourcePath = (session: Session) => `/sources/${session.id}`;

export async function lidarLimits(signal?: AbortSignal): Promise<{ available: boolean; max_upload_bytes: number }> {
  return (await request("/limits", { signal })).json();
}

export function uploadPointCloud(file: File, onProgress: (value: number) => void, xhr: XMLHttpRequest) {
  return new Promise<Session>((resolve, reject) => {
    xhr.open("POST", `${root}/sources`);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.setRequestHeader("X-Lidar-Filename", encodeURIComponent(file.name));
    xhr.setRequestHeader("X-Lidar-Size", String(file.size));
    xhr.responseType = "json";
    xhr.upload.onprogress = (event) => onProgress(Math.floor(event.loaded / file.size * 100));
    xhr.onload = () => xhr.status === 202 ? resolve(xhr.response) :
      reject(new Error(errorMessage(xhr.response, `Upload failed (${xhr.status}).`)));
    xhr.onerror = () => reject(new Error("Could not reach the LiDAR backend. Check that FastAPI is running."));
    xhr.onabort = () => reject(new DOMException("Upload cancelled.", "AbortError"));
    xhr.send(file);
  });
}

export async function inspectPointCloud(session: Session, signal?: AbortSignal): Promise<Source> {
  return (await request(sourcePath(session), { signal }, session)).json();
}

export async function closePointCloud(session: Session) {
  await request(sourcePath(session), { method: "DELETE" }, session);
}

export interface CloudPreview {
  count: number;
  xyz: Float64Array;
  display: Uint8Array;
}

export async function readCloudPreview(session: Session, quality: Quality, count: number, signal?: AbortSignal) {
  const response = await request(`${sourcePath(session)}/preview?quality=${quality}`, { signal }, session);
  const view = new DataView(await response.arrayBuffer());
  if (view.byteLength !== 28 * count) throw new Error("The preview size does not match its metadata.");
  const xyz = new Float64Array(count * 3);
  const display = new Uint8Array(count * 4);
  for (let i = 0; i < count; i++) {
    for (let axis = 0; axis < 3; axis++) xyz[i * 3 + axis] = view.getFloat64(i * 28 + axis * 8, true);
    for (let channel = 0; channel < 4; channel++) display[i * 4 + channel] = view.getUint8(i * 28 + 24 + channel);
  }
  return { count, xyz, display };
}

export async function requestCropPreview(session: Session, quality: Quality, selection: Region) {
  const response = await request(`${sourcePath(session)}/preview-crop`,
    post({ selection, quality, include_full_count: true }), session);
  return {
    mask: new Uint8Array(await response.arrayBuffer()),
    countId: response.headers.get("X-Lidar-Count-Id"),
  };
}

export async function readLidarPreviewCount(session: Session, countId: string, signal?: AbortSignal): Promise<PreviewCount> {
  return (await request(`${sourcePath(session)}/preview-count/${encodeURIComponent(countId)}`, { signal }, session)).json();
}

export async function startLidarExport(session: Session, sourceSha256: string, selection: Region,
  outputFormat: Format, acceptDerivative: boolean): Promise<Job> {
  const body = { source_sha256: sourceSha256, selection, output_format: outputFormat, accept_derivative: acceptDerivative };
  return (await request(`${sourcePath(session)}/jobs`, post(body), session)).json();
}

export async function readLidarJob(session: Session, job: string, signal?: AbortSignal): Promise<Job> {
  return (await request(`${sourcePath(session)}/jobs/${job}`, { signal }, session)).json();
}

export async function cancelLidarJob(session: Session, job: string): Promise<Job> {
  return (await request(`${sourcePath(session)}/jobs/${job}/cancel`, post(), session)).json();
}

export async function downloadLidarAsset(session: Session, job: string, asset: Asset) {
  const { ticket } = await (await request(`${sourcePath(session)}/jobs/${job}/download/${asset}`, post(), session)).json();
  const link = document.createElement("a");
  link.href = `${root}/downloads/${encodeURIComponent(ticket)}`;
  link.referrerPolicy = "no-referrer";
  document.body.append(link);
  link.click();
  link.remove();
}
