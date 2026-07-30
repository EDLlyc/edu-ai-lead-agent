from __future__ import annotations

import re
import unicodedata
import zipfile
from io import BytesIO
from uuid import UUID, uuid5

from docx import Document
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.errors import BrandUploadRejectedError
from app.domain.brand_knowledge import BrandChunk, ParsedBrandDocument
from app.domain.value_objects import sha256_bytes, stable_key

_BREAK_PATTERN = re.compile("[。\uff01\uff1f\uff1b!?;\\n]")
_DOCX_MAX_FILES = 2_000
_DOCX_MAX_EXPANDED_BYTES = 40 * 1024 * 1024
_DOCX_MAX_COMPRESSION_RATIO = 100


class BoundedBrandDocumentParser:
    def __init__(
        self,
        *,
        max_pages: int,
        max_characters: int,
        max_chunks: int,
        chunk_characters: int,
        overlap_characters: int,
        chunk_version: str,
    ) -> None:
        self._max_pages = max_pages
        self._max_characters = max_characters
        self._max_chunks = max_chunks
        self._chunk_characters = chunk_characters
        self._overlap_characters = overlap_characters
        self._chunk_version = chunk_version

    def parse(self, *, body: bytes, media_type: str) -> ParsedBrandDocument:
        if media_type == "application/pdf":
            parsed = self._parse_pdf(body)
        elif (
            media_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ):
            parsed = self._parse_docx(body)
        elif media_type in {"text/plain", "text/markdown"}:
            parsed = ParsedBrandDocument(text=self._decode_text(body), page_count=None)
        else:
            raise BrandUploadRejectedError(
                "unsupported_brand_file", "brand file type is unsupported"
            )
        normalized = normalize_brand_text(parsed.text)
        if len(normalized) > self._max_characters:
            raise BrandUploadRejectedError(
                "brand_text_too_large", "parsed brand text exceeded the configured limit"
            )
        if not normalized:
            raise BrandUploadRejectedError(
                "brand_text_empty", "brand document contains no usable text"
            )
        return ParsedBrandDocument(text=normalized, page_count=parsed.page_count)

    def chunk(self, *, version_id: UUID, document: ParsedBrandDocument) -> tuple[BrandChunk, ...]:
        chunks: list[BrandChunk] = []
        text = document.text
        start = 0
        while start < len(text):
            hard_end = min(start + self._chunk_characters, len(text))
            end = hard_end
            if hard_end < len(text):
                lower_bound = start + int(self._chunk_characters * 0.6)
                candidates = [
                    match.end() for match in _BREAK_PATTERN.finditer(text, lower_bound, hard_end)
                ]
                if candidates:
                    end = candidates[-1]
            raw_chunk = text[start:end]
            leading_whitespace = len(raw_chunk) - len(raw_chunk.lstrip())
            trailing_whitespace = len(raw_chunk) - len(raw_chunk.rstrip())
            chunk_start = start + leading_whitespace
            chunk_end = end - trailing_whitespace
            chunk_text = text[chunk_start:chunk_end]
            if chunk_text:
                text_hash = sha256_bytes(chunk_text.encode("utf-8"))
                ordinal = len(chunks)
                chunk_key = stable_key(version_id, ordinal, text_hash, self._chunk_version)
                chunks.append(
                    BrandChunk(
                        id=uuid5(version_id, chunk_key),
                        ordinal=ordinal,
                        text=chunk_text,
                        text_hash=text_hash,
                        char_start=chunk_start,
                        char_end=chunk_end,
                        chunk_key=chunk_key,
                    )
                )
                if len(chunks) > self._max_chunks:
                    raise BrandUploadRejectedError(
                        "brand_chunk_limit", "brand document produced too many chunks"
                    )
            if end >= len(text):
                break
            next_start = max(start + 1, end - self._overlap_characters)
            while next_start < end and text[next_start].isspace():
                next_start += 1
            start = next_start
        if not chunks:
            raise BrandUploadRejectedError(
                "brand_text_empty", "brand document contains no usable text"
            )
        return tuple(chunks)

    def _parse_pdf(self, body: bytes) -> ParsedBrandDocument:
        try:
            reader = PdfReader(BytesIO(body), strict=True)
        except (PdfReadError, ValueError, TypeError, OSError):
            raise BrandUploadRejectedError(
                "malformed_brand_pdf", "brand PDF could not be parsed"
            ) from None
        if reader.is_encrypted:
            raise BrandUploadRejectedError(
                "encrypted_brand_pdf", "encrypted brand PDF is not accepted"
            )
        if len(reader.pages) > self._max_pages:
            raise BrandUploadRejectedError("brand_page_limit", "brand PDF exceeded the page limit")
        parts: list[str] = []
        character_count = 0
        try:
            for page in reader.pages:
                page_text = page.extract_text() or ""
                character_count += len(page_text)
                if character_count > self._max_characters:
                    raise BrandUploadRejectedError(
                        "brand_text_too_large", "parsed brand text exceeded the configured limit"
                    )
                parts.append(page_text)
        except BrandUploadRejectedError:
            raise
        except Exception:
            raise BrandUploadRejectedError(
                "malformed_brand_pdf", "brand PDF could not be parsed"
            ) from None
        return ParsedBrandDocument(text="\n\n".join(parts), page_count=len(reader.pages))

    def _parse_docx(self, body: bytes) -> ParsedBrandDocument:
        self._inspect_docx_archive(body)
        try:
            document = Document(BytesIO(body))
        except (ValueError, TypeError, OSError, zipfile.BadZipFile):
            raise BrandUploadRejectedError(
                "malformed_brand_docx", "brand DOCX could not be parsed"
            ) from None
        parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        for table in document.tables:
            for row in table.rows:
                row_text = "\t".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    parts.append(row_text)
        return ParsedBrandDocument(text="\n\n".join(parts), page_count=None)

    @staticmethod
    def _inspect_docx_archive(body: bytes) -> None:
        try:
            with zipfile.ZipFile(BytesIO(body)) as archive:
                entries = archive.infolist()
                if len(entries) > _DOCX_MAX_FILES:
                    raise BrandUploadRejectedError(
                        "brand_archive_limit", "brand DOCX archive contains too many entries"
                    )
                expanded_bytes = 0
                for entry in entries:
                    name = entry.filename.casefold()
                    if "vbaproject.bin" in name or name.startswith("word/embeddings/"):
                        raise BrandUploadRejectedError(
                            "unsafe_brand_docx", "brand DOCX contains prohibited embedded content"
                        )
                    expanded_bytes += entry.file_size
                    if expanded_bytes > _DOCX_MAX_EXPANDED_BYTES:
                        raise BrandUploadRejectedError(
                            "brand_archive_limit", "brand DOCX expanded content is too large"
                        )
                    if (
                        entry.compress_size > 0
                        and entry.file_size / entry.compress_size > _DOCX_MAX_COMPRESSION_RATIO
                    ):
                        raise BrandUploadRejectedError(
                            "brand_archive_limit", "brand DOCX compression ratio is unsafe"
                        )
                    if name.endswith(".rels"):
                        relationships = archive.read(entry)
                        if (
                            b'TargetMode="External"' in relationships
                            or b"TargetMode='External'" in relationships
                        ):
                            raise BrandUploadRejectedError(
                                "unsafe_brand_docx", "brand DOCX contains external relationships"
                            )
        except BrandUploadRejectedError:
            raise
        except (zipfile.BadZipFile, KeyError, OSError):
            raise BrandUploadRejectedError(
                "malformed_brand_docx", "brand DOCX could not be parsed"
            ) from None

    @staticmethod
    def _decode_text(body: bytes) -> str:
        try:
            return body.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise BrandUploadRejectedError(
                "invalid_brand_encoding", "brand text must be UTF-8"
            ) from None


def normalize_brand_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u200b", "").replace("\ufeff", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in normalized.split("\n")]
    output: list[str] = []
    previous_blank = False
    for line in lines:
        blank = not line
        if blank and previous_blank:
            continue
        output.append(line)
        previous_blank = blank
    return "\n".join(output).strip()
