"use client";

/**
 * GS-Prep — Main Configuration & Upload Page
 *
 * This is the primary entry point where users:
 * 1. Upload a video file
 * 2. Configure extraction FPS, blur threshold, duplicate threshold, resize width
 * 3. Start the processing pipeline
 */

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Upload,
  Play,
  X,
  Settings2,
  Film,
  Sparkles,
  Loader2,
} from "lucide-react";
import { usePipelineStore } from "@/hooks/use-pipeline-store";
import { deleteJob, uploadVideo } from "@/services/api";
import { DuplicateMethod, RESIZE_OPTIONS } from "@/types";

export default function HomePage() {
  const router = useRouter();
  const {
    jobId,
    videoMetadata,
    videoFile,
    config,
    isProcessing,
    setVideoFile,
    setJobId,
    setVideoMetadata,
    updateConfig,
    setProcessing,
    updateStepProgress,
    reset,
  } = usePipelineStore();

  const [uploadProgress, setUploadProgress] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [isCancelling, setIsCancelling] = useState(false);

  const uploadFileInstantly = async (file: File) => {
    setIsUploading(true);
    setJobId(null);
    setVideoMetadata(null);
    setVideoFile(file);
    setError(null);
    setUploadProgress(0);
    
    try {
      updateStepProgress("upload" as never, {
        status: "running" as never,
        message: "Uploading video...",
      });

      const response = await uploadVideo(file, (progress) => {
        setUploadProgress(progress);
        updateStepProgress("upload" as never, { progress });
      });

      setJobId(response.job_id);
      setVideoMetadata(response.video_metadata);
      updateStepProgress("upload" as never, {
        status: "completed" as never,
        progress: 100,
        message: "Upload complete",
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
      updateStepProgress("upload" as never, {
        status: "failed" as never,
        message: "Upload failed",
      });
    } finally {
      setIsUploading(false);
    }
  };

  // --- Drag & Drop ---
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      const file = e.dataTransfer.files[0];
      if (file && file.type.startsWith("video/")) {
        uploadFileInstantly(file);
      } else {
        setError("Please upload a valid video file.");
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) {
        uploadFileInstantly(file);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []
  );

  // --- Process ---
  const handleProcess = async () => {
    if (!videoMetadata || !jobId) {
      setError("Please wait for the upload to complete before processing.");
      return;
    }
    if (
      config.extraction_fps < 1 ||
      config.extraction_fps > 30 ||
      config.jpeg_quality < 50 ||
      config.jpeg_quality > 100 ||
      config.blur_threshold < 10 ||
      config.blur_threshold > 500 ||
      config.duplicate_threshold < 0.5 ||
      config.duplicate_threshold > 0.99
    ) {
      setError("One or more processing settings are outside the allowed range.");
      return;
    }

    setProcessing(true);
    setError(null);
    router.push("/processing");
  };

  const handleCancel = async () => {
    if (isUploading || isProcessing || isCancelling) return;

    setIsCancelling(true);
    setError(null);

    try {
      if (jobId) {
        await deleteJob(jobId);
      }

      reset();
      setUploadProgress(0);
      setIsDragging(false);

      const fileInput = document.getElementById("file-input") as HTMLInputElement | null;
      if (fileInput) fileInput.value = "";
    } catch (err) {
      setError(
        err instanceof Error
          ? `Unable to cancel upload: ${err.message}`
          : "Unable to cancel upload. Please try again."
      );
    } finally {
      setIsCancelling(false);
    }
  };

  const formatFileSize = (bytes: number) => {
    if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
    if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
    return `${(bytes / 1024).toFixed(1)} KB`;
  };

  const formatBitRate = (bitsPerSecond?: number | null) => {
    if (!bitsPerSecond) return "N/A";
    if (bitsPerSecond >= 1_000_000) {
      return `${(bitsPerSecond / 1_000_000).toFixed(2)} Mbps`;
    }
    return `${(bitsPerSecond / 1000).toFixed(0)} Kbps`;
  };

  return (
    <main className="flex-1 flex items-center justify-center p-6">
      <div className="w-full max-w-2xl space-y-8 animate-fade-in">
        {/* Header */}
        <div className="text-center space-y-3">
          <div className="flex items-center justify-center gap-3">
            <Sparkles className="w-8 h-8 text-primary" />
            <h1 className="text-4xl font-bold tracking-tight bg-gradient-to-r from-primary to-accent bg-clip-text text-transparent">
              GS-Prep
            </h1>
          </div>
          <p className="text-muted-foreground text-lg">
            Gaussian Splatting Dataset Preparation Tool
          </p>
        </div>

        {/* Upload Zone */}
        <div
          className={`glass-card p-8 transition-all duration-300 cursor-pointer ${
            isDragging
              ? "border-primary/60 animate-pulse-glow"
              : "hover:border-primary/30"
          }`}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => document.getElementById("file-input")?.click()}
        >
          <input
            id="file-input"
            type="file"
            accept="video/*"
            className="hidden"
            onChange={handleFileSelect}
          />

          <div className="flex flex-col items-center gap-4 text-center">
            {videoFile || videoMetadata ? (
              <>
                <Film className="w-12 h-12 text-success" />
                <div>
                  <p className="text-lg font-semibold">
                    {videoFile?.name ?? videoMetadata?.filename}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {formatFileSize(videoFile?.size ?? videoMetadata?.file_size ?? 0)}
                  </p>
                </div>
              </>
            ) : (
              <>
                <Upload className="w-12 h-12 text-muted-foreground" />
                <div>
                  <p className="text-lg font-medium">
                    Drop your video here or click to browse
                  </p>
                  <p className="text-sm text-muted-foreground mt-1">
                    Supports MP4, AVI, MOV, MKV
                  </p>
                </div>
              </>
            )}
          </div>

          {videoFile && uploadProgress < 100 && uploadProgress > 0 && (
            <div className="mt-4">
              <div className="h-2 bg-secondary rounded-full overflow-hidden">
                <div
                  className="h-full bg-gradient-to-r from-primary to-accent rounded-full transition-all duration-300"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
              <p className="text-xs text-muted-foreground mt-1 text-center">
                Uploading... {uploadProgress}%
              </p>
            </div>
          )}
        </div>

        {/* Video Metadata Panel */}
        {(videoMetadata || isUploading) && (
          <div className="glass-card p-6 animate-fade-in border border-primary/20 bg-primary/5">
            <div className="flex items-center gap-2 text-lg font-semibold mb-4 text-primary">
              <Film className="w-5 h-5" />
              <span>Video Info</span>
            </div>
            
            {isUploading ? (
              <div className="flex flex-col items-center justify-center py-6 space-y-3">
                <Loader2 className="w-8 h-8 animate-spin text-primary" />
                <p className="text-sm text-muted-foreground animate-pulse">Extracting video metadata...</p>
              </div>
            ) : videoMetadata ? (
              <div className="space-y-4">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <div className="space-y-1">
                    <p className="text-xs text-muted-foreground uppercase tracking-wider">Resolution</p>
                    <p className="font-mono font-medium">{videoMetadata.width}x{videoMetadata.height}</p>
                  </div>
                  <div className="space-y-1">
                    <p className="text-xs text-muted-foreground uppercase tracking-wider">Original FPS</p>
                    <p className="font-mono font-medium">{videoMetadata.fps.toFixed(3)}</p>
                  </div>
                  <div className="space-y-1">
                    <p className="text-xs text-muted-foreground uppercase tracking-wider">Duration</p>
                    <p className="font-mono font-medium">{videoMetadata.duration.toFixed(3)}s</p>
                  </div>
                  <div className="space-y-1">
                    <p className="text-xs text-muted-foreground uppercase tracking-wider">Total Frames</p>
                    <p className="font-mono font-medium">{videoMetadata.total_frames}</p>
                  </div>
                </div>

                <details className="rounded-xl border border-border/60 bg-background/30 px-4 py-3">
                  <summary className="cursor-pointer text-sm font-medium text-primary">
                    Technical metadata
                  </summary>
                  <div className="mt-4 grid grid-cols-2 gap-4 text-sm md:grid-cols-4">
                    <div>
                      <p className="text-xs text-muted-foreground">Container</p>
                      <p className="font-mono break-words">
                        {videoMetadata.container?.format_name ?? "N/A"}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Video codec</p>
                      <p className="font-mono">
                        {videoMetadata.video_stream?.codec_name ?? videoMetadata.codec}
                        {videoMetadata.video_stream?.profile
                          ? ` (${videoMetadata.video_stream.profile})`
                          : ""}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Pixel format</p>
                      <p className="font-mono">
                        {videoMetadata.video_stream?.pixel_format ?? "N/A"}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Bitrate</p>
                      <p className="font-mono">
                        {formatBitRate(videoMetadata.container?.bit_rate)}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Aspect ratio</p>
                      <p className="font-mono">
                        {videoMetadata.video_stream?.display_aspect_ratio ?? "N/A"}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Rotation</p>
                      <p className="font-mono">
                        {videoMetadata.video_stream?.rotation ?? 0}°
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Audio</p>
                      <p className="font-mono">
                        {videoMetadata.audio_stream
                          ? `${videoMetadata.audio_stream.codec_name ?? "unknown"} / ${videoMetadata.audio_stream.channels ?? "?"} ch`
                          : "None"}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Metadata source</p>
                      <p className="font-mono">
                        {videoMetadata.integrity?.metadata_source ?? "legacy"}
                      </p>
                    </div>
                  </div>

                  {videoMetadata.video_stream?.possible_variable_frame_rate && (
                    <p className="mt-3 text-xs text-amber-400">
                      Possible variable frame rate detected; timestamps should be treated as authoritative.
                    </p>
                  )}
                  {!!videoMetadata.integrity?.warnings.length && (
                    <ul className="mt-3 space-y-1 text-xs text-amber-400">
                      {videoMetadata.integrity.warnings.map((warning) => (
                        <li key={warning}>• {warning}</li>
                      ))}
                    </ul>
                  )}
                  {videoMetadata.integrity?.sha256 && (
                    <p className="mt-3 break-all font-mono text-[11px] text-muted-foreground">
                      SHA-256: {videoMetadata.integrity.sha256}
                    </p>
                  )}
                </details>
              </div>
            ) : null}
          </div>
        )}

        {/* Config Section */}
        <div className="glass-card p-6 space-y-5">
          <div className="flex items-center gap-2 text-lg font-semibold">
            <Settings2 className="w-5 h-5 text-primary" />
            <span>Processing Configuration</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
            {/* Extraction FPS */}
            <div className="space-y-2">
              <label
                htmlFor="extraction-fps"
                className="text-sm font-medium text-muted-foreground"
              >
                Extraction FPS
              </label>
              <input
                id="extraction-fps"
                type="number"
                min={1}
                max={30}
                value={config.extraction_fps}
                onChange={(e) =>
                  updateConfig({ extraction_fps: Number(e.target.value) })
                }
                className="w-full h-10 px-3 rounded-lg bg-input border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-colors"
              />
            </div>

            {/* Blur Threshold */}
            <div className="space-y-2">
              <label
                htmlFor="blur-threshold"
                className="text-sm font-medium text-muted-foreground"
              >
                Blur Threshold
              </label>
              <input
                id="blur-threshold"
                type="number"
                min={10}
                max={500}
                value={config.blur_threshold}
                onChange={(e) =>
                  updateConfig({ blur_threshold: Number(e.target.value) })
                }
                className="w-full h-10 px-3 rounded-lg bg-input border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-colors"
              />
            </div>

            {/* Duplicate Threshold */}
            <div className="space-y-2">
              <label
                htmlFor="duplicate-threshold"
                className="text-sm font-medium text-muted-foreground"
              >
                Duplicate Threshold
              </label>
              <input
                id="duplicate-threshold"
                type="number"
                min={0.5}
                max={0.99}
                step={0.01}
                value={config.duplicate_threshold}
                onChange={(e) => {
                  const val = e.target.value.replace(",", ".");
                  const num = parseFloat(val);
                  if (!isNaN(num)) {
                    updateConfig({ duplicate_threshold: num });
                  }
                }}
                className="w-full h-10 px-3 rounded-lg bg-input border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-colors"
              />
            </div>

            {/* JPEG Quality */}
            <div className="space-y-2">
              <label
                htmlFor="jpeg-quality"
                className="text-sm font-medium text-muted-foreground"
              >
                JPEG Quality
              </label>
              <input
                id="jpeg-quality"
                type="number"
                min={50}
                max={100}
                value={config.jpeg_quality}
                onChange={(e) =>
                  updateConfig({ jpeg_quality: Number(e.target.value) })
                }
                className="w-full h-10 px-3 rounded-lg bg-input border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-colors"
              />
            </div>

            {/* Duplicate Method */}
            <div className="space-y-2">
              <label
                htmlFor="duplicate-method"
                className="text-sm font-medium text-muted-foreground"
              >
                Duplicate Method
              </label>
              <select
                id="duplicate-method"
                value={config.duplicate_method}
                onChange={(e) =>
                  updateConfig({
                    duplicate_method: e.target.value as DuplicateMethod,
                  })
                }
                className="w-full h-10 px-3 rounded-lg bg-input border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-colors"
              >
                <option value={DuplicateMethod.ORB}>ORB Feature Matching</option>
                <option value={DuplicateMethod.SSIM}>SSIM</option>
              </select>
            </div>

            {/* Resize */}
            <div className="space-y-2">
              <label
                htmlFor="resize-width"
                className="text-sm font-medium text-muted-foreground"
              >
                Resize Width
              </label>
              <select
                id="resize-width"
                value={config.resize_width}
                onChange={(e) =>
                  updateConfig({ resize_width: Number(e.target.value) })
                }
                className="w-full h-10 px-3 rounded-lg bg-input border border-border text-foreground focus:outline-none focus:ring-2 focus:ring-ring transition-colors"
              >
                {RESIZE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <label className="flex items-start gap-3 rounded-lg border border-border bg-muted/30 p-3 cursor-pointer">
            <input
              type="checkbox"
              checked={config.keep_intermediates}
              onChange={(e) =>
                updateConfig({ keep_intermediates: e.target.checked })
              }
              className="mt-1 h-4 w-4 accent-primary"
            />
            <span>
              <span className="block text-sm font-medium">
                Keep intermediate files
              </span>
              <span className="block text-xs text-muted-foreground mt-0.5">
                Retain extracted, blurry, and duplicate frames for inspection. This uses significantly more storage.
              </span>
            </span>
          </label>
        </div>

        {/* Error */}
        {error && (
          <div className="p-4 rounded-lg bg-destructive/10 border border-destructive/30 text-destructive text-sm">
            {error}
          </div>
        )}

        {/* Cancel & Process Buttons */}
        <div className="grid grid-cols-2 gap-3">
          <button
            id="cancel-button"
            type="button"
            disabled={
              (!videoFile && !videoMetadata && !jobId) ||
              isUploading ||
              isProcessing ||
              isCancelling
            }
            onClick={handleCancel}
            className="h-14 rounded-xl border border-border bg-secondary text-lg font-semibold text-foreground
              transition-all duration-300 hover:border-destructive/50 hover:bg-destructive/10 hover:text-destructive
              disabled:cursor-not-allowed disabled:opacity-20 disabled:hover:border-border disabled:hover:bg-secondary disabled:hover:text-foreground
              flex items-center justify-center gap-3"
          >
            {isCancelling ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                Cancelling...
              </>
            ) : (
              <>
                <X className="w-5 h-5" />
                Cancel
              </>
            )}
          </button>

          <button
            id="process-button"
            type="button"
            disabled={
              !videoMetadata ||
              isProcessing ||
              isUploading ||
              isCancelling ||
              !jobId
            }
            onClick={handleProcess}
            className="h-14 rounded-xl text-lg font-semibold transition-all duration-300
              bg-gradient-to-r from-primary to-accent text-primary-foreground
              hover:shadow-lg hover:shadow-primary/25 hover:scale-[1.01]
              disabled:opacity-20 disabled:cursor-not-allowed disabled:hover:scale-100 disabled:hover:shadow-none
              flex items-center justify-center gap-3"
          >
            {isProcessing ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                Processing...
              </>
            ) : (
              <>
                <Play className="w-5 h-5" />
                Start Processing
              </>
            )}
          </button>
        </div>

        {/* Footer */}
        <p className="text-center text-xs text-muted-foreground">
          GS-Prep v0.1.0 — Open Source Dataset Preparation for 3D Reconstruction
        </p>
      </div>
    </main>
  );
}
