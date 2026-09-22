from __future__ import annotations

import os
from collections.abc import Callable

import httpx

import replicate

from app.core.config import get_settings
from app.services.hero_image_error import HeroImageError

_DOWNLOAD_TIMEOUT = 60.0


def _is_timeout(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return True
    text = str(exc).lower()
    return "timed out" in text or "timeout" in text


def _download(url: str) -> bytes:
    try:
        response = httpx.get(url, timeout=_DOWNLOAD_TIMEOUT, follow_redirects=True)
        response.raise_for_status()
    except Exception as exc:
        if _is_timeout(exc):
            raise HeroImageError(
                "timeout",
                "La generación de imagen excedió el tiempo de espera",
                504,
            ) from exc
        raise HeroImageError(
            "download_error",
            "No se pudo descargar la imagen",
            502,
        ) from exc
    if not response.content:
        raise HeroImageError("empty_output", "El modelo no devolvió una imagen", 502)
    return response.content


def _coerce_bytes(output: object) -> bytes:
    if output is None:
        raise HeroImageError("empty_output", "El modelo no devolvió una imagen", 502)
    if isinstance(output, (bytes, bytearray)):
        if not output:
            raise HeroImageError("empty_output", "El modelo no devolvió una imagen", 502)
        return bytes(output)
    if isinstance(output, str):
        text = output.strip()
        if not text.startswith("http"):
            raise HeroImageError("empty_output", "El modelo no devolvió una imagen", 502)
        return _download(text)
    if isinstance(output, (list, tuple)):
        if not output:
            raise HeroImageError("empty_output", "El modelo no devolvió una imagen", 502)
        return _coerce_bytes(output[0])
    reader = getattr(output, "read", None)
    if callable(reader):
        data = reader()
        if isinstance(data, str):
            data = data.encode()
        if not data:
            raise HeroImageError("empty_output", "El modelo no devolvió una imagen", 502)
        return bytes(data)
    url = getattr(output, "url", None)
    if isinstance(url, str) and url.strip().startswith("http"):
        return _download(url.strip())
    text = str(output).strip()
    if text.startswith("http"):
        return _download(text)
    raise HeroImageError("empty_output", "El modelo no devolvió una imagen", 502)


class ReplicateImageProvider:
    def __init__(self, runner: Callable[..., object] | None = None) -> None:
        self.runner = runner

    def generate(self, prompt: str) -> bytes:
        settings = get_settings()
        token = (settings.replicate_api_token or "").strip()
        if not token:
            raise HeroImageError("missing_replicate_token", "Falta REPLICATE_API_TOKEN", 503)
        text = (prompt or "").strip()
        if not text:
            raise HeroImageError("empty_prompt", "El modelo no devolvió un prompt", 502)
        runner = self.runner or replicate.run
        previous = os.environ.get("REPLICATE_API_TOKEN")
        os.environ["REPLICATE_API_TOKEN"] = token
        try:
            output = runner(
                settings.article_image_model,
                input={
                    "prompt": text,
                    "go_fast": settings.article_image_go_fast,
                    "megapixels": settings.article_image_megapixels,
                    "num_outputs": 1,
                    "aspect_ratio": settings.article_image_aspect_ratio,
                    "output_format": settings.article_image_output_format,
                    "output_quality": settings.article_image_output_quality,
                    "num_inference_steps": settings.article_image_num_inference_steps,
                },
            )
        except HeroImageError:
            raise
        except Exception as exc:
            if _is_timeout(exc):
                raise HeroImageError(
                    "timeout",
                    "La generación de imagen excedió el tiempo de espera",
                    504,
                ) from exc
            raise HeroImageError(
                "replicate_error",
                "No se pudo generar la imagen",
                502,
            ) from exc
        finally:
            if previous is None:
                os.environ.pop("REPLICATE_API_TOKEN", None)
            else:
                os.environ["REPLICATE_API_TOKEN"] = previous
        return _coerce_bytes(output)
