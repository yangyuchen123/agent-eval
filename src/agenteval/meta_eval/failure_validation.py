"""Generic, human-review-first failure-handling validation utilities.

The scanner in this module is deliberately rubric-neutral at the retrieval
layer and conservative at the interpretation layer.  It finds observable
runtime signals and nearby/later candidate events.  It does *not* decide that
an agent ignored, partially recovered from, or fully recovered from a failure;
those are Gold judgments that require human review.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import json
import re
from typing import Any, Iterable, Mapping, Sequence


class FailureSignalKind(str, Enum):
    NONZERO_EXIT = "nonzero_exit"
    TIMEOUT = "timeout"
    TOOL_ERROR = "tool_error"
    FAILED_CHECK = "failed_check"
    EXIT_ZERO_ERROR_TEXT = "exit_zero_error_text"
    NONFATAL_WARNING = "nonfatal_warning"
    EXPECTED_FALLBACK_BRANCH = "expected_fallback_branch"
    OBSERVER_CAPTURE_ERROR = "observer_capture_error"


class FailureValidationStratum(str, Enum):
    """Human Gold strata requested by the blind validation protocol."""

    EXPLICIT_FAILURE_IGNORED = "A_explicit_failure_ignored"
    EXPLICIT_FAILURE_PARTIAL_RECOVERY = "B_explicit_failure_partial_recovery"
    EXPLICIT_FAILURE_SUCCESSFUL_RECOVERY = "C_explicit_failure_successful_recovery"
    EXPECTED_FALLBACK_BRANCH = "D_expected_fallback_branch"
    NONFATAL_WARNING = "E_nonfatal_warning"
    EXIT_ZERO_SEMANTIC_FAILURE = "F_exit_zero_semantic_failure"
    OBSERVER_CAPTURE_FAILURE = "G_observer_capture_failure"
    WRONG_OUTCOME_WITHOUT_EXPLICIT_FAILURE = "H_wrong_outcome_without_explicit_failure"


@dataclass(frozen=True)
class FailureSignal:
    evidence_id: str
    kind: FailureSignalKind
    evidence_class: str | None
    event_type: str | None
    tool_name: str | None
    tool_call_id: str | None
    agent_id: str | None
    explicit_agent_visible: bool
    exit_code: int | None = None
    timed_out: bool | None = None
    summary: str = ""
    matched_terms: tuple[str, ...] = ()
    later_success_candidate_refs: tuple[str, ...] = ()
    nearby_evidence_refs: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["kind"] = self.kind.value
        return value


@dataclass(frozen=True)
class FailureAttemptScan:
    attempt_id: str
    env_name: str | None
    task_id: str | None
    status: str | None
    score_total: float | None
    trace_digest: str | None
    record_count: int
    signals: tuple[FailureSignal, ...] = ()
    candidate_strata: tuple[str, ...] = ()
    diagnostic_notes: tuple[str, ...] = ()

    @property
    def signal_counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for signal in self.signals:
            result[signal.kind.value] = result.get(signal.kind.value, 0) + 1
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "env_name": self.env_name,
            "task_id": self.task_id,
            "status": self.status,
            "score_total": self.score_total,
            "trace_digest": self.trace_digest,
            "record_count": self.record_count,
            "signal_counts": self.signal_counts,
            "signals": [item.to_dict() for item in self.signals],
            "candidate_strata": list(self.candidate_strata),
            "diagnostic_notes": list(self.diagnostic_notes),
            "gold_status": "pending_human_review",
        }


_ERROR_RE = re.compile(
    r"(?:^|\b)(?:error|exception|traceback|fatal|cannot|unable to|permission denied|"
    r"not found|no such file|connection refused|assertionerror)(?:\b|:)", re.IGNORECASE,
)
_WARNING_RE = re.compile(r"(?:^|\b)(?:warning|warn|deprecated)(?:\b|:)", re.IGNORECASE)
_FAILED_CHECK_RE = re.compile(
    r"(?:\bfailed\b|\bfailure\b|\btests? failed\b|\bvalidation failed\b|"
    r"\bassertion(?:error)?\b|\bnot passed\b)", re.IGNORECASE,
)
_TIMEOUT_RE = re.compile(r"(?:timed[ -]?out|timeout|deadline exceeded)", re.IGNORECASE)
_OBSERVER_RE = re.compile(
    r"(?:observer|capture|instrumentation|telemetry|collector|serialization|projection)",
    re.IGNORECASE,
)


def scan_failure_signals(records: Sequence[Any], *, context_radius: int = 2,
                         later_success_limit: int = 3) -> list[FailureSignal]:
    """Find generic runtime failure/warning candidates in normalized records.

    ``records`` may contain EvidenceRecord objects or dictionaries. Detection
    is based on structured runtime result/lifecycle fields, never arbitrary
    prose nested inside messages. This prevents code, prompts, or retrospective
    text that merely *mentions* an error from becoming a runtime failure event.
    """
    normalized = [_as_mapping(record) for record in records]
    provisional: list[dict[str, Any]] = []
    for index, record in enumerate(normalized):
        content = _semantic_content(record)
        has_result = "result" in content
        result = _decoded_result(content.get("result")) if has_result else None
        lifecycle = str(record.get("lifecycle_state") or "").lower()
        event_type = str(record.get("event_type") or record.get("kind") or "")
        source = str(record.get("source") or "")
        direct_error = content.get("error")
        direct_ok = content.get("ok")
        operation_record = bool(
            has_result or direct_error not in (None, "", False, [], {})
            or isinstance(direct_ok, bool)
            or lifecycle in {"failed", "error", "rejected", "timeout", "timed_out"}
        )

        # Observer-side failures are identified from observer/instrumentation
        # event identity plus an explicit structured failure field. Arbitrary
        # message text is intentionally excluded.
        observer_identity = bool(_OBSERVER_RE.search(" ".join((event_type, source))))
        observer_data = content.get("data") if isinstance(content.get("data"), Mapping) else {}
        observer_event = str(observer_data.get("event") or observer_data.get("status") or "").lower()
        observer_reason = str(observer_data.get("reason_code") or "").lower()
        observer_failure = bool(
            observer_identity and (
                direct_error not in (None, "", False, [], {})
                or direct_ok is False
                or lifecycle in {"failed", "error", "rejected", "timeout", "timed_out"}
                or observer_event in {"error", "failed", "failure", "rejected", "timeout", "timed_out"}
                or observer_reason in {"parse_failed", "capture_failed", "serialization_failed"}
                or "error" in event_type.lower() or "failed" in event_type.lower()
            )
        )

        kinds: list[tuple[FailureSignalKind, tuple[str, ...], bool]] = []
        exit_code: int | None = None
        timed_out: bool | None = None
        output = ""
        combined = _searchable_text(record, content, result)
        if observer_failure:
            kinds.append((FailureSignalKind.OBSERVER_CAPTURE_ERROR,
                          _matches(_OBSERVER_RE, " ".join((event_type, source))), False))
        elif operation_record:
            exit_code = _find_int(result, keys=("exit_code", "returncode", "return_code"))
            timed_out = _find_bool(result, keys=("timed_out", "timeout"))
            ok = direct_ok if isinstance(direct_ok, bool) else _find_bool(result, keys=("ok", "success"))
            command = _find_text(content.get("arguments"), keys=("command", "cmd")) or ""
            output = _find_text(result, keys=("output", "stderr", "message", "error")) or ""
            result_error = _find_value(result, keys=("error", "exception"))
            error_value = direct_error if direct_error not in (None, "", False, [], {}) else result_error

            if exit_code is not None and exit_code != 0:
                kinds.append((FailureSignalKind.NONZERO_EXIT, (f"exit_code={exit_code}",), True))
            timeout_text = str(error_value or "")
            if timed_out is True or lifecycle in {"timeout", "timed_out"} or _TIMEOUT_RE.search(timeout_text):
                terms = ("timed_out=true",) if timed_out is True else _matches(_TIMEOUT_RE, timeout_text)
                kinds.append((FailureSignalKind.TIMEOUT, terms, True))
            if error_value not in (None, "", False, [], {}) or ok is False or lifecycle in {"failed", "error", "rejected"}:
                kinds.append((FailureSignalKind.TOOL_ERROR, _matches(_ERROR_RE, output), True))
            if _FAILED_CHECK_RE.search(output) and exit_code in (None, 0):
                kinds.append((FailureSignalKind.FAILED_CHECK, _matches(_FAILED_CHECK_RE, output), True))

            has_error_text = bool(_ERROR_RE.search(output))
            shell_fallback = bool("||" in command and exit_code == 0 and has_error_text)
            if shell_fallback:
                kinds.append((FailureSignalKind.EXPECTED_FALLBACK_BRANCH,
                              _matches(_ERROR_RE, output), True))
            elif exit_code == 0 and has_error_text:
                kinds.append((FailureSignalKind.EXIT_ZERO_ERROR_TEXT,
                              _matches(_ERROR_RE, output), True))
            if exit_code in (None, 0) and _WARNING_RE.search(output):
                kinds.append((FailureSignalKind.NONFATAL_WARNING,
                              _matches(_WARNING_RE, output), True))

        for kind, matched_terms, visible in _dedupe_kinds(kinds):
            provisional.append({
                "index": index,
                "kind": kind,
                "record": record,
                "exit_code": exit_code,
                "timed_out": timed_out,
                "summary": _summary(
                    str(observer_data.get("message") or observer_reason)
                    if observer_failure else (output or str(direct_error or "") or combined)
                ),
                "matched_terms": matched_terms,
                "explicit_agent_visible": visible,
            })

    results: list[FailureSignal] = []
    for item in provisional:
        index = item["index"]
        record = item["record"]
        nearby = normalized[max(0, index - context_radius): min(len(normalized), index + context_radius + 1)]
        nearby_refs = tuple(
            str(value.get("evidence_id")) for value in nearby
            if value.get("evidence_id") and value.get("evidence_id") != record.get("evidence_id")
        )
        later_refs = tuple(_later_success_candidates(
            normalized, index, record, limit=later_success_limit,
        ))
        results.append(FailureSignal(
            evidence_id=str(record.get("evidence_id") or f"record:{index}"),
            kind=item["kind"],
            evidence_class=_optional_str(record.get("evidence_class")),
            event_type=_optional_str(record.get("event_type") or record.get("kind")),
            tool_name=_optional_str(record.get("tool_name")),
            tool_call_id=_optional_str(record.get("tool_call_id")),
            agent_id=_optional_str(record.get("agent_id") or record.get("actor_agent_id")),
            explicit_agent_visible=item["explicit_agent_visible"],
            exit_code=item["exit_code"],
            timed_out=item["timed_out"],
            summary=item["summary"],
            matched_terms=tuple(item["matched_terms"]),
            later_success_candidate_refs=later_refs,
            nearby_evidence_refs=nearby_refs,
        ))
    return results


def candidate_strata(signals: Iterable[FailureSignal], *, score_total: float | None = None) -> tuple[str, ...]:
    """Return review strata candidates, never final labels or Gold."""
    values = list(signals)
    result: list[str] = []
    explicit = [s for s in values if s.kind in {
        FailureSignalKind.NONZERO_EXIT, FailureSignalKind.TIMEOUT,
        FailureSignalKind.TOOL_ERROR, FailureSignalKind.FAILED_CHECK,
    }]
    if explicit:
        if any(s.later_success_candidate_refs for s in explicit):
            result.extend([
                "review_A_B_C_explicit_failure_with_later_success_candidate",
                "review_B_or_C_recovery_outcome_requires_human",
            ])
        else:
            result.append("review_A_B_C_explicit_failure_without_obvious_later_success")
    if any(s.kind == FailureSignalKind.EXPECTED_FALLBACK_BRANCH for s in values):
        result.append("review_D_expected_fallback_branch_candidate")
    if any(s.kind == FailureSignalKind.NONFATAL_WARNING for s in values):
        result.append("review_E_nonfatal_warning_candidate")
    if any(s.kind == FailureSignalKind.EXIT_ZERO_ERROR_TEXT for s in values):
        result.append("review_F_exit_zero_error_text_candidate")
    if any(s.kind == FailureSignalKind.OBSERVER_CAPTURE_ERROR for s in values):
        result.append("review_G_observer_capture_failure_candidate")
    if not explicit and score_total is not None and score_total <= 20:
        result.append("review_H_low_score_without_explicit_failure_candidate")
    return tuple(dict.fromkeys(result))


def select_balanced_scans(scans: Sequence[FailureAttemptScan], count: int,
                          *, excluded_attempt_ids: Iterable[str] = (),
                          excluded_env_names: Iterable[str] = ()) -> list[FailureAttemptScan]:
    """Deterministically select cross-environment candidates for human review.

    The selector balances *candidate* strata and environments.  It does not use
    Octagon score as Gold; score is used only to surface the H diagnostic pool.
    """
    excluded = set(excluded_attempt_ids)
    excluded_envs = set(excluded_env_names)
    eligible = [
        scan for scan in scans
        if scan.attempt_id not in excluded
        and (scan.env_name or "unknown") not in excluded_envs
        and scan.candidate_strata
    ]
    by_stratum: dict[str, list[FailureAttemptScan]] = {}
    for scan in eligible:
        for stratum in scan.candidate_strata:
            by_stratum.setdefault(stratum, []).append(scan)
    for values in by_stratum.values():
        values.sort(key=lambda item: (item.env_name or "", item.task_id or "", item.attempt_id))

    selected: list[FailureAttemptScan] = []
    selected_ids: set[str] = set()
    environment_counts: dict[str, int] = {}
    strata = sorted(by_stratum)
    while len(selected) < count:
        made_progress = False
        for stratum in strata:
            choices = [x for x in by_stratum[stratum] if x.attempt_id not in selected_ids]
            if not choices:
                continue
            choices.sort(key=lambda item: (
                environment_counts.get(item.env_name or "unknown", 0),
                len(item.candidate_strata), len(item.signals),
                item.env_name or "", item.attempt_id,
            ))
            choice = choices[0]
            selected.append(choice)
            selected_ids.add(choice.attempt_id)
            env = choice.env_name or "unknown"
            environment_counts[env] = environment_counts.get(env, 0) + 1
            made_progress = True
            if len(selected) >= count:
                break
        if not made_progress:
            break
    return selected


def _as_mapping(record: Any) -> dict[str, Any]:
    if isinstance(record, Mapping):
        return dict(record)
    if hasattr(record, "model_dump"):
        return dict(record.model_dump())
    if hasattr(record, "to_dict"):
        return dict(record.to_dict())
    raise TypeError(f"unsupported evidence record: {type(record)!r}")


def _semantic_content(record: Mapping[str, Any]) -> dict[str, Any]:
    value = record.get("content")
    return dict(value) if isinstance(value, Mapping) else {"content": value}


def _decoded_result(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped[0] not in "[{":
        return value
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return value


def _walk(value: Any) -> Iterable[tuple[str | None, Any]]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key), child
            yield from _walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield None, child
            yield from _walk(child)


def _find_value(*values: Any, keys: tuple[str, ...]) -> Any:
    wanted = {key.lower() for key in keys}
    for value in values:
        for key, child in _walk(value):
            if key and key.lower() in wanted:
                return child
    return None


def _find_int(*values: Any, keys: tuple[str, ...]) -> int | None:
    value = _find_value(*values, keys=keys)
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _find_bool(*values: Any, keys: tuple[str, ...]) -> bool | None:
    value = _find_value(*values, keys=keys)
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return None


def _find_text(*values: Any, keys: tuple[str, ...]) -> str | None:
    value = _find_value(*values, keys=keys)
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def _searchable_text(*values: Any) -> str:
    return "\n".join(json.dumps(value, ensure_ascii=False, default=str) for value in values if value is not None)


def _matches(pattern: re.Pattern[str], text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(match.group(0) for match in pattern.finditer(text)))[:8]


def _summary(text: str, limit: int = 500) -> str:
    compact = " ".join(text.split())
    return compact[:limit] + ("…" if len(compact) > limit else "")


def _dedupe_kinds(values: Iterable[tuple[FailureSignalKind, tuple[str, ...], bool]]) -> list[tuple[FailureSignalKind, tuple[str, ...], bool]]:
    result: list[tuple[FailureSignalKind, tuple[str, ...], bool]] = []
    seen: set[FailureSignalKind] = set()
    for value in values:
        if value[0] not in seen:
            result.append(value)
            seen.add(value[0])
    return result


def _record_succeeded(record: Mapping[str, Any]) -> bool:
    content = _semantic_content(record)
    result = _decoded_result(content.get("result"))
    exit_code = _find_int(result, content, keys=("exit_code", "returncode", "return_code"))
    timed_out = _find_bool(result, content, keys=("timed_out", "timeout"))
    ok = _find_bool(result, content, record, keys=("ok", "success"))
    lifecycle = str(record.get("lifecycle_state") or "").lower()
    if exit_code is not None:
        return exit_code == 0 and timed_out is not True
    if ok is not None:
        return ok
    return lifecycle in {"completed", "success", "succeeded", "ok"}


def _later_success_candidates(records: Sequence[Mapping[str, Any]], index: int,
                              source: Mapping[str, Any], *, limit: int) -> list[str]:
    result: list[str] = []
    source_tool = source.get("tool_name")
    source_agent = source.get("agent_id") or source.get("actor_agent_id")
    for candidate in records[index + 1:]:
        if source_tool and candidate.get("tool_name") != source_tool:
            continue
        candidate_agent = candidate.get("agent_id") or candidate.get("actor_agent_id")
        if source_agent and candidate_agent and candidate_agent != source_agent:
            continue
        if _record_succeeded(candidate) and candidate.get("evidence_id"):
            result.append(str(candidate["evidence_id"]))
            if len(result) >= limit:
                break
    return result


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None
