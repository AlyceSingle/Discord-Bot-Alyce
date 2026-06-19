from typing import Optional

from src.chat.cogs.image_command_cog import ImageCommandCog
from src.chat.config.chat_config import IMAGE_COMMAND_CONFIG


class FakeAttachment:
    def __init__(
        self,
        *,
        filename: str,
        content_type: Optional[str],
        size: int,
    ) -> None:
        self.filename = filename
        self.content_type = content_type
        self.size = size


def test_reference_image_metadata_accepts_image_content_type():
    attachment = FakeAttachment(
        filename="reference.bin",
        content_type="image/png",
        size=1024,
    )

    assert ImageCommandCog._validate_reference_image_metadata(attachment) is None


def test_reference_image_metadata_accepts_image_extension_without_content_type():
    attachment = FakeAttachment(
        filename="reference.webp",
        content_type=None,
        size=1024,
    )

    assert ImageCommandCog._validate_reference_image_metadata(attachment) is None


def test_reference_image_metadata_rejects_non_image_content_type():
    attachment = FakeAttachment(
        filename="notes.txt",
        content_type="text/plain",
        size=1024,
    )

    assert ImageCommandCog._validate_reference_image_metadata(attachment) == (
        "参考图必须是图片附件。"
    )


def test_reference_image_metadata_rejects_large_attachment(monkeypatch):
    monkeypatch.setitem(IMAGE_COMMAND_CONFIG, "MAX_REFERENCE_IMAGE_BYTES", 3)
    attachment = FakeAttachment(
        filename="reference.png",
        content_type="image/png",
        size=4,
    )

    assert "参考图太大" in ImageCommandCog._validate_reference_image_metadata(
        attachment
    )
