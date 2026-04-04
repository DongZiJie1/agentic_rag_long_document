"""MinerU PDF parser integration - calls MinerU Docker HTTP API"""
import logging
from pathlib import Path
from typing import Literal

import httpx

from app.config import MinerUConfig

logger = logging.getLogger(__name__)


class MinerUParseError(Exception):
    """Raised when MinerU API returns an error."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"MinerU API error {status_code}: {detail}")


class MinerUParser:
    """MinerU document parser via HTTP API (Docker service).

    Calls the ``/file_parse`` endpoint exposed by the MinerU container.
    See ``docker-compose.yml`` for service deployment.
    """

    def __init__(self, config: MinerUConfig):
        self.api_url = config.api_url.rstrip("/")
        self.backend = config.backend
        self.parse_method = config.parse_method
        self.lang_list = config.lang_list
        self.return_md = config.return_md
        self.timeout = config.timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_pdf(
        self,
        file_path: str | Path,
        *,
        parse_method: Literal["ocr", "txt", "auto"] | None = None,
        lang_list: str | None = None,
        return_md: bool | None = None,
    ) -> dict:
        """Parse a PDF file via the MinerU ``/file_parse`` endpoint.

        Args:
            file_path: Path to the local PDF file.
            parse_method: ``"ocr"`` | ``"txt"`` | ``"auto"`` (default from config).
            lang_list: Language hint, e.g. ``"ch"`` for Chinese.
            return_md: Whether to request Markdown output.

        Returns:
            Parsed JSON response from MinerU.

        Raises:
            FileNotFoundError: If *file_path* does not exist.
            MinerUParseError: If the API returns a non-2xx status code.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Input file not found: {file_path}")

        url = f"{self.api_url}/file_parse"
        data = {
            "backend": self.backend,
            "parse_method": parse_method or self.parse_method,
            "lang_list": lang_list or self.lang_list,
            "return_md": str(return_md if return_md is not None else self.return_md).lower(),
        }

        logger.info("MinerU parse request: %s %s", url, data)

        with open(file_path, "rb") as fh:
            files = {"files": (file_path.name, fh, "application/pdf")}
            response = httpx.post(
                url,
                data=data,
                files=files,
                timeout=self.timeout,
            )

        if response.status_code != 200:
            raise MinerUParseError(response.status_code, response.text)

        result = response.json()
        logger.info("MinerU parse completed: %s", file_path.name)
        return result

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def extract_markdown(self, file_path: str | Path, **kwargs) -> str:
        """Parse a PDF and return the Markdown content as a string."""
        result = self.parse_pdf(file_path, return_md=True, **kwargs)
        return result.get("md_content", result.get("markdown", ""))

    def extract_content_list(self, file_path: str | Path, **kwargs) -> list[dict]:
        """Parse a PDF and return the structured content list."""
        result = self.parse_pdf(file_path, **kwargs)
        return result.get("content_list", [])
