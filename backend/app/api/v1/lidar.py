"""LiDAR API with streaming upload and source-scoped capabilities."""

from hashlib import sha256
from pathlib import Path
from typing import Annotated
from urllib.parse import unquote
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from app.core.config import settings
from app.models.lidar import CropRequest, DownloadKind, PreviewQuality, PreviewRequest

router = APIRouter(prefix="/lidar", tags=["LiDAR"])
NO_CACHE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def get_service(request: Request):
    service = getattr(request.app.state, "lidar_service", None)
    if service is None:
        raise HTTPException(503, "LiDAR core is not installed. Install backend/requirements-lidar.txt.")
    return service


Service = Annotated[object, Depends(get_service)]
Authorization = Annotated[str | None, Header()]


@router.get("/limits")
def limits(request: Request):
    return {"available": getattr(request.app.state, "lidar_service", None) is not None,
            "max_upload_bytes": settings.max_upload_size_bytes}


@router.post("/sources", status_code=202)
async def upload(request: Request, service: Service,
                 x_lidar_filename: Annotated[str, Header(min_length=1, max_length=1024)],
                 x_lidar_size: Annotated[int, Header(gt=0)]):
    try:
        name = unquote(x_lidar_filename, errors="strict")
    except UnicodeError as exc:
        raise HTTPException(400, "Invalid filename.") from exc
    if len(name) > 255 or any(ord(char) < 32 or char in "/\\:" for char in name):
        raise HTTPException(400, "Send a filename without a directory.")
    if Path(name).suffix.lower() not in {".ply", ".las", ".laz"}:
        raise HTTPException(415, "Choose a PLY, LAS, or LAZ file.")
    if request.headers.get("content-type") != "application/octet-stream":
        raise HTTPException(415, "Send the file as a binary request body.")
    if x_lidar_size > settings.max_upload_size_bytes:
        raise HTTPException(413, f"Maximum upload size is {settings.max_upload_size_mb} MB.")
    length = request.headers.get("content-length")
    if length is not None and (not length.isdecimal() or int(length) != x_lidar_size):
        raise HTTPException(400, "Upload size does not match Content-Length.")
    source = await run_in_threadpool(service.begin_upload, name, x_lidar_size)
    temp = source.path.with_name("upload.part")
    checksum = sha256()
    received = 0
    try:
        with temp.open("xb") as stream:
            async for chunk in request.stream():
                received += len(chunk)
                if received > settings.max_upload_size_bytes:
                    raise HTTPException(413, f"Maximum upload size is {settings.max_upload_size_mb} MB.")
                if received > x_lidar_size:
                    raise HTTPException(400, "Upload exceeds the declared size.")
                await run_in_threadpool(stream.write, chunk)
                checksum.update(chunk)
        if received != x_lidar_size:
            raise HTTPException(400, "Upload is incomplete.")
        temp.rename(source.path)
        service.finish_upload(source, checksum.hexdigest())
    except BaseException as exc:
        service.discard_upload(source)
        if isinstance(exc, ClientDisconnect):
            raise HTTPException(400, "Upload was interrupted.") from exc
        if isinstance(exc, OSError):
            raise HTTPException(507, "Could not write the upload to disk.") from exc
        raise
    return {**service.source_status(source), "token": source.token}


@router.get("/sources/{source_id}")
def inspect(source_id: UUID, service: Service, response: Response, authorization: Authorization = None):
    response.headers.update(NO_CACHE)
    with service.use(source_id.hex, authorization) as source:
        return service.source_status(source)


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: UUID, service: Service, authorization: Authorization = None):
    service.remove_source(source_id.hex, authorization)


@router.get("/sources/{source_id}/preview")
def preview(source_id: UUID, service: Service, quality: PreviewQuality = "standard",
            authorization: Authorization = None):
    with service.use(source_id.hex, authorization) as source:
        service.require_ready(source)
        body = (source.path.parent / f"preview-{quality}.bin").read_bytes()
    return Response(body, media_type="application/octet-stream", headers=NO_CACHE)


@router.post("/sources/{source_id}/preview-crop")
def preview_crop(source_id: UUID, payload: PreviewRequest, service: Service, authorization: Authorization = None):
    from app.modules.lidar_crop import preview_mask

    with service.use(source_id.hex, authorization) as source:
        info = service.require_ready(source)
        path = source.path.parent / f"preview-{payload.quality}.bin"
        body = preview_mask(path, payload.selection)
        headers = {**NO_CACHE}
        if payload.include_full_count and len(body) < info["point_count"]:
            headers["X-Lidar-Count-Id"] = service.start_preview_count(source, payload.selection)
            headers["Access-Control-Expose-Headers"] = "X-Lidar-Count-Id"
    return Response(body, media_type="application/octet-stream", headers=headers)


@router.get("/sources/{source_id}/preview-count/{count_id}")
def preview_count(source_id: UUID, count_id: UUID, service: Service, response: Response,
                  authorization: Authorization = None):
    response.headers.update(NO_CACHE)
    with service.use(source_id.hex, authorization) as source:
        return service.preview_count_status(source, count_id.hex)


@router.post("/sources/{source_id}/jobs", status_code=202)
def export(source_id: UUID, payload: CropRequest, service: Service, authorization: Authorization = None):
    with service.use(source_id.hex, authorization) as source:
        return service.start_export(source, payload)


@router.get("/sources/{source_id}/jobs/{job_id}")
def progress(source_id: UUID, job_id: UUID, service: Service, response: Response, authorization: Authorization = None):
    response.headers.update(NO_CACHE)
    with service.use(source_id.hex, authorization) as source:
        return service.job_status(source, job_id.hex)


@router.post("/sources/{source_id}/jobs/{job_id}/cancel")
def cancel(source_id: UUID, job_id: UUID, service: Service, authorization: Authorization = None):
    with service.use(source_id.hex, authorization) as source:
        return service.job_status(source, job_id.hex, cancel=True)


@router.post("/sources/{source_id}/jobs/{job_id}/download/{kind}")
def make_download(source_id: UUID, job_id: UUID, kind: DownloadKind, service: Service,
                  response: Response, authorization: Authorization = None):
    response.headers.update(NO_CACHE)
    with service.use(source_id.hex, authorization) as source:
        return {"ticket": service.ticket(source, job_id.hex, kind)}


class DownloadResponse(FileResponse):
    def __init__(self, lease, path, kind):
        super().__init__(path, filename=path.name, headers=NO_CACHE,
                         media_type="application/json" if kind == "selection" else "application/octet-stream")
        self.lease = lease

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.lease.__exit__(None, None, None)


@router.get("/downloads/{ticket}", response_class=FileResponse)
def download(ticket: str, service: Service):
    lease = service.download(ticket)
    path, kind = lease.__enter__()
    return DownloadResponse(lease, path, kind)
