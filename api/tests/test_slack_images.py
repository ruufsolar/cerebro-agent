import asyncio
import io
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from PIL import Image

from cerebro.agent.runner import TranscriptAttachment
from cerebro.config import AppConfig
from cerebro.slack.images import (
    DownloadedImage,
    ImageFailureCategory,
    SlackImageError,
    SlackSdkFileClient,
    ingest_trigger_images,
    sweep_abandoned_image_directories,
)


def image_bytes(image_format: str, *, animated: bool = False) -> bytes:
    output = io.BytesIO()
    first = Image.new("RGB", (12, 8), "white")
    if animated:
        second = Image.new("RGB", (12, 8), "black")
        first.save(output, format=image_format, save_all=True, append_images=[second], duration=10)
    else:
        first.save(output, format=image_format)
    return output.getvalue()


class BytesFileClient:
    def __init__(self, data: bytes, mimetype: str) -> None:
        self.data = data
        self.mimetype = mimetype

    async def download(
        self, attachment: TranscriptAttachment, destination: Path
    ) -> DownloadedImage:
        del attachment
        await asyncio.to_thread(destination.write_bytes, self.data)
        return DownloadedImage(destination, self.mimetype)

    async def close(self) -> None:
        return None


class SlowFileClient(BytesFileClient):
    async def download(
        self, attachment: TranscriptAttachment, destination: Path
    ) -> DownloadedImage:
        await asyncio.sleep(0.05)
        return await super().download(attachment, destination)


@pytest.mark.parametrize(
    ("mimetype", "image_format", "suffix"),
    [
        ("image/png", "PNG", ".png"),
        ("image/jpeg", "JPEG", ".jpg"),
        ("image/webp", "WEBP", ".webp"),
    ],
)
async def test_valid_images_are_private_and_ephemeral(
    tmp_path: Path, mimetype: str, image_format: str, suffix: str
) -> None:
    config = AppConfig(image_temp_root=str(tmp_path / "cerebro-images"))
    attachment = TranscriptAttachment("F1", "bank.png", mimetype, 1_000)

    async with ingest_trigger_images(
        run_id=uuid4(),
        attachments=(attachment,),
        requested=1,
        rejected=0,
        client=BytesFileClient(image_bytes(image_format), mimetype),
        config=config,
    ) as batch:
        assert batch.ingestion.downloaded == 1
        assert batch.paths[0].suffix == suffix
        assert batch.paths[0].exists()
        assert oct(batch.paths[0].stat().st_mode & 0o777) == "0o600"
        assert oct(batch.paths[0].parent.stat().st_mode & 0o777) == "0o700"
        run_directory = batch.paths[0].parent

    assert not run_directory.exists()


@pytest.mark.parametrize(
    ("data", "mimetype", "category"),
    [
        (b"not an image", "image/png", ImageFailureCategory.MALFORMED),
        (image_bytes("PNG"), "image/jpeg", ImageFailureCategory.MIME_MISMATCH),
        (image_bytes("WEBP", animated=True), "image/webp", ImageFailureCategory.ANIMATED),
    ],
)
async def test_invalid_image_bytes_are_rejected_and_cleaned(
    tmp_path: Path,
    data: bytes,
    mimetype: str,
    category: ImageFailureCategory,
) -> None:
    config = AppConfig(image_temp_root=str(tmp_path / "cerebro-images"))
    async with ingest_trigger_images(
        run_id=uuid4(),
        attachments=(TranscriptAttachment("F1", None, mimetype, len(data)),),
        requested=1,
        rejected=0,
        client=BytesFileClient(data, mimetype),
        config=config,
    ) as batch:
        assert batch.paths == ()
        assert batch.ingestion.failure_categories == (category.value,)
    assert list((tmp_path / "cerebro-images").iterdir()) == []


@pytest.mark.parametrize("failure", [RuntimeError("provider failed"), asyncio.CancelledError()])
async def test_run_directory_is_cleaned_when_consumer_fails_or_is_cancelled(
    tmp_path: Path, failure: BaseException
) -> None:
    data = image_bytes("PNG")
    config = AppConfig(image_temp_root=str(tmp_path / "cerebro-images"))
    with pytest.raises(type(failure)):
        async with ingest_trigger_images(
            run_id=uuid4(),
            attachments=(TranscriptAttachment("F1", None, "image/png", len(data)),),
            requested=1,
            rejected=0,
            client=BytesFileClient(data, "image/png"),
            config=config,
        ):
            raise failure
    assert list((tmp_path / "cerebro-images").iterdir()) == []


async def test_file_timeout_is_categorical_and_cleans_partial_run(tmp_path: Path) -> None:
    data = image_bytes("PNG")
    config = AppConfig.model_construct(
        image_temp_root=str(tmp_path / "cerebro-images"),
        slack_file_timeout_seconds=0.01,
        slack_image_batch_timeout_seconds=0.1,
    )
    async with ingest_trigger_images(
        run_id=uuid4(),
        attachments=(TranscriptAttachment("F1", None, "image/png", len(data)),),
        requested=1,
        rejected=0,
        client=SlowFileClient(data, "image/png"),
        config=config,
    ) as batch:
        assert batch.paths == ()
        assert batch.ingestion.failure_categories == (ImageFailureCategory.DOWNLOAD_TIMEOUT.value,)
    assert list((tmp_path / "cerebro-images").iterdir()) == []


async def test_pixel_ceiling_and_decompression_bomb_are_safe_categories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = image_bytes("PNG")
    dimensions_config = AppConfig(image_temp_root=str(tmp_path / "dimensions"), max_image_pixels=10)
    async with ingest_trigger_images(
        run_id=uuid4(),
        attachments=(TranscriptAttachment("F1", None, "image/png", len(data)),),
        requested=1,
        rejected=0,
        client=BytesFileClient(data, "image/png"),
        config=dimensions_config,
    ) as batch:
        assert batch.ingestion.failure_categories == (ImageFailureCategory.DIMENSIONS.value,)

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)
    bomb_config = AppConfig(image_temp_root=str(tmp_path / "bomb"), max_image_pixels=25_000_000)
    async with ingest_trigger_images(
        run_id=uuid4(),
        attachments=(TranscriptAttachment("F1", None, "image/png", len(data)),),
        requested=1,
        rejected=0,
        client=BytesFileClient(data, "image/png"),
        config=bomb_config,
    ) as batch:
        assert batch.ingestion.failure_categories == (
            ImageFailureCategory.DECOMPRESSION_BOMB.value,
        )


class FakeWebClient:
    def __init__(self, file_object: dict[str, Any]) -> None:
        self.file_object = file_object
        self.calls: list[str] = []

    async def files_info(self, *, file: str) -> dict[str, Any]:
        self.calls.append(file)
        return {"file": self.file_object}


class FakeContent:
    def __init__(self, data: bytes) -> None:
        self.data = data

    async def iter_chunked(self, size: int) -> Any:
        del size
        yield self.data


class FakeResponse:
    def __init__(
        self, status: int, data: bytes = b"", *, headers: dict[str, str] | None = None
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self.content = FakeContent(data)
        self.content_length = len(data) or None

    async def __aenter__(self) -> "FakeResponse":
        return self

    async def __aexit__(self, *args: object) -> None:
        del args


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str], bool]] = []
        self.closed = False

    def get(self, url: str, *, headers: dict[str, str], allow_redirects: bool) -> FakeResponse:
        self.calls.append((url, headers, allow_redirects))
        return self.responses.pop(0)


async def test_slack_file_client_uses_files_info_bearer_and_validated_redirect(
    tmp_path: Path,
) -> None:
    data = image_bytes("PNG")
    web = FakeWebClient(
        {
            "mode": "hosted",
            "is_external": False,
            "mimetype": "image/png",
            "size": len(data),
            "url_private_download": "https://files.slack.com/files-pri/T-F/file.png",
        }
    )
    session = FakeSession(
        [
            FakeResponse(302, headers={"Location": "https://downloads.slack-edge.com/file.png"}),
            FakeResponse(200, data),
        ]
    )
    client = SlackSdkFileClient(
        AppConfig(slack_bot_token="xoxb-secret"),
        web_client=web,
        session=session,  # type: ignore[arg-type]
    )

    result = await client.download(
        TranscriptAttachment("F1", None, "image/png", len(data)),
        tmp_path / "download",
    )

    assert web.calls == ["F1"]
    assert result.path.read_bytes() == data
    assert [call[2] for call in session.calls] == [False, False]
    assert all(call[1] == {"Authorization": "Bearer xoxb-secret"} for call in session.calls)


async def test_slack_file_client_rejects_stream_larger_than_advertised(tmp_path: Path) -> None:
    data = image_bytes("PNG")
    web = FakeWebClient(
        {
            "mode": "hosted",
            "is_external": False,
            "mimetype": "image/png",
            "size": len(data) - 1,
            "url_private_download": "https://files.slack.com/file.png",
        }
    )
    client = SlackSdkFileClient(
        AppConfig(slack_bot_token="xoxb-secret"),
        web_client=web,
        session=FakeSession([FakeResponse(200, data)]),  # type: ignore[arg-type]
    )

    with pytest.raises(SlackImageError) as failure:
        await client.download(
            TranscriptAttachment("F1", None, "image/png", len(data) - 1),
            tmp_path / "download",
        )
    assert failure.value.category is ImageFailureCategory.SIZE_OVERFLOW


async def test_slack_file_client_limits_redirects(tmp_path: Path) -> None:
    data = image_bytes("PNG")
    web = FakeWebClient(
        {
            "mode": "hosted",
            "is_external": False,
            "mimetype": "image/png",
            "size": len(data),
            "url_private_download": "https://files.slack.com/file.png",
        }
    )
    redirects = [
        FakeResponse(302, headers={"Location": "https://files.slack.com/next.png"})
        for _ in range(4)
    ]
    client = SlackSdkFileClient(
        AppConfig(slack_bot_token="xoxb-secret"),
        web_client=web,
        session=FakeSession(redirects),  # type: ignore[arg-type]
    )

    with pytest.raises(SlackImageError) as failure:
        await client.download(
            TranscriptAttachment("F1", None, "image/png", len(data)),
            tmp_path / "download",
        )
    assert failure.value.category is ImageFailureCategory.TOO_MANY_REDIRECTS


@pytest.mark.parametrize(
    ("url", "status", "category"),
    [
        ("http://files.slack.com/file.png", 200, ImageFailureCategory.INVALID_ORIGIN),
        ("https://evil.example/file.png", 200, ImageFailureCategory.INVALID_ORIGIN),
        ("https://files.slack.com/file.png", 429, ImageFailureCategory.RATE_LIMITED),
        ("https://files.slack.com/file.png", 500, ImageFailureCategory.HTTP_ERROR),
    ],
)
async def test_slack_file_client_rejects_origins_and_http_failures(
    tmp_path: Path, url: str, status: int, category: ImageFailureCategory
) -> None:
    data = image_bytes("PNG")
    web = FakeWebClient(
        {
            "mode": "hosted",
            "is_external": False,
            "mimetype": "image/png",
            "size": len(data),
            "url_private_download": url,
        }
    )
    client = SlackSdkFileClient(
        AppConfig(slack_bot_token="xoxb-secret"),
        web_client=web,
        session=FakeSession([FakeResponse(status, data)]),  # type: ignore[arg-type]
    )

    with pytest.raises(SlackImageError) as failure:
        await client.download(
            TranscriptAttachment("F1", None, "image/png", len(data)), tmp_path / "download"
        )
    assert failure.value.category is category
    assert "evil.example" not in str(failure.value)
    assert "xoxb-secret" not in str(failure.value)


def test_startup_sweep_removes_only_cerebro_run_directories(tmp_path: Path) -> None:
    root = tmp_path / "cerebro-images"
    abandoned = root / "run-deadbeef"
    unrelated = root / "keep-me"
    abandoned.mkdir(parents=True)
    unrelated.mkdir()
    (abandoned / "image.png").write_bytes(b"private")

    removed = sweep_abandoned_image_directories(AppConfig(image_temp_root=str(root)))

    assert removed == 1
    assert not abandoned.exists()
    assert unrelated.exists()
    assert os.path.isdir(unrelated)


async def test_symlinked_temp_root_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    root = tmp_path / "cerebro-images"
    root.symlink_to(target, target_is_directory=True)
    data = image_bytes("PNG")

    with pytest.raises(RuntimeError, match="not a private directory"):
        async with ingest_trigger_images(
            run_id=uuid4(),
            attachments=(TranscriptAttachment("F1", None, "image/png", len(data)),),
            requested=1,
            rejected=0,
            client=BytesFileClient(data, "image/png"),
            config=AppConfig(image_temp_root=str(root)),
        ):
            pass
