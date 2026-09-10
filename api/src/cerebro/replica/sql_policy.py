from dataclasses import dataclass
from hashlib import sha256

from sqlglot import exp, parse
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.scope import Scope, traverse_scope

from cerebro.replica.scope import DataScope


class SqlPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedSql:
    normalized_sql: str
    fingerprint: str
    relations: tuple[str, ...]


_FORBIDDEN_NODES = tuple(
    node
    for node in (
        exp.Alter,
        exp.Command,
        getattr(exp, "Copy", None),
        exp.Create,
        exp.Delete,
        exp.Drop,
        exp.Insert,
        exp.Merge,
        exp.Set,
        exp.Transaction,
        exp.Update,
    )
    if node is not None
)


def validate_readonly_sql(
    query: str,
    scope: DataScope,
    *,
    readable_relations: set[tuple[str, str]] | None = None,
) -> ValidatedSql:
    stripped = query.strip()
    if not stripped:
        raise SqlPolicyError("query is empty")
    if len(stripped) > scope.query_limits.max_query_characters:
        raise SqlPolicyError("query exceeds the configured character limit")
    try:
        statements = [statement for statement in parse(stripped, read="postgres") if statement]
    except ParseError as exc:
        raise SqlPolicyError("query is not valid PostgreSQL") from exc
    if len(statements) != 1:
        raise SqlPolicyError("exactly one statement is allowed")
    statement = statements[0]
    if not isinstance(statement, exp.Query):
        raise SqlPolicyError("only SELECT or WITH queries are allowed")
    if any(statement.find(node_type) is not None for node_type in _FORBIDDEN_NODES):
        raise SqlPolicyError("query contains a forbidden operation")
    for select in statement.find_all(exp.Select):
        if select.args.get("into") is not None or select.args.get("locks"):
            raise SqlPolicyError("SELECT INTO and row-locking clauses are not allowed")
        for projection in select.expressions:
            value = projection.unalias()
            if isinstance(value, exp.Star) or (isinstance(value, exp.Column) and value.is_star):
                raise SqlPolicyError("SELECT * is not allowed; name the required columns")
    if any(clause.args.get("recursive") for clause in statement.find_all(exp.With)):
        raise SqlPolicyError("recursive CTEs are not allowed")

    # A nested CTE alias must not whitelist an unrelated outer physical table.
    cte_references: set[int] = set()
    try:
        for query_scope in traverse_scope(statement):
            for node, source in query_scope.selected_sources.values():
                if isinstance(source, Scope):
                    cte_references.add(id(node))
    except OptimizeError as exc:
        raise SqlPolicyError("query scopes are ambiguous") from exc
    relations: set[str] = set()
    for table in statement.find_all(exp.Table):
        if isinstance(table.this, exp.Func):
            raise SqlPolicyError("table functions are not allowed")
        name = table.name if table.this.args.get("quoted") else table.name.lower()
        db = table.args.get("db")
        schema = table.db if db is not None and db.args.get("quoted") else table.db.lower()
        if id(table) in cte_references and not schema and not table.catalog:
            continue
        if table.catalog:
            raise SqlPolicyError("cross-database relations are not allowed")
        if schema.startswith("pg_") or schema == "information_schema":
            raise SqlPolicyError("catalog access is not allowed")
        allowed = readable_relations
        if allowed is None:
            # Compatibility for standalone policy callers; runtime always supplies live grants.
            allowed = {("public", item) for item in scope.relation_names}
        if (schema or "public", name) not in allowed:
            raise SqlPolicyError(f"relation is not allowed: {name}")
        relations.add(f"{schema}.{name}" if schema else name)
        table.set("db", exp.to_identifier(schema or "public", quoted=True))

    for join in statement.find_all(exp.Join):
        kind = str(join.args.get("kind") or "").upper()
        if kind == "CROSS" or (join.args.get("on") is None and join.args.get("using") is None):
            raise SqlPolicyError("cartesian joins are not allowed")

    safe_functions = {name.lower() for name in scope.query_limits.safe_functions}
    for function in statement.find_all(exp.Func):
        name = (
            function.name.lower()
            if isinstance(function, exp.Anonymous)
            else function.sql_name().lower()
        )
        if name and name not in safe_functions:
            raise SqlPolicyError(f"function is not allowed: {name}")

    normalized = statement.sql(dialect="postgres", pretty=False)
    fingerprint = sha256(normalized.encode("utf-8")).hexdigest()
    return ValidatedSql(normalized, fingerprint, tuple(sorted(relations)))
