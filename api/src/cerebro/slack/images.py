"""Ephemeral, authenticated Slack image retrieval for a single agent run."""

import asyncio
import inspect
import os
import secrets
import shutil
import stat
import warnings
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit
from uuid import UUID

import aiohttp
from PIL import Image, UnidentifiedImageError
from slack_sdk.web.async_client import AsyncWebClient

from cerebro.agent.runner import ImageIngestion, TranscriptAttachment
from cerebro.config import AppConfig, get_config
from cerebro.slack.events import ALLOWED_IMAGE_MIMETYPES

_MIME_FORMATS = {
    "image/png": ("PNG", ".png"),
    "image/jpeg": ("JPEG", ".jpg"),
    "image/webp": ("WEBP", ".webp"),
}
_SLACK_HOST_SUFFIXES = (".slack.com", ".slack-files.com", ".slack-edge.com")
_SLACK_HOSTS = {"slack.com", "slack-files.com", "slack-edge.com"}


class ImageFailureCategory(StrEnum):
    FILE_INFO = "file_info_failed"
    NOT_HOSTED = "not_slack_hosted"
    UNSUPPORTED_TYPE = "unsupported_type"
    INVALID_SIZE = "invalid_size"
    INVALID_ORIGIN = "invalid_origin"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    RATE_LIMITED = "rate_limited"
    HTTP_ERROR = "http_error"
    DOWNLOAD_TIMEOUT = "download_timeout"
    BATCH_TIMEOUT = "batch_timeout"
    SIZE_OVERFLOW = "size_overflow"
    MIME_MISMATCH = "mime_mismatch"
    MALFORMED = "malformed_image"
    ANIMATED = "animated_image"
    DIMENSIONS = "invalid_dimensions"
    DECOMPRESSION_BOMB = "decompression_bomb"


class SlackImageError(RuntimeError):
    def __init__(self, category: ImageFailureCategory) -> None:
        super().__init__(category.value)
        self.category = category


@dataclass(frozen=True)
class DownloadedImage:
    path: Path
    mimetype: str


@dataclass(frozen=True)
class ImageBatch:
    paths: tuple[Path, ...]
    ingestion: ImageIngestion


class SlackFileClient(Protocol):
    async def download(
        self, attachment: TranscriptAttachment, destination: Path
    ) -> DownloadedImage: ...

    async def close(self) -> None: ...


def _is_allowed_slack_url(value: str) -> bool:
    parsed = urlsplit(value)
    hostname = (parsed.hostname or "").lower()
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and parsed.port in {None, 443}
        and (hostname in _SLACK_HOSTS or hostname.endswith(_SLACK_HOST_SUFFIXES))
    )


class SlackSdkFileClient:
    """Resolve private Slack files and stream them without retaining their URLs."""

    def __init__(
        self,
        config: AppConfig | None = None,
        *,
        web_client: Any | None = None,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.config = config or get_config()
        self._web_client: Any = web_client or AsyncWebClient(token=self.config.slack_bot_token)
        self._session = session
        self._owns_session = session is None

    async def _http_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.config.slack_file_timeout_seconds)
            )
        return self._session

    async def _file_info(self, attachment: TranscriptAttachment) -> tuple[str, str, int]:
        try:
            response = await self._web_client.files_info(file=attachment.slack_file_id)
        except Exception as exc:
            raise SlackImageError(ImageFailureCategory.FILE_INFO) from exc
        raw = response.get("file") if hasattr(response, "get") else None
        if not isinstance(raw, dict):
            raise SlackImageError(ImageFailureCategory.FILE_INFO)
        mimetype = raw.get("mimetype")
        size = raw.get("size")
        mode = raw.get("mode")
        is_external = raw.get("is_external", False)
        if mode != "hosted" or is_external is True:
            raise SlackImageError(ImageFailureCategory.NOT_HOSTED)
        if mimetype not in ALLOWED_IMAGE_MIMETYPES:
            raise SlackImageError(ImageFailureCategory.UNSUPPORTED_TYPE)
        if not isinstance(size, int) or size <= 0 or size > self.config.max_image_bytes:
            raise SlackImageError(ImageFailureCategory.INVALID_SIZE)
        if mimetype != attachment.mimetype:
            raise SlackImageError(ImageFailureCategory.MIME_MISMATCH)
        url = raw.get("url_private_download") or raw.get("url_private")
        if not isinstance(url, str) or not _is_allowed_slack_url(url):
            raise SlackImageError(ImageFailureCategory.INVALID_ORIGIN)
        return url, mimetype, size

    async def download(
        self, attachment: TranscriptAttachment, destination: Path
    ) -> DownloadedImage:
        url, mimetype, advertised_size = await self._file_info(attachment)
        session = await self._http_session()
        headers = {"Authorization": f"Bearer {self.config.slack_bot_token}"}
        redirects = 0
        while True:
            async with session.get(
                url,
                headers=headers,
                allow_redirects=False,
            ) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location:
                        raise SlackImageError(ImageFailureCategory.HTTP_ERROR)
                    redirects += 1
                    if redirects > 3:
                        raise SlackImageError(ImageFailureCategory.TOO_MANY_REDIRECTS)
                    next_url = urljoin(url, location)
                    if not _is_allowed_slack_url(next_url):
                        raise SlackImageError(ImageFailureCategory.INVALID_ORIGIN)
                    url = next_url
                    continue
                if response.status == 429:
                    raise SlackImageError(ImageFailureCategory.RATE_LIMITED)
                if response.status < 200 or response.status >= 300:
                    raise SlackImageError(ImageFailureCategory.HTTP_ERROR)
                content_length = response.content_length
                if content_length is not None and (
                    content_length > self.config.max_image_bytes or content_length > advertised_size
                ):
                    raise SlackImageError(ImageFailureCategory.SIZE_OVERFLOW)
                written = 0
                descriptor = os.open(
                    destination,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    stat.S_IRUSR | stat.S_IWUSR,
                )
                with os.fdopen(descriptor, "wb") as output:
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        written += len(chunk)
                        if written > self.config.max_image_bytes or written > advertised_size:
                            raise SlackImageError(ImageFailureCategory.SIZE_OVERFLOW)
                        output.write(chunk)
                if written <= 0:
                    raise SlackImageError(ImageFailureCategory.INVALID_SIZE)
                return DownloadedImage(path=destination, mimetype=mimetype)

    async def close(self) -> None:
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()
        close = getattr(self._web_client, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result


def _validate_image(downloaded: DownloadedImage, config: AppConfig) -> Path:
    expected_format, suffix = _MIME_FORMATS[downloaded.mimetype]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(downloaded.path) as image:
                if image.format != expected_format:
                    raise SlackImageError(ImageFailureCategory.MIME_MISMATCH)
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > config.max_image_pixels:
                    raise SlackImageError(ImageFailureCategory.DIMENSIONS)
                if getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) != 1:
                    raise SlackImageError(ImageFailureCategory.ANIMATED)
                image.verify()
    except SlackImageError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise SlackImageError(ImageFailureCategory.DECOMPRESSION_BOMB) from exc
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        raise SlackImageError(ImageFailureCategory.MALFORMED) from exc
    final_path = downloaded.path.with_suffix(suffix)
    downloaded.path.replace(final_path)
    os.chmod(final_path, stat.S_IRUSR | stat.S_IWUSR)
    return final_path


def _prepare_run_directory(config: AppConfig, run_id: UUID) -> Path:
    root = Path(config.image_temp_root)
    if root.exists():
        if root.is_symlink() or not root.is_dir():
            raise RuntimeError("image temporary root is not a private directory")
    else:
        root.mkdir(mode=0o700, parents=True)
    os.chmod(root, stat.S_IRWXU)
    run_dir = root / f"run-{run_id}-{secrets.token_hex(4)}"
    run_dir.mkdir(mode=0o700)
    return run_dir


def sweep_abandoned_image_directories(config: AppConfig | None = None) -> int:
    """Remove only Cerebro run directories beneath the configured dedicated root."""
    config = config or get_config()
    root = Path(config.image_temp_root)
    if not root.exists() or root.is_symlink() or not root.is_dir():
        return 0
    removed = 0
    for child in root.iterdir():
        if child.name.startswith("run-") and child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
            removed += 1
    return removed


@asynccontextmanager
async def ingest_trigger_images(
    *,
    run_id: UUID,
    attachments: tuple[TranscriptAttachment, ...],
    requested: int,
    rejected: int,
    client: SlackFileClient | None = None,
    config: AppConfig | None = None,
) -> AsyncIterator[ImageBatch]:
    config = config or get_config()
    client = client or get_slack_file_client()
    run_dir = _prepare_run_directory(config, run_id)
    paths: list[Path] = []
    failures: list[str] = []
    try:
        try:
            async with asyncio.timeout(config.slack_image_batch_timeout_seconds):
                for index, attachment in enumerate(attachments[: config.max_images], start=1):
                    destination = run_dir / f"image-{index}.download"
                    try:
                        async with asyncio.timeout(config.slack_file_timeout_seconds):
                            downloaded = await client.download(attachment, destination)
                            paths.append(_validate_image(downloaded, config))
                    except TimeoutError:
                        failures.append(ImageFailureCategory.DOWNLOAD_TIMEOUT.value)
                    except SlackImageError as exc:
                        failures.append(exc.category.value)
        except TimeoutError:
            failures.append(ImageFailureCategory.BATCH_TIMEOUT.value)
        yield ImageBatch(
            paths=tuple(paths),
            ingestion=ImageIngestion(
                requested=requested,
                metadata_accepted=len(attachments),
                downloaded=len(paths),
                rejected=rejected,
                failure_categories=tuple(sorted(set(failures))),
            ),
        )
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


_file_client: SlackFileClient | None = None


def get_slack_file_client() -> SlackFileClient:
    global _file_client
    if _file_client is None:
        _file_client = SlackSdkFileClient()
    return _file_client


def set_slack_file_client(client: SlackFileClient | None) -> None:
    global _file_client
    _file_client = client


async def close_slack_file_client() -> None:
    global _file_client
    client = _file_client
    _file_client = None
    if client is not None:
        await client.close()
