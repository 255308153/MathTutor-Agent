from __future__ import annotations

import inspect
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from ..core.config import MathTutorSettings
from ..provider_gaps import provider_evidence_gap, provider_exception_gap
from .schema import RAGSearchResult


DOC_TYPES = {"concept_note", "question_explanation", "mistake_pattern", "learning_strategy"}


class RAGProviderSearchClient(Protocol):
    def search(
        self,
        *,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 3,
    ) -> Any:
        """Return provider-native search records."""


class RAGProviderSearchError(RuntimeError):
    pass


class RAGProviderSchemaError(RuntimeError):
    pass


@dataclass(frozen=True)
class VikingRAGProviderConfig:
    provider_name: str
    provider_mode: str
    collection: str
    namespace: str = ""
    endpoint: str = ""
    api_key: str = ""
    search_path: str = "/search"
    timeout_seconds: float = 5.0
    supports_metadata_filter: bool = True


class VikingKnowledgeRAGAdapter:
    """VikingDB/OpenViking adapter behind the stable KnowledgeRAG boundary."""

    allows_question_to_concept_fallback = False

    def __init__(
        self,
        *,
        provider_name: str,
        provider_mode: str,
        collection: str,
        namespace: str = "",
        client: RAGProviderSearchClient | None = None,
        endpoint: str = "",
        api_key: str = "",
        search_path: str = "/search",
        timeout_seconds: float = 5.0,
        provider_supports_metadata_filter: bool = True,
        fallback: Any | None = None,
    ) -> None:
        self.config = VikingRAGProviderConfig(
            provider_name=provider_name,
            provider_mode=provider_mode,
            collection=collection,
            namespace=namespace,
            endpoint=endpoint,
            api_key=api_key,
            search_path=search_path,
            timeout_seconds=timeout_seconds,
            supports_metadata_filter=provider_supports_metadata_filter,
        )
        self.provider_mode = provider_mode
        self.provider_name = provider_name
        self.collection = collection
        self.namespace = namespace
        self.provider_supports_metadata_filter = provider_supports_metadata_filter
        self._client = client or HTTPJSONRAGSearchClient(self.config)
        self._fallback = fallback
        self.last_evidence_gaps: list[dict[str, Any]] = []

    def search(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 3,
    ) -> list[RAGSearchResult]:
        self._clear_provider_gaps()
        normalized_filters = normalize_rag_metadata_filters(filters or {})
        provider_filters = (
            normalized_filters if self.provider_supports_metadata_filter else None
        )
        fetch_limit = _provider_fetch_limit(
            limit=limit,
            filters=normalized_filters,
            provider_supports_metadata_filter=self.provider_supports_metadata_filter,
        )

        try:
            raw_response = _call_provider_search(
                self._client,
                query=query,
                filters=provider_filters,
                limit=fetch_limit,
                collection=self.collection,
                namespace=self.namespace,
            )
        except Exception as exc:
            self._record_gap(
                provider_exception_gap(
                    provider=self.provider_name,
                    operation="search",
                    exc=exc,
                )
            )
            if self._fallback is not None:
                return self._fallback.search(query=query, filters=filters, limit=limit)
            raise RAGProviderSearchError(
                f"{self.provider_name} RAG search failed before returning normalized results."
            ) from exc

        results: list[RAGSearchResult] = []
        raw_records = extract_provider_records(raw_response)
        if not raw_records:
            self._record_gap(
                provider_evidence_gap(
                    gap_type="provider_empty_result",
                    provider=self.provider_name,
                    operation="search",
                    reason=f"{self.provider_name} RAG search returned no records.",
                    details={"filters": normalized_filters},
                )
            )
            return []

        for index, raw_record in enumerate(raw_records):
            try:
                result = self._to_domain_result(raw_record)
            except RAGProviderSchemaError as exc:
                self._record_gap(
                    provider_evidence_gap(
                        gap_type="provider_schema_mismatch",
                        provider=self.provider_name,
                        operation="search",
                        reason=str(exc),
                        details={"record_index": index, "filters": normalized_filters},
                    )
                )
                continue
            if matches_rag_metadata_filter(result, normalized_filters):
                results.append(result)

        if not results and not self._has_gap("provider_schema_mismatch"):
            self._record_gap(
                provider_evidence_gap(
                    gap_type="provider_empty_result",
                    provider=self.provider_name,
                    operation="search",
                    reason=f"{self.provider_name} RAG search returned no matching normalized results.",
                    details={"filters": normalized_filters},
                )
            )
        results.sort(key=lambda result: (-result.score, result.doc_id))
        return results[:limit]

    def _record_gap(self, gap: dict[str, Any]) -> None:
        key = (gap.get("gap_type"), gap.get("operation"), gap.get("reason"))
        existing = {
            (item.get("gap_type"), item.get("operation"), item.get("reason"))
            for item in self.last_evidence_gaps
        }
        if key not in existing:
            self.last_evidence_gaps.append(gap)

    def _clear_provider_gaps(self) -> None:
        self.last_evidence_gaps = []

    def _has_gap(self, gap_type: str) -> bool:
        return any(gap.get("gap_type") == gap_type for gap in self.last_evidence_gaps)

    def _to_domain_result(self, raw_record: Any) -> RAGSearchResult:
        raw = _as_mapping(raw_record)
        payload = _payload_mapping(raw)
        doc_id = _string_value(
            _first_value(
                payload,
                raw,
                "doc_id",
                "document_id",
                "id",
                "record_id",
                "vector_id",
            )
        )
        if not doc_id:
            raise RAGProviderSchemaError("Provider result missing doc_id.")

        doc_type = _doc_type(
            _first_value(payload, raw, "doc_type", "document_type", "kind")
        )
        content = _string_value(
            _first_value(payload, raw, "content", "text", "page_content", "chunk", "body")
        )
        if not content:
            raise RAGProviderSchemaError("Provider result missing content.")
        title = _string_value(_first_value(payload, raw, "title", "name")) or content[:60]
        source = (
            _string_value(
                _first_value(payload, raw, "source", "source_ref", "uri", "url", "path")
            )
            or f"{self.provider_name}:{doc_id}"
        )
        question_id = _string_value(
            _first_value(payload, raw, "question_id", "canonical_question_id", "mathtutor_question_id")
        )
        concept_id = _string_value(
            _first_value(payload, raw, "concept_id", "canonical_concept_id", "mathtutor_concept_id")
        )
        assist_question_id = _optional_int(
            _first_value(
                payload,
                raw,
                "assist2017_question_id",
                "assistments2017_question_id",
                "assist_question_id",
            )
        )
        assist_concept_id = _optional_int(
            _first_value(
                payload,
                raw,
                "assist2017_concept_id",
                "assistments2017_concept_id",
                "assist_concept_id",
            )
        )
        canonical_mapping = _dict_value(_first_value(payload, raw, "canonical_mapping"))
        if question_id:
            canonical_mapping.setdefault("question_id", question_id)
        if concept_id:
            canonical_mapping.setdefault("concept_id", concept_id)
        if assist_question_id is not None:
            canonical_mapping.setdefault("assist2017_question_id", assist_question_id)
        if assist_concept_id is not None:
            canonical_mapping.setdefault("assist2017_concept_id", assist_concept_id)

        coverage = _dict_value(_first_value(payload, raw, "coverage"))
        coverage.setdefault("coverage_type", "question" if question_id else "concept" if concept_id else "global")
        coverage.setdefault("doc_type", doc_type)
        coverage.setdefault("question_aligned", bool(question_id or assist_question_id))
        coverage.setdefault("concept_aligned", bool(concept_id or assist_concept_id))

        payload_provenance = _dict_value(_first_value(payload, raw, "provenance"))
        provenance = {
            **payload_provenance,
            "provider_name": self.provider_name,
            "provider_mode": self.provider_mode,
            "collection": self.collection,
            "source": source,
        }
        if self.namespace:
            provenance["namespace"] = self.namespace
        provider_record_id = _string_value(
            _first_value(raw, payload, "id", "record_id", "vector_id")
        )
        if provider_record_id:
            provenance["provider_record_id"] = provider_record_id

        return RAGSearchResult(
            doc_id=doc_id,
            doc_type=doc_type,
            title=title,
            content=content,
            source=source,
            concept_id=concept_id,
            question_id=question_id,
            assist2017_question_id=assist_question_id,
            assist2017_concept_id=assist_concept_id,
            canonical_mapping=canonical_mapping,
            provenance=provenance,
            coverage=coverage,
            score=_score(raw, payload),
        )


class HTTPJSONRAGSearchClient:
    """Small HTTP client for opt-in live smoke without adding provider SDK deps."""

    def __init__(self, config: VikingRAGProviderConfig) -> None:
        self.config = config

    def search(
        self,
        *,
        query: str,
        filters: dict[str, Any] | None = None,
        limit: int = 3,
    ) -> Any:
        url = _join_url(self.config.endpoint, self.config.search_path)
        request_body = {
            "query": query,
            "text": query,
            "collection": self.config.collection,
            "namespace": self.config.namespace,
            "limit": limit,
            "filters": filters or {},
            "metadata_filter": filters or {},
        }
        data = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "X-Api-Key": self.config.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.config.timeout_seconds,
            ) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RAGProviderSearchError(f"{self.config.provider_name} HTTP search failed.") from exc


def create_viking_knowledge_rag_adapter(
    settings: MathTutorSettings,
    *,
    fallback: Any | None = None,
) -> VikingKnowledgeRAGAdapter:
    from .knowledge_rag import RAGProviderConfigurationError

    provider_name = settings.rag_live_provider.lower()
    if provider_name not in {"vikingdb", "openviking"}:
        raise RAGProviderConfigurationError(
            "VikingDB/OpenViking live provider requires "
            "MATHTUTOR_RAG_LIVE_PROVIDER=vikingdb or openviking."
        )
    api_key = (
        settings.openviking_api_key
        if provider_name == "openviking"
        else settings.vikingdb_api_key
    )
    if not api_key:
        raise RAGProviderConfigurationError(
            "VikingDB/OpenViking live provider requires an explicit provider API key."
        )
    if not settings.rag_provider_collection:
        raise RAGProviderConfigurationError(
            "VikingDB/OpenViking live provider requires MATHTUTOR_RAG_PROVIDER_COLLECTION."
        )
    if not settings.rag_provider_endpoint:
        raise RAGProviderConfigurationError(
            "VikingDB/OpenViking live provider requires MATHTUTOR_RAG_PROVIDER_ENDPOINT."
        )

    return VikingKnowledgeRAGAdapter(
        provider_name=provider_name,
        provider_mode=settings.rag_provider_mode,
        collection=settings.rag_provider_collection,
        namespace=settings.rag_provider_namespace,
        endpoint=settings.rag_provider_endpoint,
        api_key=api_key,
        search_path=settings.rag_provider_search_path,
        timeout_seconds=settings.rag_provider_timeout_seconds,
        provider_supports_metadata_filter=settings.rag_provider_supports_metadata_filter,
        fallback=fallback,
    )


def normalize_rag_metadata_filters(filters: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    doc_type = _filter_value(filters, "doc_type")
    doc_types = _filter_value(filters, "doc_types")
    if isinstance(doc_type, (list, tuple, set)) and not doc_types:
        doc_types = doc_type
        doc_type = None
    if doc_type is not None:
        normalized["doc_type"] = _doc_type(doc_type)
    if doc_types is not None:
        normalized["doc_types"] = sorted({_doc_type(item) for item in doc_types})

    for target, aliases in {
        "question_id": ("question_id", "canonical_question_id", "mathtutor_question_id"),
        "concept_id": ("concept_id", "canonical_concept_id", "mathtutor_concept_id"),
        "assist2017_question_id": (
            "assist2017_question_id",
            "assistments2017_question_id",
            "assist_question_id",
        ),
        "assist2017_concept_id": (
            "assist2017_concept_id",
            "assistments2017_concept_id",
            "assist_concept_id",
        ),
    }.items():
        value = _filter_value(filters, *aliases)
        if value is not None:
            normalized[target] = value
    return normalized


def matches_rag_metadata_filter(
    result: RAGSearchResult,
    filters: dict[str, Any],
) -> bool:
    if not filters:
        return True
    doc_type = filters.get("doc_type")
    if doc_type is not None and result.doc_type != doc_type:
        return False
    doc_types = filters.get("doc_types")
    if doc_types is not None and result.doc_type not in set(doc_types):
        return False
    if not _same_optional(result.question_id, filters.get("question_id")):
        return False
    if not _same_optional(result.concept_id, filters.get("concept_id")):
        return False
    if not _same_optional(result.assist2017_question_id, filters.get("assist2017_question_id")):
        return False
    if not _same_optional(result.assist2017_concept_id, filters.get("assist2017_concept_id")):
        return False
    return True


def extract_provider_records(raw_response: Any) -> list[Any]:
    if raw_response is None:
        return []
    if isinstance(raw_response, list):
        return raw_response
    if isinstance(raw_response, tuple):
        return list(raw_response)
    if isinstance(raw_response, dict):
        for key in ("results", "matches", "records", "documents", "items"):
            value = raw_response.get(key)
            if isinstance(value, list):
                return value
        data = raw_response.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return extract_provider_records(data)
    return [raw_response]


def _call_provider_search(
    client: Any,
    *,
    query: str,
    filters: dict[str, Any] | None,
    limit: int,
    collection: str,
    namespace: str,
) -> Any:
    search = getattr(client, "search", None)
    if search is None and callable(client):
        search = client
    if search is None:
        raise TypeError("Provider client must expose search() or be callable.")
    kwargs = {
        "query": query,
        "filters": filters,
        "limit": limit,
        "collection": collection,
        "namespace": namespace,
    }
    try:
        signature = inspect.signature(search)
    except (TypeError, ValueError):
        return search(query=query, filters=filters, limit=limit)
    if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
        return search(**kwargs)
    accepted = {name: value for name, value in kwargs.items() if name in signature.parameters}
    return search(**accepted)


def _provider_fetch_limit(
    *,
    limit: int,
    filters: dict[str, Any],
    provider_supports_metadata_filter: bool,
) -> int:
    bounded_limit = max(int(limit), 1)
    if filters and not provider_supports_metadata_filter:
        return max(bounded_limit * 5, 10)
    return bounded_limit


def _payload_mapping(raw: dict[str, Any]) -> dict[str, Any]:
    for key in ("payload", "metadata", "fields", "entity", "document"):
        value = raw.get(key)
        if isinstance(value, dict):
            return value
    return raw


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        if isinstance(dumped, dict):
            return dumped
    if hasattr(value, "dict"):
        dumped = value.dict()
        if isinstance(dumped, dict):
            return dumped
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    raise RAGProviderSchemaError("Provider result is not mapping-like.")


def _first_value(primary: dict[str, Any], secondary: dict[str, Any], *keys: str) -> Any:
    sources = (primary, secondary)
    for source in sources:
        for key in keys:
            value = source.get(key)
            if value not in (None, ""):
                return value
    return None


def _filter_value(filters: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = filters.get(key)
        if value not in (None, ""):
            return value
    return None


def _doc_type(value: Any) -> str:
    doc_type = str(value or "").strip()
    if doc_type not in DOC_TYPES:
        raise RAGProviderSchemaError(f"Unsupported RAG doc_type: {doc_type}")
    return doc_type


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string_value(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _score(raw: dict[str, Any], payload: dict[str, Any]) -> float:
    score = _first_value(payload, raw, "score", "similarity", "relevance_score")
    if score is not None:
        return round(float(score), 4)
    distance = _first_value(payload, raw, "distance", "vikingdb_distance", "vector_distance")
    if distance is not None:
        return round(max(0.0, 1.0 - float(distance)), 4)
    return 0.0


def _same_optional(actual: Any, expected: Any) -> bool:
    if expected in (None, ""):
        return True
    return str(actual) == str(expected)


def _join_url(endpoint: str, search_path: str) -> str:
    base = endpoint.rstrip("/")
    path = search_path.strip()
    if not path:
        return base
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{base}{path}"
