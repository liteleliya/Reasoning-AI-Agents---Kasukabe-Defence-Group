"""Authored decision cases (roadmap section 06): a public record agents see and a private
grading record they never do, both stored under `data/cases/` and loaded without any network.

Each case is two files with the same id: `public/<id>.json` (question, context, labelled evidence,
and the response shape) and `grading/<id>.json` (acceptable decisions, required conditions, fatal
errors, required evidence and the rubric version). `question_for` renders only the public record.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from bench.mscore import Instance

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "data" / "cases"
# ``challenge`` is a separately frozen, richer case suite.  It is never mixed into the original
# held-out 24-item study, preserving that study's manifest and denominator for comparison.
SPLITS = ("dev", "heldout", "challenge")
KINDS = ("duration", "number", "enum", "bool")
FORMAT = "authored"


class CaseError(ValueError):
    """A case record is missing, inconsistent or malformed."""


# --- public record --------------------------------------------------------------------------


@dataclass(frozen=True)
class Evidence:
    id: str
    text: str


@dataclass(frozen=True)
class Field:
    """One value the response must state: `decisive` ones take part in the agreement key."""

    name: str
    kind: str
    unit: str = ""
    values: tuple[str, ...] = ()
    decisive: bool = True
    description: str = ""


@dataclass(frozen=True)
class PublicCase:
    id: str
    split: str
    version: int
    domain: str
    question: str
    context: str
    evidence: tuple[Evidence, ...]
    decisions: tuple[str, ...]
    fields: tuple[Field, ...]


# --- grading record -------------------------------------------------------------------------


@dataclass(frozen=True)
class Condition:
    """A material condition a full-credit answer states; `patterns` are regexes that prefill it."""

    id: str
    description: str
    patterns: tuple[str, ...]


@dataclass(frozen=True)
class Critical:
    """A fatal error: it fires when the decision and listed field values all match `when`."""

    id: str
    description: str
    when: dict[str, Any]


@dataclass(frozen=True)
class GradingRecord:
    id: str
    rubric_version: int
    acceptable_decisions: tuple[str, ...]
    conditions: tuple[Condition, ...]
    critical: tuple[Critical, ...]
    evidence_required: tuple[str, ...]


# --- loading --------------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthoredInstance(Instance):
    """An `Instance` whose prompt is the rendered public case; `reference` is the acceptable
    decision(s) for the automatic decision check and is never part of the prompt."""

    prompt: str = ""
    case: PublicCase | None = None
    grading: GradingRecord | None = None  # private: used by the runner's judge, never shown

    def prompt_text(self) -> str:
        return self.prompt


@dataclass(frozen=True)
class CaseBook:
    public: dict[str, PublicCase]
    grading: dict[str, GradingRecord]
    version: str

    def split(self, name: str) -> list[PublicCase]:
        return sorted((c for c in self.public.values() if c.split == name), key=lambda c: c.id)

    def instance(self, case_id: str) -> AuthoredInstance:
        case, grading = self.public[case_id], self.grading[case_id]
        return AuthoredInstance(
            id=f"case:{case.id}",
            domain=case.domain,
            format=FORMAT,
            difficulty=case.split,
            stage="",
            question=case.question,
            reference="|".join(grading.acceptable_decisions),
            context=case.context,
            prompt=question_for(case),
            benchmark="authored",
            case=case,
            grading=grading,
        )


def public_view(case: PublicCase) -> dict[str, Any]:
    """The public record as JSON for the viewer; the grading record has no path into this."""
    return asdict(case)


def question_for(case: PublicCase) -> str:
    """What agents are shown: the public record and nothing from the grading record."""
    lines = [case.question, case.context, "", "Evidence:"]
    lines += [f"[{e.id}] {e.text}" for e in case.evidence]
    lines += ["", "Respond with:", f"- decision: one of {' | '.join(case.decisions)}"]
    for f in case.fields:
        shape = " | ".join(f.values) if f.kind == "enum" else f.kind
        lines.append(f"- {f.name} ({shape}): {f.description}")
    lines.append("- cited evidence: the evidence IDs your justification relies on")
    return "\n".join(lines)


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise CaseError(f"cannot read {path}: {e}") from e


def _field(raw: dict, case_id: str) -> Field:
    kind = raw.get("kind")
    if kind not in KINDS:
        raise CaseError(f"{case_id}: field {raw.get('name')!r} has unknown kind {kind!r}")
    values = tuple(raw.get("values", ()))
    if kind == "enum" and not values:
        raise CaseError(f"{case_id}: enum field {raw['name']!r} lists no values")
    return Field(
        raw["name"],
        kind,
        raw.get("unit", ""),
        values,
        raw.get("decisive", True),
        raw.get("description", ""),
    )


def _public(raw: dict) -> PublicCase:
    cid = raw["id"]
    if raw.get("split") not in SPLITS:
        raise CaseError(f"{cid}: split must be one of {SPLITS}, got {raw.get('split')!r}")
    response = raw["response"]
    return PublicCase(
        id=cid,
        split=raw["split"],
        version=raw["version"],
        domain=raw.get("domain", ""),
        question=raw["question"],
        context=raw.get("context", ""),
        evidence=tuple(Evidence(e["id"], e["text"]) for e in raw.get("evidence", ())),
        decisions=tuple(response["decisions"]),
        fields=tuple(_field(f, cid) for f in response.get("fields", ())),
    )


def _grading(raw: dict) -> GradingRecord:
    cid = raw["id"]
    for cond in raw.get("conditions", ()):
        for pattern in cond["patterns"]:
            try:
                re.compile(pattern)
            except re.error as e:
                raise CaseError(f"{cid}: bad pattern {pattern!r} in {cond['id']}: {e}") from e
    return GradingRecord(
        id=cid,
        rubric_version=raw["rubric_version"],
        acceptable_decisions=tuple(raw["acceptable_decisions"]),
        conditions=tuple(
            Condition(c["id"], c["description"], tuple(c["patterns"]))
            for c in raw.get("conditions", ())
        ),
        critical=tuple(
            Critical(c["id"], c["description"], dict(c["when"])) for c in raw.get("critical", ())
        ),
        evidence_required=tuple(raw.get("evidence_required", ())),
    )


def _check(public: PublicCase, grading: GradingRecord) -> None:
    cid = public.id
    for d in grading.acceptable_decisions:
        if d not in public.decisions:
            raise CaseError(f"{cid}: acceptable decision {d!r} is not in the public vocabulary")
    known = {e.id for e in public.evidence}
    for e in grading.evidence_required:
        if e not in known:
            raise CaseError(f"{cid}: grading requires unknown evidence {e!r}")
    names = {"decision"} | {f.name for f in public.fields}
    for crit in grading.critical:
        for key in crit.when:
            if key not in names:
                raise CaseError(f"{cid}: critical rule {crit.id} names unknown field {key!r}")


def load_cases(root: str | Path = DEFAULT_ROOT) -> CaseBook:
    """Both manifests, validated against each other; `version` hashes every file's content."""
    root = Path(root)
    public_files = {p.stem: p for p in sorted((root / "public").glob("*.json"))}
    grading_files = {p.stem: p for p in sorted((root / "grading").glob("*.json"))}
    for stem in sorted(set(public_files) ^ set(grading_files)):
        missing = "no grading record" if stem in public_files else "no public record"
        raise CaseError(f"{stem}: {missing}")
    digest = hashlib.sha256()
    public: dict[str, PublicCase] = {}
    grading: dict[str, GradingRecord] = {}
    for stem in public_files:
        for path in (public_files[stem], grading_files[stem]):
            digest.update(path.read_bytes())
        pub, grd = _public(_read(public_files[stem])), _grading(_read(grading_files[stem]))
        if not pub.id == grd.id == stem:
            raise CaseError(f"{stem}: file name and record ids disagree ({pub.id}, {grd.id})")
        _check(pub, grd)
        public[stem], grading[stem] = pub, grd
    return CaseBook(public, grading, digest.hexdigest()[:12])
