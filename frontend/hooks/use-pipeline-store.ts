/**
 * GS-Prep Frontend — Pipeline State Store (Zustand)
 *
 * Global state management for the entire processing pipeline.
 * Manages config, job state, progress, and results.
 */

import { create } from "zustand";
import type {
  ProcessingConfig,
  VideoMetadata,
  StepProgress,
  ProcessingResult,
  PipelineStep,
  StepStatus,
  DuplicateMethod,
} from "@/types";

// ========================
// Store Interface
// ========================

interface PipelineState {
  // --- Job ---
  jobId: string | null;
  videoFile: File | null;
  videoMetadata: VideoMetadata | null;

  // --- Config ---
  config: ProcessingConfig;

  // --- Progress ---
  isProcessing: boolean;
  steps: StepProgress[];
  currentStep: PipelineStep | null;

  // --- Result ---
  result: ProcessingResult | null;

  // --- Actions ---
  setVideoFile: (file: File | null) => void;
  setJobId: (jobId: string) => void;
  setVideoMetadata: (metadata: VideoMetadata) => void;
  updateConfig: (config: Partial<ProcessingConfig>) => void;
  setProcessing: (processing: boolean) => void;
  updateStepProgress: (step: PipelineStep, update: Partial<StepProgress>) => void;
  setCurrentStep: (step: PipelineStep) => void;
  setResult: (result: ProcessingResult) => void;
  reset: () => void;
}

// ========================
// Default Values
// ========================

const DEFAULT_CONFIG: ProcessingConfig = {
  extraction_fps: 2,
  jpeg_quality: 95,
  blur_threshold: 80,
  duplicate_threshold: 0.85,
  resize_width: 1920,
  duplicate_method: "orb" as DuplicateMethod,
};

const createInitialSteps = (): StepProgress[] => [
  { step: "upload" as PipelineStep, status: "pending" as StepStatus, progress: 0, message: "Waiting..." },
  { step: "extract" as PipelineStep, status: "pending" as StepStatus, progress: 0, message: "Waiting..." },
  { step: "blur" as PipelineStep, status: "pending" as StepStatus, progress: 0, message: "Waiting..." },
  { step: "duplicate" as PipelineStep, status: "pending" as StepStatus, progress: 0, message: "Waiting..." },
  { step: "resize" as PipelineStep, status: "pending" as StepStatus, progress: 0, message: "Waiting..." },
  { step: "report" as PipelineStep, status: "pending" as StepStatus, progress: 0, message: "Waiting..." },
];

// ========================
// Store
// ========================

export const usePipelineStore = create<PipelineState>((set) => ({
  // Initial state
  jobId: null,
  videoFile: null,
  videoMetadata: null,
  config: { ...DEFAULT_CONFIG },
  isProcessing: false,
  steps: createInitialSteps(),
  currentStep: null,
  result: null,

  // Actions
  setVideoFile: (file) => set({ videoFile: file }),

  setJobId: (jobId) => set({ jobId }),

  setVideoMetadata: (metadata) => set({ videoMetadata: metadata }),

  updateConfig: (partial) =>
    set((state) => ({ config: { ...state.config, ...partial } })),

  setProcessing: (processing) => set({ isProcessing: processing }),

  updateStepProgress: (step, update) =>
    set((state) => ({
      steps: state.steps.map((s) =>
        s.step === step ? { ...s, ...update } : s
      ),
    })),

  setCurrentStep: (step) => set({ currentStep: step }),

  setResult: (result) => set({ result }),

  reset: () =>
    set({
      jobId: null,
      videoFile: null,
      videoMetadata: null,
      config: { ...DEFAULT_CONFIG },
      isProcessing: false,
      steps: createInitialSteps(),
      currentStep: null,
      result: null,
    }),
}));
