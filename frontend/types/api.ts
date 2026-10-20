/**
 * GS-Prep Frontend — TypeScript API Types
 *
 * Shared interfaces and enums for communication with the backend API.
 */

// ========================
// Enums
// ========================

export enum PipelineStep {
  UPLOAD = "upload",
  EXTRACT = "extract",
  BLUR = "blur",
  DUPLICATE = "duplicate",
  RESIZE = "resize",
  REPORT = "report",
}

export enum StepStatus {
  PENDING = "pending",
  RUNNING = "running",
  COMPLETED = "completed",
  FAILED = "failed",
}

export enum JobStatus {
  UPLOADED = "uploaded",
  RUNNING = "running",
  COMPLETED = "completed",
  FAILED = "failed",
}

// ========================
// API Response Types
// ========================

export interface HealthResponse {
  status: string;
  app_name: string;
  version: string;
  environment: string;
}

export interface VideoMetadata {
  filename: string;
  duration: number;
  fps: number;
  total_frames: number;
  width: number;
  height: number;
  codec: string;
  file_size: number;
  container?: ContainerMetadata | null;
  video_stream?: VideoStreamMetadata | null;
  audio_stream?: AudioStreamMetadata | null;
  integrity?: MediaIntegrityMetadata | null;
}

export interface ContainerMetadata {
  format_name?: string | null;
  format_long_name?: string | null;
  duration?: number | null;
  start_time?: number | null;
  bit_rate?: number | null;
  stream_count?: number | null;
}

export interface VideoStreamMetadata {
  stream_index?: number | null;
  codec_name?: string | null;
  codec_long_name?: string | null;
  profile?: string | null;
  level?: number | null;
  pixel_format?: string | null;
  bit_depth?: number | null;
  coded_width?: number | null;
  coded_height?: number | null;
  average_frame_rate?: number | null;
  nominal_frame_rate?: number | null;
  frame_count_source: string;
  duration_source: string;
  possible_variable_frame_rate: boolean;
  sample_aspect_ratio?: string | null;
  display_aspect_ratio?: string | null;
  rotation: number;
  bit_rate?: number | null;
  time_base?: string | null;
  color_range?: string | null;
  color_space?: string | null;
  color_transfer?: string | null;
  color_primaries?: string | null;
  field_order?: string | null;
}

export interface AudioStreamMetadata {
  present: boolean;
  stream_index?: number | null;
  codec_name?: string | null;
  codec_long_name?: string | null;
  profile?: string | null;
  sample_rate?: number | null;
  channels?: number | null;
  channel_layout?: string | null;
  bit_rate?: number | null;
}

export interface MediaIntegrityMetadata {
  sha256: string;
  metadata_source: string;
  warnings: string[];
}

export interface UploadResponse {
  job_id: string;
  video_metadata: VideoMetadata;
}

// ========================
// Processing Configuration
// ========================

export enum DuplicateMethod {
  ORB = "orb",
  SSIM = "ssim",
}

export interface ProcessingConfig {
  extraction_fps: number;
  jpeg_quality: number;
  blur_threshold: number;
  duplicate_threshold: number;
  duplicate_method: DuplicateMethod;
  resize_width: number;
  keep_intermediates: boolean;
}

export const RESIZE_OPTIONS = [
  { label: "Original Resolution", value: 0 },
  { label: "1080p (1920px)", value: 1920 },
  { label: "720p (1280px)", value: 1280 },
  { label: "480p (854px)", value: 854 },
];

// ========================
// Progress Tracking
// ========================

export interface StepProgress {
  step: PipelineStep;
  status: StepStatus;
  progress: number;
  message: string;
  processed?: number;
  total?: number;
}

export interface PipelineProgress {
  job_id: string;
  steps: StepProgress[];
  current_step: PipelineStep;
  overall_progress: number;
  status: JobStatus;
  error?: string;
}

// ========================
// Final Results
// ========================

export interface ExtractionResult {
  extraction_fps: number;
  total_frames: number;
  extracted_frames: number;
}

export interface BlurResult {
  blur_removed: number;
  remaining: number;
}

export interface DuplicateResult {
  duplicates_removed: number;
  remaining: number;
}

export interface ResizeResult {
  final_width: number;
  final_height: number;
}

export interface DatasetSummary {
  final_images: number;
}

export interface ProcessingResult {
  job_id: string;
  video_info: VideoMetadata;
  extraction: ExtractionResult;
  blur: BlurResult;
  duplicate: DuplicateResult;
  resize: ResizeResult;
  dataset_summary: DatasetSummary;
  processing_time: number;
  report_url: string;
  dataset_url: string;
  manifest_url?: string | null;
  preview_images: string[];
}
