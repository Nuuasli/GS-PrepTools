"use client";

/**
 * GS-Prep — Result Page
 *
 * Displays the final dataset summary, processing metrics,
 * image previews, and download buttons for the dataset and report.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  Film,
  Clock,
  ImageIcon,
  Download,
  FileText,
  RotateCcw,
  Sparkles,
  Check,
  Trash2,
  Layers,
  Scaling,
} from "lucide-react";
import { usePipelineStore } from "@/hooks/use-pipeline-store";
import { getDatasetDownloadUrl, getReportDownloadUrl, getPreviewImageUrl } from "@/services/api";

interface StatCardProps {
  icon: React.ElementType;
  label: string;
  value: string | number;
  sublabel?: string;
}

function StatCard({ icon: Icon, label, value, sublabel }: StatCardProps) {
  return (
    <div className="glass-card p-4 space-y-1">
      <div className="flex items-center gap-2 text-muted-foreground">
        <Icon className="w-4 h-4 text-primary" />
        <span className="text-xs font-medium uppercase tracking-wider">
          {label}
        </span>
      </div>
      <p className="text-2xl font-bold">{value}</p>
      {sublabel && (
        <p className="text-xs text-muted-foreground">{sublabel}</p>
      )}
    </div>
  );
}

export default function ResultPage() {
  const router = useRouter();
  const { result, jobId, reset } = usePipelineStore();

  useEffect(() => {
    if (!result || !jobId) {
      router.push("/");
    }
  }, [result, jobId, router]);

  if (!result || !jobId) return null;

  const formatDuration = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}m ${s}s`;
  };

  const handleNewProject = async () => {
    if (jobId) {
      try {
        const { deleteJob } = await import("@/services/api");
        await deleteJob(jobId);
      } catch {
        // Silently ignore cleanup errors
      }
    }
    reset();
    router.push("/");
  };

  return (
    <main className="flex-1 flex justify-center p-6">
      <div className="w-full max-w-3xl space-y-8 animate-fade-in">
        {/* Header */}
        <div className="text-center space-y-3">
          <div className="flex items-center justify-center gap-3">
            <Sparkles className="w-8 h-8 text-success" />
            <h1 className="text-3xl font-bold tracking-tight">
              Dataset Ready
            </h1>
          </div>
          <p className="text-muted-foreground">
            Your dataset has been successfully prepared.
          </p>
        </div>

        {/* Video Information */}
        <div className="glass-card p-5 space-y-3">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Film className="w-5 h-5 text-primary" />
            Video Information
          </h2>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm">
            <div>
              <span className="text-muted-foreground">Filename</span>
              <p className="font-medium truncate">{result.video_info.filename}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Duration</span>
              <p className="font-medium">{formatDuration(result.video_info.duration)}</p>
            </div>
            <div>
              <span className="text-muted-foreground">FPS</span>
              <p className="font-medium">{result.video_info.fps}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Resolution</span>
              <p className="font-medium">
                {result.video_info.width}×{result.video_info.height}
              </p>
            </div>
          </div>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <StatCard
            icon={ImageIcon}
            label="Final Images"
            value={result.dataset_summary.final_images}
          />
          <StatCard
            icon={Check}
            label="Extracted"
            value={result.extraction.extracted_frames}
            sublabel={`at ${result.extraction.extraction_fps} FPS`}
          />
          <StatCard
            icon={Trash2}
            label="Blur Removed"
            value={result.blur.blur_removed}
          />
          <StatCard
            icon={Layers}
            label="Duplicates Removed"
            value={result.duplicate.duplicates_removed}
          />
          <StatCard
            icon={Scaling}
            label="Final Resolution"
            value={`${result.resize.final_width}×${result.resize.final_height}`}
          />
          <StatCard
            icon={Clock}
            label="Processing Time"
            value={formatDuration(result.processing_time)}
          />
        </div>

        {/* Preview Images */}
        {result.preview_images.length > 0 && (
          <div className="glass-card p-5 space-y-3">
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <ImageIcon className="w-5 h-5 text-primary" />
              Preview
            </h2>
            <div className="grid grid-cols-3 sm:grid-cols-4 gap-2">
              {result.preview_images.slice(0, 8).map((img) => (
                <div
                  key={img}
                  className="aspect-video rounded-lg overflow-hidden bg-muted"
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={getPreviewImageUrl(jobId, img)}
                    alt={img}
                    className="w-full h-full object-cover hover:scale-105 transition-transform duration-300"
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Download Buttons */}
        <div className="flex flex-col sm:flex-row gap-3">
          <a
            href={getDatasetDownloadUrl(jobId)}
            download
            className="flex-1 h-12 rounded-xl font-semibold transition-all duration-300
              bg-gradient-to-r from-primary to-accent text-primary-foreground
              hover:shadow-lg hover:shadow-primary/25
              flex items-center justify-center gap-2"
          >
            <Download className="w-5 h-5" />
            Download Dataset
          </a>
          <a
            href={getReportDownloadUrl(jobId)}
            download
            target="_blank"
            rel="noopener noreferrer"
            className="flex-1 h-12 rounded-xl font-semibold transition-all duration-300
              bg-secondary text-secondary-foreground border border-border
              hover:bg-muted
              flex items-center justify-center gap-2"
          >
            <FileText className="w-5 h-5" />
            Download Report
          </a>
        </div>

        {/* New Project */}
        <button
          onClick={handleNewProject}
          className="w-full h-10 rounded-lg text-sm text-muted-foreground
            hover:text-foreground transition-colors flex items-center justify-center gap-2 cursor-pointer"
        >
          <RotateCcw className="w-4 h-4" />
          Start New Project
        </button>
      </div>
    </main>
  );
}
