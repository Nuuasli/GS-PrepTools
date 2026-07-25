"use client";

/**
 * GS-Prep — Processing Progress Page
 *
 * Professional Pipeline Task Engine (Vercel / GitHub Actions Style):
 * 1. Centered Hero Overall Progress Card with top-right percentage badge.
 * 2. Bottom-right Task Stack powered by Framer Motion:
 *    - Strict MAX TWO tasks visible at any time.
 *    - Top Card: Last Completed Task (opacity ~40%, scale ~0.95, green check mark).
 *    - Bottom Card: Active Running Task (opacity 100%, scale 1.0, active theme).
 *    - Smooth spring transitions (translateY, opacity, scale).
 *    - Older completed tasks exit cleanly with fade-out upwards.
 */

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  Upload,
  Film,
  Eye,
  Copy,
  Scaling,
  FileText,
  CheckCircle2,
  Loader2,
  XCircle,
  Clock,
  Sparkles,
} from "lucide-react";
import { usePipelineStore } from "@/hooks/use-pipeline-store";
import { startPipeline, getPipelineProgress } from "@/services/api";
import type { PipelineStep, StepStatus, StepProgress } from "@/types";

const STEP_META: Record<
  string,
  { label: string; icon: React.ElementType }
> = {
  upload: { label: "Upload Video", icon: Upload },
  extract: { label: "Extract Frames", icon: Film },
  blur: { label: "Blur Detection", icon: Eye },
  duplicate: { label: "Duplicate Removal", icon: Copy },
  resize: { label: "Resize Images", icon: Scaling },
  report: { label: "Generate Report", icon: FileText },
};

function StatusIcon({ status }: { status: StepStatus }) {
  switch (status) {
    case "completed":
      return <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />;
    case "running":
      return <Loader2 className="w-4 h-4 text-primary animate-spin shrink-0" />;
    case "failed":
      return <XCircle className="w-4 h-4 text-destructive shrink-0" />;
    default:
      return <Clock className="w-4 h-4 text-muted-foreground shrink-0" />;
  }
}

function formatCounts(processed?: number, total?: number): string | null {
  if (
    typeof processed === "number" &&
    typeof total === "number" &&
    total > 0
  ) {
    return ` (${processed}/${total})`;
  }
  return null;
}

interface DisplayTask {
  id: string;
  role: "completed" | "active";
  stepData: StepProgress;
}

/**
 * Derives a strict max-2 task array for the bottom-right task feed:
 * 1. At start: Only 1 active task (Upload Video).
 * 2. During execution: 1 Last Completed Task (top, 40% opacity) + 1 Active Task (bottom, 100% opacity).
 * 3. As next task finishes: Oldest task exits, previous active moves up, new active enters from bottom.
 */
function getDisplayTasks(steps: StepProgress[]): DisplayTask[] {
  if (!steps || steps.length === 0) return [];

  const runningIndex = steps.findIndex((s) => s.status === "running");

  if (runningIndex >= 0) {
    const runningStep = steps[runningIndex];
    const prevCompletedStep =
      runningIndex > 0 ? steps[runningIndex - 1] : null;

    const list: DisplayTask[] = [];

    if (prevCompletedStep && prevCompletedStep.status === "completed") {
      list.push({
        id: prevCompletedStep.step,
        role: "completed",
        stepData: prevCompletedStep,
      });
    }

    list.push({
      id: runningStep.step,
      role: "active",
      stepData: runningStep,
    });

    return list;
  }

  // If no step is currently 'running'
  const completedSteps = steps.filter((s) => s.status === "completed");

  if (completedSteps.length === 0) {
    // Very start: show only first task as active
    return [
      {
        id: steps[0].step,
        role: "active",
        stepData: steps[0],
      },
    ];
  }

  if (completedSteps.length === steps.length) {
    // All completed
    const last = steps[steps.length - 1];
    const prev = steps[steps.length - 2];
    return [
      { id: prev.step, role: "completed", stepData: prev },
      { id: last.step, role: "completed", stepData: last },
    ];
  }

  // Fallback: show last completed + next pending
  const lastCompleted = completedSteps[completedSteps.length - 1];
  const lastCompletedIdx = steps.findIndex((s) => s.step === lastCompleted.step);
  const nextPending = steps[lastCompletedIdx + 1];

  const list: DisplayTask[] = [
    { id: lastCompleted.step, role: "completed", stepData: lastCompleted },
  ];
  if (nextPending) {
    list.push({ id: nextPending.step, role: "active", stepData: nextPending });
  }
  return list;
}

export default function ProcessingPage() {
  const router = useRouter();
  const { jobId, config, steps, setResult, updateStepProgress, setCurrentStep } =
    usePipelineStore();
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedRef = useRef(false);

  useEffect(() => {
    if (!jobId) {
      router.push("/");
      return;
    }

    // Start pipeline
    if (!startedRef.current) {
      startedRef.current = true;
      startPipeline(jobId, config).catch(console.error);
    }

    // Poll for progress
    pollingRef.current = setInterval(async () => {
      try {
        const progress = await getPipelineProgress(jobId);

        // Update each step's progress
        progress.steps.forEach((stepProgress) => {
          updateStepProgress(stepProgress.step as PipelineStep, {
            status: stepProgress.status as StepStatus,
            progress: stepProgress.progress,
            message: stepProgress.message,
            processed: stepProgress.processed,
            total: stepProgress.total,
          });
        });

        setCurrentStep(progress.current_step);

        // Check if all done
        if (progress.overall_progress >= 100) {
          if (pollingRef.current) clearInterval(pollingRef.current);
          const { getPipelineResult } = await import("@/services/api");
          const result = await getPipelineResult(jobId);
          setResult(result);
          router.push("/result");
        }
      } catch {
        // Silently retry on progress polling errors
      }
    }, 1000);

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [jobId, config, router, setResult, updateStepProgress, setCurrentStep]);

  const overallProgress = Math.round(
    steps.reduce((sum, s) => sum + s.progress, 0) / (steps.length || 1)
  );

  const displayTasks = getDisplayTasks(steps);
  const activeTask = displayTasks.find((t) => t.role === "active");
  const activeMeta = activeTask ? STEP_META[activeTask.id] : null;

  return (
    <main className="relative min-h-screen flex items-center justify-center p-6 overflow-hidden">
      {/* Ambient background glow */}
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[550px] h-[550px] bg-primary/10 rounded-full blur-[140px] pointer-events-none" />

      {/* ========================================================
          CENTER HERO: Overall Progress Display
         ======================================================== */}
      <div className="w-full max-w-xl text-center space-y-6 z-10 animate-fade-in">
        <div className="space-y-2">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-primary/10 border border-primary/20 text-primary text-xs font-semibold tracking-wide uppercase">
            <Sparkles className="w-3.5 h-3.5" />
            GS-Prep Processing Engine
          </div>
          <h1 className="text-4xl font-extrabold tracking-tight">
            Processing Dataset
          </h1>
          <p className="text-muted-foreground text-sm max-w-md mx-auto">
            Please wait while your video is being processed...
          </p>
        </div>

        {/* Clean Overall Progress Card */}
        <div className="glass-card p-6 space-y-4 shadow-2xl relative border border-border/80">
          {/* Header Row: Overall Progress label on left, 57% on right */}
          <div className="flex items-center justify-between text-sm font-semibold">
            <span className="text-muted-foreground tracking-wide">
              Overall Progress
            </span>
            <span className="text-primary font-mono font-bold text-base">
              {overallProgress}%
            </span>
          </div>

          {/* Smooth Linear Progress Bar */}
          <div className="h-3 bg-secondary/80 rounded-full overflow-hidden p-0.5 border border-border/50">
            <div
              className="h-full bg-gradient-to-r from-primary via-accent to-indigo-400 rounded-full transition-all duration-500 ease-out shadow-[0_0_12px_rgba(99,102,241,0.4)]"
              style={{ width: `${overallProgress}%` }}
            />
          </div>

          {/* Current Running Task Indicator */}
          {activeMeta && (
            <div className="pt-1 flex items-center justify-center gap-2 text-xs text-muted-foreground font-medium">
              <Loader2 className="w-3.5 h-3.5 text-primary animate-spin" />
              <span>Current Task:</span>
              <span className="font-semibold text-foreground">
                {activeMeta.label}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* ========================================================
          BOTTOM-RIGHT PIPELINE TASK FEED (Strictly Max 2 Tasks)
          Powered by Framer Motion AnimatePresence & Spring Layout
         ======================================================== */}
      <div className="fixed bottom-6 right-6 z-50 w-80 sm:w-96 space-y-2.5 pointer-events-auto flex flex-col justify-end">
        <AnimatePresence mode="popLayout" initial={false}>
          {displayTasks.map(({ id, role, stepData }) => {
            const meta = STEP_META[id] || { label: id, icon: Clock };
            const Icon = meta.icon;
            const isCompleted = role === "completed";
            const isFailed = stepData.status === "failed";
            const countText = formatCounts(stepData.processed, stepData.total);

            return (
              <motion.div
                key={id}
                layout
                initial={{ opacity: 0, y: 30, scale: 0.95 }}
                animate={{
                  opacity: isCompleted ? 0.4 : 1.0,
                  y: 0,
                  scale: isCompleted ? 0.95 : 1.0,
                }}
                exit={{ opacity: 0, y: -25, scale: 0.9 }}
                transition={{
                  type: "spring",
                  stiffness: 380,
                  damping: 28,
                  mass: 0.8,
                }}
                className={`p-3.5 rounded-xl backdrop-blur-xl border shadow-xl transition-colors duration-300 ${
                  isCompleted
                    ? "bg-emerald-950/20 border-emerald-500/30 text-emerald-300"
                    : isFailed
                    ? "bg-red-950/30 border-red-500/40 text-red-300"
                    : "bg-card/95 border-primary/50 text-foreground shadow-primary/10"
                }`}
              >
                <div className="flex items-center gap-2.5 mb-1.5">
                  <Icon
                    className={`w-4 h-4 ${
                      isCompleted
                        ? "text-emerald-400"
                        : "text-primary shrink-0"
                    }`}
                  />
                  <span className="text-xs font-semibold flex-1 truncate">
                    {meta.label}
                  </span>
                  <StatusIcon status={stepData.status} />
                </div>

                {/* Progress bar */}
                <div className="h-1 bg-secondary/80 rounded-full overflow-hidden">
                  <motion.div
                    className={`h-full rounded-full ${
                      isCompleted
                        ? "bg-emerald-400"
                        : isFailed
                        ? "bg-destructive"
                        : "bg-gradient-to-r from-primary to-accent"
                    }`}
                    initial={{ width: 0 }}
                    animate={{ width: `${stepData.progress}%` }}
                    transition={{ duration: 0.3, ease: "easeOut" }}
                  />
                </div>

                {/* Status Message */}
                <p className="text-[11px] mt-1.5 truncate text-muted-foreground">
                  {stepData.message}
                  {countText}
                </p>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </main>
  );
}
