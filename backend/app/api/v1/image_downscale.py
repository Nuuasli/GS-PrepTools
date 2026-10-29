"""API endpoints for folder-preserving standalone image downscale jobs."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.services.image_downscale import (
    image_downscale_service,
    single_dataset_identity,
)
from tools.image_downscale.batch import (
    BatchDownscaleError,
    UploadPath,
    is_supported_image,
    parse_browser_relative_path,
    validate_browser_relative_path,
)


router = APIRouter(prefix="/image-downscale", tags=["Image Downscale"])
UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024


class LocalPathPreflightRequest(BaseModel):
    """Trusted-localhost filesystem paths for a direct downscale batch."""

    input_path: str = Field(min_length=1)
    output_path: str = Field(min_length=1)
    max_width: int = Field(default=1920, gt=0)
    max_height: int = Field(default=1080, gt=0)
    samples_per_dataset: int = Field(default=2, ge=1)


async def _stream_upload(upload: UploadFile, destination: Path) -> None:
    """Copy one browser upload to disk without buffering the complete file."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f".{destination.name}.uploading")
    try:
        with partial.open("wb") as output:
            while chunk := await upload.read(UPLOAD_CHUNK_SIZE_BYTES):
                output.write(chunk)
        os.replace(partial, destination)
    finally:
        partial.unlink(missing_ok=True)


@router.post("/preflight")
async def create_preflight(
    files: list[UploadFile] = File(...),
    relative_paths: list[str] = Form(...),
    input_mode: str = Form(...),
    root_name: str = Form(...),
    max_width: int = Form(1920),
    max_height: int = Form(1080),
) -> dict:
    """Upload copies, validate paths, and dry-run every detected dataset."""
    if len(files) != len(relative_paths):
        raise HTTPException(
            status_code=400,
            detail="Each uploaded file must have one matching relative path",
        )
    if max_width <= 0 or max_height <= 0:
        raise HTTPException(status_code=422, detail="Resolution must be positive")
    if input_mode not in {"single", "root"}:
        raise HTTPException(status_code=422, detail="Invalid input mode")

    job_id, job_dir, source_root = image_downscale_service.new_workspace()
    dataset_names: dict[str, str] = {}
    seen_paths: set[tuple[str, str]] = set()
    ignored_files: list[str] = []
    try:
        for upload, raw_path in zip(files, relative_paths):
            if not is_supported_image(raw_path):
                validate_browser_relative_path(raw_path)
                ignored_files.append(raw_path)
                continue
            parsed = parse_browser_relative_path(raw_path, input_mode)
            if input_mode == "single":
                display_name, dataset_id = single_dataset_identity(root_name)
                parsed = UploadPath(
                    dataset_name=display_name,
                    dataset_id=dataset_id,
                    filename=parsed.filename,
                    relative_path=parsed.relative_path,
                )

            existing_name = dataset_names.get(parsed.dataset_id)
            if existing_name is not None and existing_name != parsed.dataset_name:
                raise BatchDownscaleError(
                    "Dataset names collide after filesystem sanitization: "
                    f"{existing_name!r} and {parsed.dataset_name!r}"
                )
            dataset_names[parsed.dataset_id] = parsed.dataset_name

            identity = (parsed.dataset_id.casefold(), parsed.filename.casefold())
            if identity in seen_paths:
                raise BatchDownscaleError(
                    f"Duplicate uploaded relative path: {parsed.relative_path}"
                )
            seen_paths.add(identity)

            destination = source_root / parsed.dataset_id / parsed.filename
            resolved_destination = destination.resolve()
            if not resolved_destination.is_relative_to(source_root.resolve()):
                raise BatchDownscaleError(
                    f"Upload path escapes the job workspace: {parsed.relative_path}"
                )
            await _stream_upload(upload, destination)

        # A dataset containing only ignored files is not a detected image dataset.
        dataset_names = {
            dataset_id: dataset_name
            for dataset_id, dataset_name in dataset_names.items()
            if (source_root / dataset_id).is_dir()
        }
        job = image_downscale_service.register_preflight(
            job_id=job_id,
            root_name=root_name.strip() or "image_dataset",
            input_mode=input_mode,
            source_root=source_root,
            dataset_names=dataset_names,
            ignored_files=ignored_files,
            max_width=max_width,
            max_height=max_height,
        )
        return job.as_dict()
    except (BatchDownscaleError, OSError, ValueError) as exc:
        image_downscale_service.cleanup_workspace(job_dir)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        for upload in files:
            await upload.close()


@router.post("/local/preflight")
async def create_local_preflight(request: LocalPathPreflightRequest) -> dict:
    """Dry-run a local dataset root without uploading or writing final images."""
    try:
        job = image_downscale_service.register_local_preflight(
            input_path=request.input_path,
            output_path=request.output_path,
            max_width=request.max_width,
            max_height=request.max_height,
            samples_per_dataset=request.samples_per_dataset,
        )
    except (BatchDownscaleError, OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return job.as_dict()


@router.post("/{job_id}/start")
async def start_batch(job_id: str) -> dict:
    try:
        job = image_downscale_service.start(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Downscale job not found") from exc
    except BatchDownscaleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return job.as_dict()


@router.get("/{job_id}/status")
async def get_batch_status(job_id: str) -> dict:
    job = image_downscale_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Downscale job not found")
    return job.as_dict()


def _completed_job(job_id: str):
    job = image_downscale_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Downscale job not found")
    if job.status != "completed" or job.result is None:
        raise HTTPException(status_code=409, detail="Downscale batch is not completed")
    return job


@router.get("/{job_id}/download/zip")
async def download_batch_zip(job_id: str) -> FileResponse:
    job = _completed_job(job_id)
    assert job.result is not None
    if job.result.archive_path is None:
        raise HTTPException(
            status_code=404,
            detail="ZIP is not generated for Local Path mode",
        )
    return FileResponse(
        str(job.result.archive_path),
        media_type="application/zip",
        filename=job.result.archive_path.name,
    )


@router.get("/{job_id}/download/summary")
async def download_batch_summary(job_id: str) -> FileResponse:
    job = _completed_job(job_id)
    assert job.result is not None
    return FileResponse(
        str(job.result.summary_path),
        media_type="text/csv",
        filename="batch_downscale_summary.csv",
    )


@router.get("/{job_id}/download/manifest/{dataset_id}")
async def download_dataset_manifest(job_id: str, dataset_id: str) -> FileResponse:
    job = _completed_job(job_id)
    if dataset_id not in job.dataset_names or Path(dataset_id).name != dataset_id:
        raise HTTPException(status_code=404, detail="Dataset not found")
    assert job.result is not None
    manifest = (
        job.result.output_root / "downscale_manifest.csv"
        if job.input_mode == "single"
        else job.result.output_root / dataset_id / "downscale_manifest.csv"
    )
    if not manifest.is_file():
        raise HTTPException(status_code=404, detail="Dataset manifest not found")
    return FileResponse(
        str(manifest),
        media_type="text/csv",
        filename=f"{dataset_id}_downscale_manifest.csv",
    )


@router.delete("/{job_id}")
async def delete_batch(job_id: str) -> dict:
    try:
        deleted = image_downscale_service.delete(job_id)
    except BatchDownscaleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Downscale job not found")
    return {"status": "deleted", "job_id": job_id}
