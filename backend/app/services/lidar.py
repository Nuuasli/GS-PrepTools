"""Bounded workers and private temporary storage for LiDAR sessions."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
import hmac
import logging
from pathlib import Path
import secrets
import shutil
from tempfile import mkdtemp
from threading import Event, RLock
from time import monotonic, time
from uuid import uuid4

from fastapi import HTTPException
from lidar_cropper.core import CropCancelled, CropError, write_json_atomic

from app.core.config import settings
from app.models.lidar import CropRegion, CropRequest
from app.modules.lidar_crop import count_selection, export_selection, prepare_source

logger = logging.getLogger(__name__)
BUSY = {"queued", "running"}
DOWNLOAD_TTL = 300


@dataclass
class Operation:
    id: str = field(default_factory=lambda: uuid4().hex)
    status: str = "queued"
    progress: int = 0
    error: str | None = None
    stop: Event = field(default_factory=Event)
    result: dict | None = None

    def public(self):
        return dict(id=self.id, status=self.status, progress=self.progress, error=self.error, result=self.result)


@dataclass
class PreviewCount:
    selection: CropRegion
    operation: Operation = field(default_factory=Operation)


@dataclass
class Source:
    id: str
    token: str
    path: Path
    name: str
    size: int
    sha256: str = ""
    scan: Operation = field(default_factory=Operation)
    jobs: dict[str, Operation] = field(default_factory=dict)
    preview_count: PreviewCount | None = None
    count_worker_active: bool = False
    used: float = field(default_factory=monotonic)
    leases: int = 1  # Upload is holding the directory.

    def in_use(self):
        return (self.leases or self.scan.status in BUSY or self.count_worker_active
                or any(job.status in BUSY for job in self.jobs.values()))


class LidarService:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.directory = Path(mkdtemp(prefix="session-", dir=root))
        self.sessions: dict[str, Source] = {}
        self.tickets: dict[str, tuple[float, str, str, str]] = {}
        self.lock = RLock()
        self.workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="lidar")
        self.cleanup()

    def begin_upload(self, filename: str, size: int) -> Source:
        with self.lock:
            if len(self.sessions) >= 8:
                raise HTTPException(429, "LiDAR storage is busy. Close an unused source or try again later.")
            if shutil.disk_usage(self.directory).free < size:
                raise HTTPException(507, "There is not enough free disk space for this upload.")
            key = uuid4().hex
            directory = self.directory / key
            directory.mkdir()
            source = Source(key, secrets.token_urlsafe(32), directory / ("source" + Path(filename).suffix.lower()),
                            filename, size)
            self.sessions[key] = source
            return source

    def discard_upload(self, source):
        with self.lock:
            source.leases -= 1
            if self._remove(source.path.parent):
                self.sessions.pop(source.id, None)
            else:
                source.scan.status = "failed"

    def finish_upload(self, source, digest):
        with self.lock:
            source.sha256 = digest
            self.workers.submit(self._inspect, source)
            source.leases -= 1

    def _progress(self, operation, value):
        if operation.stop.is_set():
            raise CropCancelled("Crop cancelled.")
        with self.lock:
            operation.progress = max(operation.progress, min(99, int(value)))

    def _inspect(self, source):
        with self.lock:
            source.scan.status = "running"
        try:
            info = prepare_source(
                source.path, decoded_limit=settings.max_upload_size_bytes * 4,
                progress=lambda p: self._progress(source.scan, p),
                verify=lambda: self._progress(source.scan, 99),
            )
        except Exception as exc:
            self._remove(source.path)
            for file in source.path.parent.glob("preview-*.bin"):
                self._remove(file)
            self._failure(source, source.scan, exc, "Could not read the point cloud. Check its file format and data.")
        else:
            with self.lock:
                source.scan.result = info
                source.scan.status, source.scan.progress = "completed", 100
                source.used = monotonic()

    def _failure(self, source, operation, exc, fallback):
        with self.lock:
            if operation.stop.is_set() or isinstance(exc, CropCancelled):
                operation.status = "cancelled"
            else:
                operation.status = "failed"
                if isinstance(exc, CropError):
                    operation.error = str(exc).replace(str(source.path), source.name)
                else:
                    logger.exception("LiDAR operation failed", exc_info=exc)
                    operation.error = fallback
            source.used = monotonic()

    def _authenticate(self, key, authorization):
        source = self.sessions.get(key)
        prefix, _, token = (authorization or "").partition(" ")
        if not source or prefix.lower() != "bearer" or not token.isascii() or not hmac.compare_digest(source.token, token):
            raise HTTPException(404, "LiDAR source not found or expired.")
        return source

    @contextmanager
    def use(self, key, auth):
        with self.lock:
            source = self._authenticate(key, auth)
            source.leases += 1
            source.used = monotonic()
        try:
            yield source
        finally:
            with self.lock:
                source.leases -= 1

    def remove_source(self, key, auth):
        with self.lock:
            source = self._authenticate(key, auth)
            if source.in_use():
                raise HTTPException(409, "Wait for the active LiDAR operation to finish.")
            if not self._remove(source.path.parent):
                raise HTTPException(503, "LiDAR files are in use. Try again.")
            del self.sessions[key]

    def source_status(self, source):
        with self.lock:
            return {**source.scan.public(), "id": source.id, "filename": source.name,
                    "size": source.size, "sha256": source.sha256}

    @staticmethod
    def require_ready(source):
        if source.scan.status != "completed":
            raise HTTPException(409, "Wait for source inspection to finish.")
        return source.scan.result

    def start_preview_count(self, source: Source, selection: CropRegion) -> str:
        with self.lock:
            previous = source.preview_count
            if previous and previous.selection == selection and previous.operation.status in ("queued", "running", "completed"):
                return previous.operation.id
            if previous:
                previous.operation.stop.set()
            count = PreviewCount(selection)
            source.preview_count = count
            if not source.count_worker_active:
                source.count_worker_active = True
                self.workers.submit(self._count_preview, source)
            return count.operation.id

    def _count_preview(self, source: Source):
        while True:
            with self.lock:
                count = source.preview_count
                if count is None or count.operation.status != "queued":
                    source.count_worker_active = False
                    return
                operation = count.operation
                operation.status = "running"
            try:
                selected = count_selection(source.path, count.selection,
                                           lambda p: self._progress(operation, p), operation.stop.is_set)
                with self.lock:
                    self._progress(operation, 99)
                    operation.result = {"point_count": selected}
                    operation.status, operation.progress = "completed", 100
                    source.used = monotonic()
            except Exception as exc:
                self._failure(source, operation, exc, "Could not count the full-resolution crop.")

    def preview_count_status(self, source: Source, count_id: str):
        with self.lock:
            count = source.preview_count
            if count is None or count.operation.id != count_id:
                raise HTTPException(404, "Preview count not found or superseded.")
            return count.operation.public()

    def start_export(self, source, request: CropRequest):
        with self.lock:
            info = self.require_ready(source)
            if request.source_sha256 != source.sha256:
                raise HTTPException(409, "Selection SHA-256 does not match this source.")
            if info["format"] == "ply" and request.output_format != "ply":
                raise HTTPException(422, "Export PLY as PLY to preserve its vertex properties.")
            if info["format"] != "ply" and request.output_format == "ply":
                if not info["ply_derivative"]:
                    raise HTTPException(422, "These LAS attributes cannot be represented as scalar PLY.")
                if not request.accept_derivative:
                    raise HTTPException(422, "Acknowledge that PLY cannot retain the native LAS header and CRS.")
            if any(j.status in BUSY for j in source.jobs.values()):
                raise HTTPException(409, "A crop is already active for this source.")
            if len(source.jobs) >= 8:
                raise HTTPException(429, "This source has reached its export limit. Reopen the file to start a new session.")
            operation = Operation()
            source.jobs[operation.id] = operation
            self.workers.submit(self._export, source, operation, request)
            return operation.public()

    def _export(self, source, operation, request):
        working = source.path.parent / operation.id
        with self.lock:
            operation.status = "running"
        try:
            self._progress(operation, 0)
            working.mkdir()
            output = working / f"crop.{request.output_format}"
            details = export_selection(source.path, output, request, source.sha256,
                                       lambda p: self._progress(operation, p), operation.stop.is_set)
            selection = request.selection.model_dump()
            status = {"point_count": details["retained_points"], "output_format": request.output_format,
                      "size": output.stat().st_size}
            payload = {"schema_version": 1, "source_filename": source.name, **request.model_dump(),
                       "source_points": details["source_points"], "selected_points": status["point_count"],
                       "selected_bounds_xyz": details["selected_bounds_xyz"],
                       "preserved_attributes": details["preserved_vertex_properties"],
                       "las_source": details.get("las_source"),
                       "derivative": details.get("derivative"),
                       "verification": details["verification"], "selection": selection}
            write_json_atomic(working / "selection.json", payload)
            with self.lock:
                self._progress(operation, 99)
                operation.result = status
                operation.status, operation.progress = "completed", 100
                source.used = monotonic()
        except Exception as exc:
            self._remove(working)
            self._failure(source, operation, exc, "Crop could not be saved. Check free space and try again.")

    def _job(self, source, job_id):
        if job_id not in source.jobs:
            raise HTTPException(404, "Crop job not found or expired.")
        return source.jobs[job_id]

    def job_status(self, source, job_id, cancel=False):
        with self.lock:
            job = self._job(source, job_id)
            if cancel and job.status in BUSY:
                job.stop.set()
            return {**job.public(), "cancel_requested": job.stop.is_set()}

    def ticket(self, source, job_id, kind):
        with self.lock:
            job = self._job(source, job_id)
            if job.status != "completed":
                raise HTTPException(409, "This crop is not ready to download.")
            now = monotonic()
            for key, (end, sid, jid, asset) in self.tickets.items():
                if (sid, jid, asset) == (source.id, job_id, kind) and end > now:
                    return key
            token = secrets.token_urlsafe(32)
            self.tickets[token] = (now + DOWNLOAD_TTL, source.id, job_id, kind)
            return token

    @contextmanager
    def download(self, token):
        with self.lock:
            ticket = self.tickets.get(token)
            if not ticket or monotonic() >= ticket[0] or ticket[1] not in self.sessions:
                raise HTTPException(404, "Download link expired. Request a new link.")
            _, key, job_id, kind = ticket
            source = self.sessions[key]
            job = self._job(source, job_id)
            name = "selection.json" if kind == "selection" else f"crop.{job.result['output_format']}"
            path = source.path.parent / job_id / name
            if not path.is_file():
                raise HTTPException(404, "Download is no longer available.")
            source.leases += 1
            source.used = monotonic()
        try:
            yield path, kind
        finally:
            with self.lock:
                source.leases -= 1

    def cleanup(self):
        with self.lock:
            now = monotonic()
            for key, source in list(self.sessions.items()):
                if source.in_use():
                    continue
                states = {source.scan.status} | {j.status for j in source.jobs.values()}
                ttl = (settings.completed_job_ttl_hours if any(j.status == "completed" for j in source.jobs.values())
                       else settings.failed_job_ttl_hours if {"failed", "cancelled"} & states
                       else settings.uploaded_job_ttl_hours)
                if now - source.used > ttl * 3600 and self._remove(source.path.parent):
                    del self.sessions[key]
            self.tickets = {key: grant for key, grant in self.tickets.items()
                            if grant[0] > now and grant[1] in self.sessions}
            self.directory.touch()
            stale_seconds = 3600 * max(settings.completed_job_ttl_hours, 1)
            for folder in self.directory.parent.glob("session-*"):
                try:
                    if folder != self.directory and not folder.is_symlink() and folder.is_dir() and (
                        time() - folder.stat().st_mtime > stale_seconds
                    ):
                        self._remove(folder)
                except OSError:
                    logger.warning("Could not examine a stale LiDAR directory")

    @staticmethod
    def _remove(path):
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
            return True
        except OSError:
            logger.warning("LiDAR temporary files could not be removed yet")
            return False

    def close(self):
        with self.lock:
            for source in self.sessions.values():
                source.scan.stop.set()
                if source.preview_count:
                    source.preview_count.operation.stop.set()
                for operation in source.jobs.values():
                    operation.stop.set()
        self.workers.shutdown(wait=True, cancel_futures=True)
        self._remove(self.directory)
