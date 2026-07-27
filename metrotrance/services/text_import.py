from __future__ import annotations

from io import BytesIO
from pathlib import Path


class TextImportError(ValueError):
    pass


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise TextImportError("Не удалось определить кодировку текстового файла")


def import_text(filename: str, content: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md"}:
        text = _decode_text(content)
    elif suffix == ".docx":
        try:
            from docx import Document
        except ImportError as exc:
            raise TextImportError("Для импорта DOCX не установлен компонент python-docx") from exc
        try:
            document = Document(BytesIO(content))
        except Exception as exc:  # noqa: BLE001
            raise TextImportError(f"Не удалось прочитать DOCX: {exc}") from exc
        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs]
        text = "\n\n".join(value for value in paragraphs if value)
    else:
        raise TextImportError("Поддерживаются файлы TXT, MD и DOCX")

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(normalized) < 20:
        raise TextImportError("В файле слишком мало текста")
    return normalized
