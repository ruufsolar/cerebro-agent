from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


class RelationScope(BaseModel):
    name: str
    reason: str


class QueryLimits(BaseModel):
    statement_timeout_seconds: int = Field(ge=1, le=60)
    max_rows: int = Field(ge=1, le=1_000)
    max_connections: int = Field(ge=1, le=10)
    max_output_bytes: int = Field(ge=4_096, le=262_144)
    max_query_characters: int = Field(ge=100, le=50_000)
    statements: list[str]
    vambe_default_days: int = Field(ge=1, le=90)
    vambe_max_days: int = Field(ge=1, le=365)
    vambe_max_messages: int = Field(ge=1, le=200)
    schema_descriptions_per_call: int = Field(ge=1, le=20)
    safe_functions: list[str]
    forbid: list[str]


class DataScope(BaseModel):
    version: int
    schema_version: int
    candidate_defaults: dict[str, Any]
    relations: list[RelationScope]
    bank_account_policy: dict[str, Any]
    explicitly_unavailable: list[dict[str, str]]
    query_limits: QueryLimits

    @property
    def relation_names(self) -> set[str]:
        return {relation.name for relation in self.relations}


class RelationSchema(BaseModel):
    description: str
    columns: dict[str, str]
    gotchas: list[str] = Field(default_factory=list)


class SchemaCatalog(BaseModel):
    version: int
    source: str
    relations: dict[str, RelationSchema]

    @model_validator(mode="after")
    def nonempty(self) -> "SchemaCatalog":
        if not self.relations:
            raise ValueError("database schema catalog cannot be empty")
        return self


class KnowledgeBundle(BaseModel):
    scope: DataScope
    catalog: SchemaCatalog

    @model_validator(mode="after")
    def versions_and_relations_match(self) -> "KnowledgeBundle":
        if self.scope.schema_version != self.catalog.version:
            raise ValueError("data scope and schema catalog versions differ")
        missing = self.scope.relation_names - set(self.catalog.relations)
        if missing:
            raise ValueError(f"schema catalog is missing allowed relations: {sorted(missing)}")
        return self


def load_knowledge(knowledge_dir: str | Path) -> KnowledgeBundle:
    root = Path(knowledge_dir)
    scope_data = yaml.safe_load((root / "data-scope.yaml").read_text(encoding="utf-8"))
    catalog_data = yaml.safe_load((root / "database-schema.yaml").read_text(encoding="utf-8"))
    return KnowledgeBundle(
        scope=DataScope.model_validate(scope_data),
        catalog=SchemaCatalog.model_validate(catalog_data),
    )


@lru_cache(maxsize=8)
def cached_knowledge(knowledge_dir: str) -> KnowledgeBundle:
    return load_knowledge(knowledge_dir)
