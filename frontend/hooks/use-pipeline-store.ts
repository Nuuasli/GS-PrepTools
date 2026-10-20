/**
 * GS-Prep Frontend — Pipeline State Store (Zustand)
 *
 * Global state management for the entire processing pipeline.
 * Manages config, job state, progress, and results.
 */

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
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
  hasHydrated: boolean;

  // --- Actions ---
  setVideoFile: (file: File | null) => void;
  setJobId: (jobId: string | null) => void;
  setVideoMetadata: (metadata: VideoMetadata | null) => void;
  updateConfig: (config: Partial<ProcessingConfig>) => void;
  setProcessing: (processing: boolean) => void;
  updateStepProgress: (step: PipelineStep, update: Partial<StepProgress>) => void;
  setCurrentStep: (step: PipelineStep) => void;
  setResult: (result: ProcessingResult) => void;
  setHasHydrated: (hydrated: boolean) => void;
  reset: () => void;
}

// ========================
// Default Values
// ========================

const DEFAULT_CONFIG: ProcessingConfig = {
  extraction_fps: 2,
  jpeg_quality: 100,
  blur_threshold: 10,
  duplicate_threshold: 0.5,
  resize_width: 0,
  duplicate_method: "orb" as DuplicateMethod,
  keep_intermediates: true,
};

const PERSIST_VERSION = 2;

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

export const usePipelineStore = create<PipelineState>()(
  persist(
    (set) => ({
  // Initial state
  jobId: null,
  videoFile: null,
  videoMetadata: null,
  config: { ...DEFAULT_CONFIG },
  isProcessing: false,
  steps: createInitialSteps(),
  currentStep: null,
  result: null,
  hasHydrated: false,

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

  setHasHydrated: (hydrated) => set({ hasHydrated: hydrated }),

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
    }),
    {
      name: "gs-prep-pipeline",
      version: PERSIST_VERSION,
      storage: createJSONStorage(() => sessionStorage),
      skipHydration: true,
      migrate: (persistedState, version) => {
        const state = (persistedState ?? {}) as Partial<PipelineState>;
        if (version < PERSIST_VERSION) {
          return {
            ...state,
            config: { ...DEFAULT_CONFIG },
          } as PipelineState;
        }
        return state as PipelineState;
      },
      partialize: (state) => ({
        jobId: state.jobId,
        videoMetadata: state.videoMetadata,
        config: state.config,
        isProcessing: state.isProcessing,
        steps: state.steps,
        currentStep: state.currentStep,
        result: state.result,
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true);
      },
    }
  )
);
