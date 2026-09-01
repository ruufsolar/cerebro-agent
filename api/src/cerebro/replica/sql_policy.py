from dataclasses import dataclass
from hashlib import sha256

from sqlglot import exp, parse
from sqlglot.errors import ParseError

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


def validate_readonly_sql(query: str, scope: DataScope) -> ValidatedSql:
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
    with_clause = statement.args.get("with_") or statement.args.get("with")
    if with_clause is not None and with_clause.args.get("recursive"):
        raise SqlPolicyError("recursive CTEs are not allowed")

    cte_names = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}
    relations: set[str] = set()
    for table in statement.find_all(exp.Table):
        if isinstance(table.this, exp.Func):
            raise SqlPolicyError("table functions are not allowed")
        name = table.name.lower()
        schema = table.db.lower() if table.db else ""
        if name in cte_names and not schema:
            continue
        if schema not in {"", "public"}:
            raise SqlPolicyError("only public or unqualified relations are allowed")
        if name.startswith("pg_") or name == "information_schema":
            raise SqlPolicyError("catalog access is not allowed")
        if name not in scope.relation_names:
            raise SqlPolicyError(f"relation is not allowed: {name}")
        relations.add(name)

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
