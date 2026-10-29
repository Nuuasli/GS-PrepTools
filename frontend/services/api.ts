/**
 * GS-Prep Frontend — API Service Layer
 *
 * Centralized HTTP client for all backend communication.
 * Uses native fetch API with typed responses.
 */

import type {
  HealthResponse,
  UploadResponse,
  ProcessingConfig,
  PipelineProgress,
  ProcessingResult,
  DownscaleInputMode,
  DownscaleJobResponse,
} from "@/types";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";

/**
 * Generic fetch wrapper with error handling.
 */
async function apiFetch<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint}`;

  const response = await fetch(url, {
    ...options,
    headers: {
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(
      errorBody.detail ||
        errorBody.message ||
        `API Error: ${response.status} ${response.statusText}`
    );
  }

  return response.json() as Promise<T>;
}

// ========================
// Health
// ========================

export async function getHealthStatus(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>("/health");
}

// ========================
// Upload
// ========================

export async function uploadVideo(
  file: File,
  onProgress?: (progress: number) => void
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  // Use XMLHttpRequest for upload progress tracking
  return new Promise<UploadResponse>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/upload`);

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && onProgress) {
        const percent = Math.round((event.loaded / event.total) * 100);
        onProgress(percent);
      }
    });

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText));
        } catch {
          reject(new Error("Upload failed: invalid server response"));
        }
      } else {
        try {
          const body = JSON.parse(xhr.responseText);
          reject(new Error(body.detail || body.message || `Upload failed: ${xhr.status}`));
        } catch {
          reject(new Error(`Upload failed: ${xhr.status} ${xhr.statusText}`));
        }
      }
    });

    xhr.addEventListener("error", () => {
      reject(new Error("Upload failed: Network error"));
    });

    xhr.send(formData);
  });
}

// ========================
// Pipeline Processing
// ========================

export async function startPipeline(
  jobId: string,
  config: ProcessingConfig
): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(`/pipeline/${jobId}/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
}

export async function getPipelineProgress(
  jobId: string
): Promise<PipelineProgress> {
  return apiFetch<PipelineProgress>(`/pipeline/${jobId}/progress`);
}

export async function getPipelineResult(
  jobId: string
): Promise<ProcessingResult> {
  return apiFetch<ProcessingResult>(`/pipeline/${jobId}/result`);
}

// ========================
// Downloads
// ========================

export function getDatasetDownloadUrl(jobId: string): string {
  return `${API_BASE_URL}/pipeline/${jobId}/download/dataset`;
}

export function getReportDownloadUrl(jobId: string): string {
  return `${API_BASE_URL}/pipeline/${jobId}/download/report`;
}

export function getManifestDownloadUrl(jobId: string): string {
  return `${API_BASE_URL}/pipeline/${jobId}/download/manifest`;
}

export function getPreviewImageUrl(jobId: string, filename: string): string {
  return `${API_BASE_URL}/pipeline/${jobId}/preview/${filename}`;
}

export async function deleteJob(jobId: string): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(`/pipeline/${jobId}`, {
    method: "DELETE",
  });
}

// ========================
// Standalone Image Downscale
// ========================

export async function preflightImageDownscale(
  files: File[],
  relativePaths: string[],
  inputMode: DownscaleInputMode,
  rootName: string,
  maxWidth: number,
  maxHeight: number,
  onProgress?: (progress: number) => void
): Promise<DownscaleJobResponse> {
  const formData = new FormData();
  files.forEach((file, index) => {
    formData.append("files", file, file.name);
    formData.append("relative_paths", relativePaths[index]);
  });
  formData.append("input_mode", inputMode);
  formData.append("root_name", rootName);
  formData.append("max_width", String(maxWidth));
  formData.append("max_height", String(maxHeight));

  return new Promise<DownscaleJobResponse>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/image-downscale/preflight`);
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as DownscaleJobResponse);
        } catch {
          reject(new Error("Preflight failed: invalid server response"));
        }
        return;
      }
      try {
        const body = JSON.parse(xhr.responseText) as { detail?: string };
        reject(new Error(body.detail || `Preflight failed: ${xhr.status}`));
      } catch {
        reject(new Error(`Preflight failed: ${xhr.status} ${xhr.statusText}`));
      }
    });
    xhr.addEventListener("error", () => {
      reject(new Error("Preflight failed: network error"));
    });
    xhr.send(formData);
  });
}

export async function preflightLocalImageDownscale(
  inputPath: string,
  outputPath: string,
  maxWidth: number,
  maxHeight: number,
  samplesPerDataset: number
): Promise<DownscaleJobResponse> {
  return apiFetch<DownscaleJobResponse>("/image-downscale/local/preflight", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      input_path: inputPath,
      output_path: outputPath,
      max_width: maxWidth,
      max_height: maxHeight,
      samples_per_dataset: samplesPerDataset,
    }),
  });
}

export async function startImageDownscale(
  jobId: string
): Promise<DownscaleJobResponse> {
  return apiFetch<DownscaleJobResponse>(`/image-downscale/${jobId}/start`, {
    method: "POST",
  });
}

export async function getImageDownscaleStatus(
  jobId: string
): Promise<DownscaleJobResponse> {
  return apiFetch<DownscaleJobResponse>(`/image-downscale/${jobId}/status`);
}

export async function deleteImageDownscaleJob(
  jobId: string
): Promise<{ status: string }> {
  return apiFetch<{ status: string }>(`/image-downscale/${jobId}`, {
    method: "DELETE",
  });
}

export function getImageDownscaleZipUrl(jobId: string): string {
  return `${API_BASE_URL}/image-downscale/${jobId}/download/zip`;
}

export function getImageDownscaleSummaryUrl(jobId: string): string {
  return `${API_BASE_URL}/image-downscale/${jobId}/download/summary`;
}

export function getImageDownscaleManifestUrl(
  jobId: string,
  datasetId: string
): string {
  return `${API_BASE_URL}/image-downscale/${jobId}/download/manifest/${encodeURIComponent(datasetId)}`;
}
