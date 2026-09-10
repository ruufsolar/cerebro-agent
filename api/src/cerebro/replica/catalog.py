"""Live application metadata. Catalog reads never accept model-supplied SQL."""

from dataclasses import dataclass, field
from typing import Any

from cerebro.agent.data_tools import SourceRecordQuery


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def relation_key(name: str) -> tuple[str, str]:
    parts = name.split(".", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else ("public", name)


@dataclass
class Relation:
    schema: str
    name: str
    kind: str
    description: str
    columns: dict[str, str] = field(default_factory=dict)
    primary_key: tuple[str, ...] = ()
    writable: bool = False

    @property
    def key(self) -> tuple[str, str]:
        return self.schema, self.name

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.name}"

    @property
    def sql(self) -> str:
        return f"{quote_identifier(self.schema)}.{quote_identifier(self.name)}"


@dataclass(frozen=True)
class ForeignKey:
    identifier: str
    source: tuple[str, str]
    target: tuple[str, str]
    columns: tuple[str, ...]
    target_columns: tuple[str, ...]


@dataclass
class LiveCatalog:
    relations: dict[tuple[str, str], Relation] = field(default_factory=dict)
    foreign_keys: dict[str, ForeignKey] = field(default_factory=dict)

    def record_predicate(self, request: SourceRecordQuery) -> tuple[Relation, str, list[str]]:
        relation = self.relations.get(relation_key(request.relation))
        if relation is None or not relation.primary_key:
            raise ValueError("source requires a readable application relation with a primary key")
        values = {item.column: item.value for item in request.keys}
        if len(values) != len(request.keys) or set(values) != set(relation.primary_key):
            raise ValueError("source requires the complete primary key")
        predicate = " AND ".join(
            f"t0.{quote_identifier(column)}::text = ${index}"
            for index, column in enumerate(relation.primary_key, 1)
        )
        return relation, predicate, [values[column] for column in relation.primary_key]

    def source_query(
        self, request: SourceRecordQuery, path: list[str]
    ) -> tuple[str, list[str], Relation]:
        """Follow declared FK edges, then enumerate orders (never filter to a desired order)."""
        relation, predicate, params = self.record_predicate(request)
        current = relation
        joins: list[str] = []
        visited = {relation.key}
        for index, identifier in enumerate(path, 1):
            fk = self.foreign_keys.get(identifier)
            if fk is None:
                raise ValueError("unknown foreign key")
            if current.key == fk.source:
                target, left, right = fk.target, fk.columns, fk.target_columns
            elif current.key == fk.target:
                target, left, right = fk.source, fk.target_columns, fk.columns
            else:
                raise ValueError("foreign key does not continue this path")
            if target in visited or target not in self.relations:
                raise ValueError("cyclic or inaccessible relationship path")
            visited.add(target)
            current = self.relations[target]
            conditions = " AND ".join(
                f"t{index - 1}.{quote_identifier(a)} = t{index}.{quote_identifier(b)}"
                for a, b in zip(left, right, strict=True)
            )
            joins.append(f"JOIN {current.sql} t{index} ON {conditions}")
        if current.key != ("public", "order"):
            raise ValueError("evidence path must end at public.order")
        query = (
            f'SELECT DISTINCT t{len(path)}."id" AS order_id FROM {relation.sql} t0 '
            + " ".join(joins)
            + f" WHERE {predicate} LIMIT 2"
        )
        return query, params, relation


async def load_catalog(connection: Any) -> LiveCatalog:
    rows = await connection.fetch(
        """
        SELECT c.oid, n.nspname AS schema, c.relname AS name, c.relkind::text AS kind,
               LEFT(COALESCE(obj_description(c.oid, 'pg_class'), ''), 1000) AS description,
               has_table_privilege(c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE') AS writable
        FROM pg_catalog.pg_class c
        JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
        WHERE c.relkind IN ('r', 'p', 'v', 'm')
          AND n.nspname NOT LIKE 'pg\\_%' ESCAPE '\\'
          AND n.nspname <> 'information_schema'
          AND has_schema_privilege(n.oid, 'USAGE')
          AND has_table_privilege(c.oid, 'SELECT')
        ORDER BY n.nspname, c.relname
        """
    )
    catalog = LiveCatalog()
    oids: dict[int, Relation] = {}
    for row in rows:
        relation = Relation(
            row["schema"],
            row["name"],
            row["kind"],
            row["description"],
            writable=bool(row["writable"]),
        )
        catalog.relations[relation.key] = relation
        oids[row["oid"]] = relation
    columns = await connection.fetch(
        """
        SELECT attrelid, attname, format_type(atttypid, atttypmod) AS type
        FROM pg_catalog.pg_attribute
        WHERE attrelid = ANY($1::oid[]) AND attnum > 0 AND NOT attisdropped
        ORDER BY attrelid, attnum
        """,
        list(oids),
    )
    for row in columns:
        oids[row["attrelid"]].columns[row["attname"]] = row["type"]
    constraints = await connection.fetch(
        """
        SELECT c.conname, c.contype::text AS contype, c.conrelid, c.confrelid,
          ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY k(num, ord)
                JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.num
                ORDER BY k.ord) AS columns,
          ARRAY(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY k(num, ord)
                JOIN pg_attribute a ON a.attrelid = c.confrelid AND a.attnum = k.num
                ORDER BY k.ord) AS target_columns
        FROM pg_catalog.pg_constraint c
        WHERE c.conrelid = ANY($1::oid[]) AND c.contype IN ('p', 'f')
        """,
        list(oids),
    )
    for row in constraints:
        source = oids[row["conrelid"]]
        if row["contype"] == "p":
            source.primary_key = tuple(row["columns"])
        elif row["confrelid"] in oids:
            identifier = f"{source.qualified}.{row['conname']}"
            catalog.foreign_keys[identifier] = ForeignKey(
                identifier,
                source.key,
                oids[row["confrelid"]].key,
                tuple(row["columns"]),
                tuple(row["target_columns"]),
            )
    return catalog
