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
  Settings2,
  Film,
  Sparkles,
  Loader2,
} from "lucide-react";
import { usePipelineStore } from "@/hooks/use-pipeline-store";
import { uploadVideo } from "@/services/api";
import { RESIZE_OPTIONS } from "@/types";

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
  } = usePipelineStore();

  const [uploadProgress, setUploadProgress] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);

  const uploadFileInstantly = async (file: File) => {
    setIsUploading(true);
    // @ts-expect-error Reset metadata safely
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
    if (!videoFile || !jobId) {
      setError("Please wait for the upload to complete before processing.");
      return;
    }

    setProcessing(true);
    setError(null);
    router.push("/processing");
  };

  const formatFileSize = (bytes: number) => {
    if (bytes >= 1_073_741_824) return `${(bytes / 1_073_741_824).toFixed(1)} GB`;
    if (bytes >= 1_048_576) return `${(bytes / 1_048_576).toFixed(1)} MB`;
    return `${(bytes / 1024).toFixed(1)} KB`;
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
            {videoFile ? (
              <>
                <Film className="w-12 h-12 text-success" />
                <div>
                  <p className="text-lg font-semibold">{videoFile.name}</p>
                  <p className="text-sm text-muted-foreground">
                    {formatFileSize(videoFile.size)}
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
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground uppercase tracking-wider">Resolution</p>
                  <p className="font-mono font-medium">{videoMetadata.width}x{videoMetadata.height}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground uppercase tracking-wider">Original FPS</p>
                  <p className="font-mono font-medium">{videoMetadata.fps.toFixed(2)}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground uppercase tracking-wider">Duration</p>
                  <p className="font-mono font-medium">{videoMetadata.duration.toFixed(2)}s</p>
                </div>
                <div className="space-y-1">
                  <p className="text-xs text-muted-foreground uppercase tracking-wider">Total Frames</p>
                  <p className="font-mono font-medium">{videoMetadata.total_frames}</p>
                </div>
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
                max={60}
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
                min={1}
                max={1000}
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
                type="text"
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
        </div>

        {/* Error */}
        {error && (
          <div className="p-4 rounded-lg bg-destructive/10 border border-destructive/30 text-destructive text-sm">
            {error}
          </div>
        )}

        {/* Process Button */}
        <button
          id="process-button"
          disabled={!videoFile || isProcessing || isUploading || !jobId}
          onClick={handleProcess}
          className="w-full h-14 rounded-xl text-lg font-semibold transition-all duration-300 
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

        {/* Footer */}
        <p className="text-center text-xs text-muted-foreground">
          GS-Prep v0.1.0 — Open Source Dataset Preparation for 3D Reconstruction
        </p>
      </div>
    </main>
  );
}
