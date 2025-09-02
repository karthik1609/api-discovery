from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel


class Evidence(BaseModel):
    sources: List[str]
    confidence: float


@dataclass
class ResourceRecord:
    name: str
    kind: str  # e.g., table, endpoint
    verified: bool = False
    evidence: Optional[Evidence] = None
    meta: Dict[str, object] = field(default_factory=dict)


@dataclass
class DiscoveryState:
    known: Dict[str, ResourceRecord] = field(default_factory=dict)
    unknown: List[str] = field(default_factory=list)
    platform: str = ""
    generator_version: str = "0.1.0"


class StateStore:
    def __init__(self, root_dir: str, platform: str, *, namespace: str | None = None, api_name: str | None = None, api_version: str | None = None) -> None:
        self.root = Path(root_dir)
        self.platform = platform
        parts = [self.root / platform]
        if namespace:
            parts.append(Path(namespace))
        if api_name:
            parts.append(Path(api_name))
        if api_version:
            parts.append(Path(api_version))
        self.platform_dir = Path(*parts)
        self.platform_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.platform_dir / "state.json"
        self.cache_dir = self.platform_dir / "dictionaries"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> DiscoveryState:
        if not self.state_path.exists():
            return DiscoveryState(platform=self.platform)
        data = json.loads(self.state_path.read_text())
        known = {
            key: ResourceRecord(**{**val, "evidence": Evidence(**val["evidence"]) if val.get("evidence") else None})
            for key, val in data.get("known", {}).items()
        }
        return DiscoveryState(
            known=known,
            unknown=data.get("unknown", []),
            platform=data.get("platform", self.platform),
            generator_version=data.get("generator_version", "0.1.0"),
        )

    def save(self, state: DiscoveryState) -> None:
        serializable_known: dict[str, dict[str, object]] = {}
        for k, v in state.known.items():
            serializable_known[k] = {
                "name": v.name,
                "kind": v.kind,
                "verified": v.verified,
                "evidence": v.evidence.model_dump() if v.evidence else None,
                "meta": v.meta,
            }

        serializable = {
            "known": serializable_known,
            "unknown": list(state.unknown),
            "platform": state.platform,
            "generator_version": state.generator_version,
        }
        self.state_path.write_text(json.dumps(serializable, indent=2, sort_keys=True))

    def upsert_resource(
        self, state: DiscoveryState, name: str, kind: str, *, verified: bool = False, evidence: Optional[Evidence] = None, meta: Optional[Dict[str, object]] = None
    ) -> None:
        state.known[name] = ResourceRecord(name=name, kind=kind, verified=verified, evidence=evidence, meta=meta or {})
        if name in state.unknown:
            state.unknown = [u for u in state.unknown if u != name]

    def add_unknown(self, state: DiscoveryState, name: str) -> None:
        if name not in state.unknown and name not in state.known:
            state.unknown.append(name)

    def write_dictionary_cache(self, table: str, fields: list[dict[str, object]]) -> Path:
        path = self.cache_dir / f"{table}.json"
        path.write_text(json.dumps({"fields": fields}, indent=2))
        return path

    def read_dictionary_cache(self, table: str) -> list[dict[str, object]]:
        path = self.cache_dir / f"{table}.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text())
        return list(data.get("fields", []))

    def list_cached_tables(self) -> list[str]:
        return [p.stem for p in self.cache_dir.glob("*.json")]

    def set_verified(self, state: DiscoveryState, name: str, *, evidence: Optional[Evidence] = None) -> None:
        rec = state.known.get(name)
        if rec:
            rec.verified = True
            if evidence:
                rec.evidence = evidence

