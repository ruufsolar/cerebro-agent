import re
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unicodedata import combining, normalize
from uuid import UUID

from cerebro.agent.data_tools import (
    InvestigationCandidate,
    KnowledgeQuery,
    PaymentCandidateQuery,
    ReadonlySqlQuery,
    SchemaQuery,
    ToolAuditMetadata,
    ToolObservation,
    VambeQuery,
    VerifyCandidateQuery,
)
from cerebro.agent.models import (
    EvidenceKind,
    EvidencePolarity,
    EvidenceSignal,
    EvidenceSource,
    EvidenceStrength,
)
from cerebro.replica.database import QueryResult, ReplicaDatabase
from cerebro.replica.scope import KnowledgeBundle
from cerebro.replica.sql_policy import SqlPolicyError, validate_readonly_sql

_CANDIDATE_CORE = """
WITH candidate_core AS (
  SELECT
    pd."firstName" || ' ' || pd."lastName" AS customer_name,
    pd.rut AS customer_rut,
    ci.email AS customer_email,
    ci.phone AS customer_phone,
    o.id AS order_id,
    o."orderNumber" AS order_number,
    ar.id AS account_receivable_id,
    ar.type AS account_receivable_type,
    ar.amount AS account_receivable_amount,
    ar.currency,
    GREATEST(
      ar.amount - COALESCE(pa.paid_amount, 0) - COALESCE(la.lost_amount, 0), 0
    ) AS outstanding_amount,
    CONCAT_WS(' ', h."addressStreet", h."addressExternalNumber", h."addressInternalNumber", c.name)
      AS full_address,
    ba."fullName" AS legacy_bank_name,
    ba.rut AS legacy_bank_rut,
    ba."accountNumber" AS legacy_bank_account,
    cba."fullName" AS normalized_bank_name,
    cba.rut AS normalized_bank_rut,
    cba."accountNumber" AS normalized_bank_account
  FROM account_receivable ar
  JOIN sale s ON s.id = ar."saleId"
  JOIN booking b ON b.id = s."bookingId"
  JOIN "order" o ON o.id = b."orderId"
  JOIN personal_details pd ON pd."userId" = b."userId"
  JOIN contact_info ci ON ci."userId" = b."userId"
  JOIN house h ON h.id = o."houseId"
  JOIN commune c ON c.id = h."communeId"
  JOIN LATERAL (
    SELECT installation.id
    FROM solar_system_installation installation
    WHERE installation."saleId" = s.id AND installation."canceledAt" IS NULL
    LIMIT 1
  ) ssi ON TRUE
  LEFT JOIN LATERAL (
    SELECT COALESCE(SUM(p.amount), 0) AS paid_amount
    FROM account_receivable_payment p
    WHERE p."accountReceivableId" = ar.id
      AND p.currency = ar.currency
      AND p."deletedAt" IS NULL
  ) pa ON TRUE
  LEFT JOIN LATERAL (
    SELECT COALESCE(SUM(l.amount), 0) AS lost_amount
    FROM account_receivable_loss l
    WHERE l."accountReceivableId" = ar.id
      AND l.currency = ar.currency
      AND l."deletedAt" IS NULL
  ) la ON TRUE
  LEFT JOIN LATERAL (
    SELECT STRING_AGG(DISTINCT account."fullName", ' | ') AS "fullName",
           STRING_AGG(DISTINCT account.rut, ' | ') AS rut,
           STRING_AGG(DISTINCT account."accountNumber", ' | ') AS "accountNumber"
    FROM bank_account account
    WHERE account."solarSystemInstallationId" = ssi.id
  ) ba ON TRUE
  LEFT JOIN LATERAL (
    SELECT STRING_AGG(DISTINCT account."fullName", ' | ') AS "fullName",
           STRING_AGG(DISTINCT account.rut, ' | ') AS rut,
           STRING_AGG(DISTINCT account."accountNumber", ' | ') AS "accountNumber"
    FROM certification_user certification
    JOIN chile_bank_account account ON account.id = certification."chileBankAccountId"
    WHERE certification."bookingId" = b.id
  ) cba ON TRUE
  WHERE ar."canceledAt" IS NULL
    AND ar.debtor = 'client'
    AND ar.recipient = 'ruuf'
    AND GREATEST(
      ar.amount - COALESCE(pa.paid_amount, 0) - COALESCE(la.lost_amount, 0), 0
    ) > 0
)
SELECT * FROM candidate_core
"""

_INSTALLMENT_LATERAL = """
LEFT JOIN LATERAL (
  SELECT STRING_AGG(
           CONCAT(t.name, ' ', ROUND(i.percentage * 100, 1), '%',
             CASE WHEN i."disbursementDate" IS NULL THEN ''
                  ELSE CONCAT(' (', i."disbursementDate"::date, ')') END),
           ', ' ORDER BY i."disbursementDate" NULLS LAST, i."createdAt"
         ) AS installment_summary
  FROM account_receivable_installment i
  JOIN account_receivable_installment_type t ON t.id = i."typeId"
  WHERE i."accountReceivableId" = {source}.account_receivable_id
) ia ON TRUE
"""


def _plain(value: str | None) -> str:
    if not value:
        return ""
    decomposed = normalize("NFKD", value.casefold())
    without_accents = "".join(character for character in decomposed if not combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", without_accents))


def _glosa_name_tokens(value: str | None) -> list[str]:
    if not value:
        return []
    ignored = {
        "abono",
        "cliente",
        "cuota",
        "instalacion",
        "pago",
        "paneles",
        "proyecto",
        "ruuf",
        "solar",
        "transferencia",
    }
    tokens = list(
        dict.fromkeys(
            token for token in _plain(value).split() if len(token) >= 4 and token not in ignored
        )
    )
    return sorted(tokens, key=lambda token: (-len(token), tokens.index(token)))[:6]


def _partial_address_match(glosa: str, address: str) -> bool:
    glosa_tokens = set(glosa.split())
    address_tokens = address.split()
    numeric = {token for token in address_tokens if token.isdigit()}
    words = {token for token in address_tokens if not token.isdigit() and len(token) >= 3}
    matched_words = words & glosa_tokens
    return (
        bool(numeric)
        and numeric <= glosa_tokens
        and len(matched_words) >= 2
        and len(matched_words) / len(words) >= 0.7
    )


def _signal(
    row: dict[str, object],
    *,
    verified: bool,
    kind: EvidenceKind,
    polarity: EvidencePolarity,
    strength: EvidenceStrength,
    description: str,
) -> EvidenceSignal:
    return EvidenceSignal(
        kind=kind,
        source=(
            EvidenceSource.CANDIDATE_VERIFICATION if verified else EvidenceSource.PAYMENT_CANDIDATES
        ),
        polarity=polarity,
        strength=strength,
        description=description,
        order_id=str(row["order_id"]),
        account_receivable_id=str(row["account_receivable_id"]),
    )


def _digits(value: str | None) -> str:
    return "".join(character for character in value or "" if character.isdigit())


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _candidate(
    row: dict[str, object],
    request: PaymentCandidateQuery | VerifyCandidateQuery,
    *,
    verified: bool,
) -> InvestigationCandidate:
    evidence: list[EvidenceSignal] = []
    address = str(row.get("full_address") or "")
    customer_name = str(row["customer_name"])
    outstanding = _decimal(row["outstanding_amount"])
    outstanding_text = format(outstanding, "f")
    currency = str(row["currency"])
    requested_address = getattr(request, "glosa_or_address", None) or getattr(
        request, "address", None
    )
    transferor = getattr(request, "transferor_name", None)
    amount = getattr(request, "amount", None)
    requested_currency = getattr(request, "currency", None) or "CLP"
    if requested_address:
        left, right = _plain(requested_address), _plain(address)
        name_tokens = set(_glosa_name_tokens(requested_address))
        customer_tokens = set(_glosa_name_tokens(customer_name))
        if right and right in left:
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.EXACT_ADDRESS,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.STRONG,
                    description="La glosa coincide con la dirección completa de instalación.",
                )
            )
        elif right and _partial_address_match(left, right):
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.PARTIAL_ADDRESS,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.MEDIUM,
                    description="La glosa coincide parcialmente con la dirección de instalación.",
                )
            )
        elif name_tokens & customer_tokens:
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.CUSTOMER_NAME,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.MEDIUM,
                    description="La glosa contiene parte distintiva del nombre del cliente.",
                )
            )
    if transferor:
        normalized = _plain(transferor)
        if normalized in _plain(customer_name) or _plain(customer_name) in normalized:
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.CUSTOMER_NAME,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.MEDIUM,
                    description="El nombre del transferente coincide con el cliente.",
                )
            )
        elif any(
            normalized in _plain(str(row.get(field) or ""))
            for field in ("legacy_bank_name", "normalized_bank_name")
        ):
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.BANK_NAME,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.WEAK,
                    description=("El nombre coincide con una cuenta bancaria almacenada de apoyo."),
                )
            )
        else:
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.IDENTITY_CONFLICT,
                    polarity=EvidencePolarity.CONTRADICTING,
                    strength=EvidenceStrength.MEDIUM,
                    description="El nombre del transferente no coincide con el cliente.",
                )
            )
    if amount is not None:
        if requested_currency != currency:
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.CURRENCY_MISMATCH,
                    polarity=EvidencePolarity.CONTRADICTING,
                    strength=EvidenceStrength.STRONG,
                    description="La moneda del pago no coincide con la cuenta por cobrar.",
                )
            )
        elif amount == outstanding:
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.EXACT_OUTSTANDING,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.MEDIUM,
                    description=(
                        f"El monto coincide exactamente con el saldo {outstanding_text} {currency}."
                    ),
                )
            )
        elif amount < outstanding:
            remaining = format(outstanding - amount, "f")
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.PARTIAL_PAYMENT,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.WEAK,
                    description=(
                        f"El monto puede ser un abono parcial; quedarían {remaining} {currency}."
                    ),
                )
            )
        else:
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.AMOUNT_EXCEEDS_OUTSTANDING,
                    polarity=EvidencePolarity.CONTRADICTING,
                    strength=EvidenceStrength.STRONG,
                    description=(
                        f"El monto supera el saldo pendiente {outstanding_text} {currency}."
                    ),
                )
            )
    if isinstance(request, PaymentCandidateQuery):
        if request.transferor_rut:
            rut = _digits(request.transferor_rut)
            if rut and rut in {
                _digits(str(row.get("customer_rut") or "")),
                _digits(str(row.get("legacy_bank_rut") or "")),
                _digits(str(row.get("normalized_bank_rut") or "")),
            }:
                evidence.append(
                    _signal(
                        row,
                        verified=verified,
                        kind=EvidenceKind.RUT,
                        polarity=EvidencePolarity.SUPPORTING,
                        strength=EvidenceStrength.MEDIUM,
                        description="El RUT coincide con la identidad almacenada.",
                    )
                )
        if request.origin_account_number:
            account = _digits(request.origin_account_number)
            if account and account in {
                _digits(str(row.get("legacy_bank_account") or "")),
                _digits(str(row.get("normalized_bank_account") or "")),
            }:
                evidence.append(
                    _signal(
                        row,
                        verified=verified,
                        kind=EvidenceKind.BANK_ACCOUNT,
                        polarity=EvidencePolarity.SUPPORTING,
                        strength=EvidenceStrength.WEAK,
                        description=(
                            "La cuenta de origen coincide con una cuenta almacenada de apoyo."
                        ),
                    )
                )
        if (
            request.email
            and request.email.casefold() == str(row.get("customer_email") or "").casefold()
        ):
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.EMAIL,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.MEDIUM,
                    description="El correo coincide con el cliente.",
                )
            )
        if request.phone and _digits(request.phone) == _digits(
            str(row.get("customer_phone") or "")
        ):
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.PHONE,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.MEDIUM,
                    description="El teléfono coincide con el cliente.",
                )
            )
    installment = str(row.get("installment_summary") or "sin cuotas descritas")
    ar_type = str(row["account_receivable_type"])
    summary = f"{ar_type}; saldo pendiente {outstanding_text} {currency}; {installment}"
    return InvestigationCandidate(
        customer_name=customer_name,
        order_id=UUID(str(row["order_id"])),
        order_number=int(str(row["order_number"])),
        account_receivable_id=UUID(str(row["account_receivable_id"])),
        account_receivable_summary=summary,
        outstanding_amount=outstanding,
        currency=currency,
        evidence=evidence,
        verified=verified,
    )


class ReplicaInvestigationData:
    def __init__(
        self,
        database: ReplicaDatabase,
        knowledge: KnowledgeBundle,
        knowledge_dir: str | Path,
    ) -> None:
        self.database = database
        self.knowledge = knowledge
        self.knowledge_dir = Path(knowledge_dir)

    async def start(self) -> None:
        await self.database.start()

    async def close(self) -> None:
        await self.database.close()

    async def read_finops_knowledge(self, request: KnowledgeQuery) -> ToolObservation:
        if request.topic == "identification_policy":
            summary = (self.knowledge_dir / "payment-identification-policy.md").read_text(
                encoding="utf-8"
            )
        elif request.topic == "data_scope":
            summary = f"Scope v{self.knowledge.scope.version}; relaciones permitidas: " + ", ".join(
                sorted(self.knowledge.scope.relation_names)
            )
        else:
            summary = "; ".join(
                item["detail"] for item in self.knowledge.scope.explicitly_unavailable
            )
        return ToolObservation(source="finops_knowledge", available=True, summary=summary)

    async def describe_database_tables(self, request: SchemaQuery) -> ToolObservation:
        names = [name.lower() for name in request.names]
        unknown = sorted(set(names) - self.knowledge.scope.relation_names)
        if unknown:
            return ToolObservation(
                source="database_schema",
                available=False,
                summary="Una o más relaciones no están permitidas.",
                limitations=[f"No permitidas: {', '.join(unknown)}"],
            )
        rows = [
            {
                "name": name,
                **self.knowledge.catalog.relations[name].model_dump(mode="json"),
            }
            for name in names
        ]
        return ToolObservation(
            source="database_schema",
            available=True,
            summary=f"Descripción de {len(rows)} relaciones permitidas.",
            rows=rows,
            audit=ToolAuditMetadata(row_count=len(rows), truncated=False),
        )

    async def search_payment_candidates(self, request: PaymentCandidateQuery) -> ToolObservation:
        params: list[Any] = []

        def parameter(value: Any) -> str:
            params.append(value)
            return f"${len(params)}"

        matches: list[tuple[str, str]] = []
        if request.glosa_or_address:
            p = parameter(request.glosa_or_address)
            matches.append(
                (
                    "address_match",
                    "(immutable_unaccent(LOWER(full_address)) LIKE '%' || "
                    f"immutable_unaccent(LOWER({p})) || '%' OR "
                    f"immutable_unaccent(LOWER({p})) LIKE '%' || "
                    "immutable_unaccent(LOWER(full_address)) || '%')",
                )
            )
            glosa_tokens = _glosa_name_tokens(request.glosa_or_address)
            if glosa_tokens:
                token_parameter = parameter(glosa_tokens)
                matches.append(
                    (
                        "glosa_name_match",
                        "EXISTS (SELECT 1 FROM UNNEST("
                        f"{token_parameter}::text[]) AS token(value) WHERE "
                        "immutable_unaccent(LOWER(customer_name)) LIKE '%' || "
                        "immutable_unaccent(LOWER(token.value)) || '%')",
                    )
                )
                matches.append(
                    (
                        "glosa_address_token_match",
                        "EXISTS (SELECT 1 FROM UNNEST("
                        f"{token_parameter}::text[]) AS token(value) WHERE "
                        "immutable_unaccent(LOWER(full_address)) LIKE '%' || "
                        "immutable_unaccent(LOWER(token.value)) || '%')",
                    )
                )
        if request.transferor_name:
            p = parameter(request.transferor_name)
            matches.append(
                (
                    "customer_name_match",
                    "immutable_unaccent(LOWER(customer_name)) LIKE '%' || "
                    f"immutable_unaccent(LOWER({p})) || '%'",
                )
            )
            matches.append(
                (
                    "bank_name_match",
                    "immutable_unaccent(LOWER(CONCAT_WS(' ', legacy_bank_name, "
                    "normalized_bank_name))) LIKE '%' || "
                    f"immutable_unaccent(LOWER({p})) || '%'",
                )
            )
        if request.transferor_rut:
            p = parameter(request.transferor_rut)
            matches.append(
                (
                    "rut_match",
                    "REGEXP_REPLACE(CONCAT_WS(' ', customer_rut, legacy_bank_rut, "
                    "normalized_bank_rut), '[^0-9]', '', 'g') LIKE '%' || "
                    f"REGEXP_REPLACE({p}, '[^0-9]', '', 'g') || '%'",
                )
            )
        if request.origin_account_number:
            p = parameter(request.origin_account_number)
            matches.append(
                (
                    "bank_account_match",
                    "REGEXP_REPLACE(CONCAT_WS(' ', legacy_bank_account, "
                    "normalized_bank_account), '[^0-9]', '', 'g') LIKE '%' || "
                    f"REGEXP_REPLACE({p}, '[^0-9]', '', 'g') || '%'",
                )
            )
        if request.email:
            p = parameter(request.email.lower())
            matches.append(("email_match", f"LOWER(customer_email) = {p}"))
        if request.phone:
            p = parameter(request.phone)
            matches.append(
                (
                    "phone_match",
                    "REGEXP_REPLACE(customer_phone, '[^0-9]', '', 'g') = "
                    f"REGEXP_REPLACE({p}, '[^0-9]', '', 'g')",
                )
            )
        if request.amount is not None:
            amount = parameter(request.amount)
            currency = parameter(request.currency or "CLP")
            expression = f"outstanding_amount = {amount}::numeric AND currency = {currency}"
            matches.append(("amount_match", expression))
        select_matches = ",\n".join(f"{expression} AS {name}" for name, expression in matches)
        aliases = [name for name, _ in matches]
        ordering = ", ".join(f"{name} DESC" for name in aliases)
        query = f"""
        WITH eligible AS ({_CANDIDATE_CORE}), scored AS (
          SELECT eligible.*, {select_matches} FROM eligible
        ), matched AS (
          SELECT * FROM scored
          WHERE {" OR ".join(aliases)}
          ORDER BY {ordering}, order_number DESC
          LIMIT 20
        )
        SELECT matched.customer_name, matched.customer_rut, matched.customer_email,
               matched.customer_phone,
               order_id, order_number, account_receivable_id, account_receivable_type,
               account_receivable_amount, currency, outstanding_amount, installment_summary,
               full_address, legacy_bank_name, legacy_bank_rut, legacy_bank_account,
               normalized_bank_name, normalized_bank_rut, normalized_bank_account
        FROM matched
        {_INSTALLMENT_LATERAL.format(source="matched")}
        ORDER BY {ordering}, order_number DESC
        """
        result = await self.database.fetch_bounded(query, *params, max_rows=20)
        candidates = [_candidate(row, request, verified=False) for row in result.rows]
        return ToolObservation(
            source="payment_candidates",
            available=True,
            summary=f"Se encontraron {len(candidates)} candidatos elegibles.",
            candidates=candidates,
            limitations=["Las cuentas bancarias son evidencia de apoyo, no decisiva."],
            audit=ToolAuditMetadata(row_count=result.row_count, truncated=result.truncated),
        )

    async def verify_payment_candidate(self, request: VerifyCandidateQuery) -> ToolObservation:
        params: list[Any] = [request.order_id]
        predicate = "order_id = $1"
        if request.account_receivable_id:
            params.append(request.account_receivable_id)
            predicate += " AND account_receivable_id = $2"
        result = await self.database.fetch_bounded(
            f"""
            WITH eligible AS ({_CANDIDATE_CORE})
            SELECT eligible.*, ia.installment_summary
            FROM eligible
            {_INSTALLMENT_LATERAL.format(source="eligible")}
            WHERE {predicate}
            """,
            *params,
            max_rows=10,
        )
        candidates = [_candidate(row, request, verified=True) for row in result.rows]
        return ToolObservation(
            source="candidate_verification",
            available=True,
            summary=(
                "Candidato verificado contra la réplica."
                if candidates
                else "La orden no tiene una cuenta por cobrar elegible."
            ),
            candidates=candidates,
            audit=ToolAuditMetadata(row_count=result.row_count, truncated=result.truncated),
        )

    async def search_vambe_messages(self, request: VambeQuery) -> ToolObservation:
        limits = self.knowledge.scope.query_limits
        today = datetime.now(UTC).date()
        start = request.start_date or today - timedelta(days=limits.vambe_default_days)
        end = request.end_date or today
        if end < start or (end - start).days > limits.vambe_max_days:
            return ToolObservation(
                source="vambe",
                available=False,
                summary="El rango solicitado no es válido.",
                limitations=[f"Vambe permite como máximo {limits.vambe_max_days} días."],
            )
        user_id: str | None = None
        phone = request.phone
        if request.order_id:
            identity = await self.database.fetch_bounded(
                """
                SELECT b."userId" AS user_id, ci.phone
                FROM booking b
                JOIN "order" o ON o.id = b."orderId"
                JOIN contact_info ci ON ci."userId" = b."userId"
                WHERE o.id = $1
                """,
                request.order_id,
                max_rows=1,
            )
            if identity.rows:
                user_id = str(identity.rows[0]["user_id"])
                phone = phone or str(identity.rows[0]["phone"])
        if user_id is None and not phone:
            return ToolObservation(
                source="vambe",
                available=True,
                summary="No se encontró identidad para acotar la búsqueda en Vambe.",
                limitations=["No se ejecutó una búsqueda global de mensajes."],
            )
        params: list[Any] = [
            user_id,
            phone,
            datetime.combine(start, time.min),
            datetime.combine(end + timedelta(days=1), time.min),
            request.query,
        ]
        result = await self.database.fetch_bounded(
            """
            SELECT id, "createdAt", direction, type,
                   CASE WHEN type IN ('text', 'button', 'template')
                        THEN content ELSE NULL END AS content,
                   CASE WHEN type IN ('image', 'video', 'audio', 'document')
                        THEN '[adjunto histórico no disponible]'
                        ELSE NULL END AS attachment_limitation,
                   "phoneNumber", status, "stageId", "senderId"
            FROM vambe_message
            WHERE (($1::uuid IS NOT NULL AND "userId" = $1::uuid)
                   OR ($2::text IS NOT NULL AND "phoneNumber" = $2::text))
              AND "createdAt" >= $3 AND "createdAt" < $4
              AND ($5::text IS NULL OR content ILIKE '%' || $5::text || '%')
            ORDER BY "createdAt" DESC
            """,
            *params,
            max_rows=limits.vambe_max_messages,
        )
        evidence: list[EvidenceSignal] = []
        if result.row_count and request.query and request.order_id:
            evidence.append(
                EvidenceSignal(
                    kind=EvidenceKind.VAMBE_CONTEXT,
                    source=EvidenceSource.VAMBE,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.WEAK,
                    description=(
                        "Vambe contiene mensajes del candidato que coinciden "
                        "con la búsqueda de pago."
                    ),
                    order_id=str(request.order_id),
                )
            )
        return ToolObservation(
            source="vambe",
            available=True,
            summary=f"Se encontraron {result.row_count} mensajes acotados al candidato.",
            rows=list(result.rows),
            evidence=evidence,
            limitations=["Los adjuntos históricos de Vambe no están disponibles."],
            audit=ToolAuditMetadata(row_count=result.row_count, truncated=result.truncated),
        )

    async def run_readonly_sql(self, request: ReadonlySqlQuery) -> ToolObservation:
        try:
            validated = validate_readonly_sql(request.query, self.knowledge.scope)
        except SqlPolicyError as exc:
            return ToolObservation(
                source="readonly_sql",
                available=False,
                summary="La consulta fue rechazada por la política de lectura.",
                limitations=[str(exc)],
            )
        result: QueryResult = await self.database.run_validated(validated)
        return ToolObservation(
            source="readonly_sql",
            available=True,
            summary=f"Consulta de solo lectura: {result.row_count} filas.",
            rows=list(result.rows),
            limitations=["Resultado truncado al límite seguro."] if result.truncated else [],
            audit=ToolAuditMetadata(
                query_fingerprint=validated.fingerprint,
                referenced_relations=list(validated.relations),
                row_count=result.row_count,
                truncated=result.truncated,
            ),
        )
