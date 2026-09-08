import time

import httpx


class VoyageEmbeddingProvider:
    def __init__(self, *, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        with httpx.Client(timeout=30.0) as client:
            started = time.perf_counter()
            response = client.post(
                "https://api.voyageai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": texts, "input_type": "document"},
            )
            duration_ms = int((time.perf_counter() - started) * 1000)
            response.raise_for_status()
            payload = response.json()
            usage = payload.get("usage") or {}
            total = int(usage.get("total_tokens") or 0)
            from app.services.usage_recorder import record_llm_usage

            record_llm_usage(
                provider="voyage",
                model=self.model,
                prompt_tokens=total,
                completion_tokens=0,
                total_tokens=total,
                duration_ms=duration_ms,
                model_reported=(payload.get("model") if isinstance(payload, dict) else None),
                usage_reported=True,
            )
            rows = sorted(payload["data"], key=lambda row: row["index"])
            return [row["embedding"] for row in rows]
