"""Web job orchestration for standalone image-downscale batches."""

from __future__ import annotations

import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from app.core.config import settings
from tools.image_downscale.batch import (
    BatchDownscaleError,
    BatchPreflight,
    BatchResult,
    QuickBatchPreflight,
    inspect_local_dataset_root,
    preflight_batch,
    quick_preflight_local,
    run_batch_downscale,
    sanitize_component,
)


@dataclass
class ImageDownscaleJob:
    job_id: str
    root_name: str
    input_mode: str
    source_root: Path
    workspace_dir: Path
    dataset_names: dict[str, str]
    dataset_sources: Optional[dict[str, Path]]
    ignored_files: tuple[str, ...]
    max_width: int
    max_height: int
    preflight: Optional[BatchPreflight] = None
    quick_preflight: Optional[QuickBatchPreflight] = None
    output_path: Optional[Path] = None
    status: str = "preflight_ready"
    progress: float = 0.0
    current_dataset: Optional[str] = None
    error: Optional[str] = None
    result: Optional[BatchResult] = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def job_dir(self) -> Path:
        return self.workspace_dir

    def as_dict(self) -> dict[str, Any]:
        with self.lock:
            result = self.result
            if self.input_mode == "local":
                assert self.quick_preflight is not None
                quick = self.quick_preflight
                datasets = [
                    {
                        "dataset_name": dataset.dataset_name,
                        "dataset_id": dataset.dataset_id,
                        "images": dataset.total_images,
                        "resize": dataset.sampled_resize,
                        "unchanged": dataset.sampled_unchanged,
                        "corrupt": dataset.sample_errors,
                        "sampled": dataset.sampled_count,
                        "sample_errors": dataset.sample_errors,
                        "samples": [
                            {
                                "filename": sample.filename,
                                "source_width": sample.source_width,
                                "source_height": sample.source_height,
                                "output_width": sample.output_width,
                                "output_height": sample.output_height,
                                "action": sample.action,
                                "error": sample.error,
                            }
                            for sample in dataset.samples
                        ],
                    }
                    for dataset in quick.datasets
                ]
                dataset_count = quick.dataset_count
                total_images = quick.total_images
                total_resize = sum(item.sampled_resize for item in quick.datasets)
                total_unchanged = sum(
                    item.sampled_unchanged for item in quick.datasets
                )
                corrupt_images = [
                    {
                        "dataset_name": dataset.dataset_name,
                        "dataset_id": dataset.dataset_id,
                        "relative_path": f"{dataset.dataset_name}/{sample.filename}",
                        "error": sample.error,
                    }
                    for dataset in quick.datasets
                    for sample in dataset.samples
                    if sample.error is not None
                ]
                can_process = not corrupt_images
                validation_scope = "sample"
                samples_per_dataset: Optional[int] = quick.samples_per_dataset
                total_sampled: Optional[int] = quick.total_sampled
            else:
                assert self.preflight is not None
                full = self.preflight
                datasets = [
                    {
                        "dataset_name": dataset.dataset_name,
                        "dataset_id": dataset.dataset_id,
                        "images": dataset.images,
                        "resize": dataset.resize,
                        "unchanged": dataset.unchanged,
                        "corrupt": dataset.corrupt,
                    }
                    for dataset in full.datasets
                ]
                dataset_count = full.dataset_count
                total_images = full.total_images
                total_resize = full.total_resize
                total_unchanged = full.total_unchanged
                corrupt_images = [
                    {
                        "dataset_name": issue.dataset_name,
                        "dataset_id": issue.dataset_id,
                        "relative_path": issue.relative_path,
                        "error": issue.error,
                    }
                    for issue in full.corrupt_images
                ]
                can_process = full.can_process
                validation_scope = "full"
                samples_per_dataset = None
                total_sampled = None
            response: dict[str, Any] = {
                "job_id": self.job_id,
                "root_folder": self.root_name,
                "input_mode": self.input_mode,
                "input_path": str(self.source_root) if self.input_mode == "local" else None,
                "output_path": str(self.output_path) if self.output_path else None,
                "status": self.status,
                "progress": self.progress,
                "current_dataset": self.current_dataset,
                "dataset_count": dataset_count,
                "total_images": total_images,
                "total_resize": total_resize,
                "total_unchanged": total_unchanged,
                "corrupt_images": corrupt_images,
                "ignored_files": list(self.ignored_files),
                "can_process": can_process,
                "validation_scope": validation_scope,
                "samples_per_dataset": samples_per_dataset,
                "total_sampled": total_sampled,
                "full_preflight_pending": self.input_mode == "local"
                and self.status in {"preflight_ready", "preflight_blocked"},
                "max_width": self.max_width,
                "max_height": self.max_height,
                "datasets": datasets,
                "error": self.error,
                "result": None,
            }
            if result is not None:
                response["result"] = {
                    "datasets_processed": len(result.datasets),
                    "total_images": result.total_images,
                    "resized": result.resized_images,
                    "unchanged": result.unchanged_images,
                    "output": result.output_images,
                    "failed": result.failed_images,
                    "datasets": [
                        {
                            "dataset_name": dataset.dataset_name,
                            "dataset_id": dataset.dataset_id,
                            "input": dataset.input_images,
                            "resized": dataset.resized_images,
                            "unchanged": dataset.unchanged_images,
                            "output": dataset.output_images,
                            "failed": dataset.failed_images,
                            "status": dataset.status,
                        }
                        for dataset in result.datasets
                    ],
                }
            return response


class ImageDownscaleService:
    """Owns temporary uploaded copies and sequential batch workers."""

    def __init__(self) -> None:
        self._jobs: dict[str, ImageDownscaleJob] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="image-downscale"
        )

    @property
    def storage_root(self) -> Path:
        return settings.jobs_path / "image_downscale"

    def new_workspace(self) -> tuple[str, Path, Path]:
        self.storage_root.mkdir(parents=True, exist_ok=True)
        job_id = uuid.uuid4().hex
        job_dir = self.storage_root / job_id
        source_root = job_dir / "source"
        source_root.mkdir(parents=True)
        return job_id, job_dir, source_root

    def register_preflight(
        self,
        *,
        job_id: str,
        root_name: str,
        input_mode: str,
        source_root: Path,
        dataset_names: dict[str, str],
        ignored_files: list[str],
        max_width: int,
        max_height: int,
    ) -> ImageDownscaleJob:
        preflight = preflight_batch(
            source_root,
            dataset_names,
            root_name=root_name,
            max_width=max_width,
            max_height=max_height,
            ignored_files=ignored_files,
        )
        status = "preflight_ready" if preflight.can_process else "preflight_blocked"
        job = ImageDownscaleJob(
            job_id=job_id,
            root_name=root_name,
            input_mode=input_mode,
            source_root=source_root,
            workspace_dir=source_root.parent,
            dataset_names=dict(dataset_names),
            dataset_sources=None,
            ignored_files=tuple(ignored_files),
            max_width=max_width,
            max_height=max_height,
            preflight=preflight,
            status=status,
        )
        with self._lock:
            self._jobs[job_id] = job
        return job

    def register_local_preflight(
        self,
        *,
        input_path: str,
        output_path: str,
        max_width: int,
        max_height: int,
        samples_per_dataset: int,
    ) -> ImageDownscaleJob:
        layout = inspect_local_dataset_root(input_path, output_path)
        job_id = uuid.uuid4().hex
        workspace_dir = self.storage_root / job_id
        quick_preflight = quick_preflight_local(
            layout,
            samples_per_dataset=samples_per_dataset,
            max_width=max_width,
            max_height=max_height,
        )
        status = (
            "preflight_ready"
            if all(dataset.sample_errors == 0 for dataset in quick_preflight.datasets)
            else "preflight_blocked"
        )
        job = ImageDownscaleJob(
            job_id=job_id,
            root_name=layout.input_root.name,
            input_mode="local",
            source_root=layout.input_root,
            workspace_dir=workspace_dir,
            dataset_names=dict(layout.dataset_names),
            dataset_sources=dict(layout.dataset_sources),
            ignored_files=layout.ignored_files,
            max_width=max_width,
            max_height=max_height,
            quick_preflight=quick_preflight,
            output_path=layout.output_root,
            status=status,
        )
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[ImageDownscaleJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def start(self, job_id: str) -> ImageDownscaleJob:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        with job.lock:
            if job.input_mode == "local":
                assert job.quick_preflight is not None
                can_process = all(
                    dataset.sample_errors == 0
                    for dataset in job.quick_preflight.datasets
                )
            else:
                assert job.preflight is not None
                can_process = job.preflight.can_process
            if not can_process:
                raise BatchDownscaleError(
                    "Batch is blocked because "
                    + (
                        "quick dry run found corrupt sampled images"
                        if job.input_mode == "local"
                        else "preflight found corrupt images"
                    )
                )
            if job.status != "preflight_ready":
                raise BatchDownscaleError(f"Job cannot start from status {job.status}")
            job.status = "running"
            job.progress = 0.0
        self._executor.submit(self._run, job)
        return job

    def _run(self, job: ImageDownscaleJob) -> None:
        def update_progress(index: int, total: int, dataset_name: str) -> None:
            with job.lock:
                job.current_dataset = dataset_name
                job.progress = round(((index - 1) / total) * 100, 2)

        try:
            if job.input_mode == "local":
                assert job.output_path is not None
                result = run_batch_downscale(
                    job.source_root,
                    job.output_path.parent,
                    job.dataset_names,
                    root_name=job.root_name,
                    max_width=job.max_width,
                    max_height=job.max_height,
                    dataset_sources=job.dataset_sources,
                    direct_output_root=job.output_path,
                    create_archive=False,
                    progress=update_progress,
                )
            else:
                result = run_batch_downscale(
                    job.source_root,
                    job.job_dir / "result",
                    job.dataset_names,
                    root_name=job.root_name,
                    max_width=job.max_width,
                    max_height=job.max_height,
                    single_folder=job.input_mode == "single",
                    progress=update_progress,
                )
        except Exception as exc:  # worker boundary: persist a visible failure
            with job.lock:
                job.status = "failed"
                job.error = str(exc)
                job.current_dataset = None
            return
        with job.lock:
            job.result = result
            job.status = "completed"
            job.progress = 100.0
            job.current_dataset = None

    def delete(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return False
        with job.lock:
            if job.status == "running":
                raise BatchDownscaleError("Cannot delete a running batch")
        with self._lock:
            self._jobs.pop(job_id, None)
        shutil.rmtree(job.job_dir, ignore_errors=True)
        return True

    def cleanup_workspace(self, job_dir: Path) -> None:
        shutil.rmtree(job_dir, ignore_errors=True)


image_downscale_service = ImageDownscaleService()


def single_dataset_identity(root_name: str) -> tuple[str, str]:
    """Return display and safe identity used for single-folder web uploads."""
    display_name = root_name.strip() or "dataset"
    return display_name, sanitize_component(display_name)
    inspect_local_dataset_root,
