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
    signees.names AS signee_names,
    signees.ruts AS signee_ruts,
    signees.phones AS signee_phones,
    signees.emails AS signee_emails,
    CONCAT_WS(' | ',
      pd."firstName" || ' ' || pd."lastName",
      signees.names
    ) AS identity_names,
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
  LEFT JOIN solar_system_sale sss ON sss."saleId" = s.id
  LEFT JOIN solar_system_contract ssc ON ssc.id = sss."solarSystemContractId"
  LEFT JOIN LATERAL (
    SELECT
      STRING_AGG(
        DISTINCT NULLIF(BTRIM(CONCAT_WS(' ',
          person."firstName", person."middleName", person."lastName", person."secondLastName"
        )), ''),
        ' | '
      ) AS names,
      STRING_AGG(DISTINCT person.rut, ' | ') AS ruts,
      STRING_AGG(DISTINCT person.phone, ' | ') AS phones,
      STRING_AGG(DISTINCT signer.email, ' | ') AS emails
    FROM signee signer
    LEFT JOIN natural_person person ON person."signeeId" = signer.id
    WHERE signer."contractId" = ssc."contractId"
  ) signees ON TRUE
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

_CUSTOMER_IDENTITY_CORE = """
SELECT
  pd."firstName" || ' ' || pd."lastName" AS customer_name,
  pd.rut AS customer_rut,
  ci.email AS customer_email,
  ci.phone AS customer_phone,
  signees.names AS signee_names,
  signees.ruts AS signee_ruts,
  signees.phones AS signee_phones,
  signees.emails AS signee_emails,
  CONCAT_WS(' | ', pd."firstName" || ' ' || pd."lastName", signees.names) AS identity_names,
  o.id AS order_id,
  o."orderNumber" AS order_number,
  CONCAT_WS(' ', h."addressStreet", h."addressExternalNumber", h."addressInternalNumber", c.name)
    AS full_address
FROM sale s
JOIN booking b ON b.id = s."bookingId"
JOIN "order" o ON o.id = b."orderId"
JOIN personal_details pd ON pd."userId" = b."userId"
JOIN contact_info ci ON ci."userId" = b."userId"
JOIN house h ON h.id = o."houseId"
JOIN commune c ON c.id = h."communeId"
LEFT JOIN solar_system_sale sss ON sss."saleId" = s.id
LEFT JOIN solar_system_contract ssc ON ssc.id = sss."solarSystemContractId"
LEFT JOIN LATERAL (
  SELECT
    STRING_AGG(
      DISTINCT NULLIF(BTRIM(CONCAT_WS(' ',
        person."firstName", person."middleName", person."lastName", person."secondLastName"
      )), ''),
      ' | '
    ) AS names,
    STRING_AGG(DISTINCT person.rut, ' | ') AS ruts,
    STRING_AGG(DISTINCT person.phone, ' | ') AS phones,
    STRING_AGG(DISTINCT signer.email, ' | ') AS emails
  FROM signee signer
  LEFT JOIN natural_person person ON person."signeeId" = signer.id
  WHERE signer."contractId" = ssc."contractId"
) signees ON TRUE
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


def _person_name_tokens(value: str | None) -> set[str]:
    particles = {"de", "del", "la", "las", "los", "y"}
    return {token for token in _plain(value).split() if len(token) >= 3 and token not in particles}


def _individual_names(value: object) -> tuple[str, ...]:
    return tuple(part.strip() for part in str(value or "").split("|") if part.strip())


def _strong_name_match(query: str, candidate: str) -> bool:
    query_tokens = _person_name_tokens(query)
    candidate_tokens = _person_name_tokens(candidate)
    shared = query_tokens & candidate_tokens
    if len(shared) < 2:
        return False
    return (
        max(
            len(shared) / len(query_tokens),
            len(shared) / len(candidate_tokens),
        )
        >= 0.75
    )


def _any_strong_name_match(query: str, candidates: object) -> bool:
    return any(_strong_name_match(query, candidate) for candidate in _individual_names(candidates))


def _name_fragments(query: str, candidates: object) -> set[str]:
    query_tokens = _person_name_tokens(query)
    candidate_tokens = {
        token
        for candidate in _individual_names(candidates)
        for token in _person_name_tokens(candidate)
    }
    return {token for token in query_tokens & candidate_tokens if len(token) >= 4}


def _matches_delimited(value: str, candidates: object, *, digits: bool = False) -> bool:
    if digits:
        target = _digits(value)
        return bool(target) and any(
            _digits(candidate) == target for candidate in _individual_names(candidates)
        )
    target = value.strip().casefold()
    return bool(target) and any(
        candidate.casefold() == target for candidate in _individual_names(candidates)
    )


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
        account_receivable_id=(
            str(row["account_receivable_id"]) if row.get("account_receivable_id") else None
        ),
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
        elif _strong_name_match(requested_address, customer_name):
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.CUSTOMER_NAME,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.MEDIUM,
                    description="La glosa contiene el nombre del cliente.",
                )
            )
        elif _any_strong_name_match(requested_address, row.get("signee_names")):
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.SIGNEE_NAME,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.MEDIUM,
                    description="La glosa contiene el nombre de un firmante del contrato.",
                )
            )
        elif _name_fragments(
            requested_address,
            " | ".join((customer_name, str(row.get("signee_names") or ""))),
        ):
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.NAME_FRAGMENT,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.WEAK,
                    description="La glosa comparte un fragmento de nombre con el cliente.",
                )
            )
    if transferor:
        normalized = _plain(transferor)
        if _strong_name_match(transferor, customer_name):
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
        elif _any_strong_name_match(transferor, row.get("signee_names")):
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.SIGNEE_NAME,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.MEDIUM,
                    description="El transferente coincide con un firmante del contrato.",
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
        elif _name_fragments(
            transferor,
            " | ".join((customer_name, str(row.get("signee_names") or ""))),
        ):
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.NAME_FRAGMENT,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.WEAK,
                    description="El transferente comparte sólo una parte del nombre registrado.",
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
            if rut and any(
                _matches_delimited(rut, row.get(field), digits=True)
                for field in (
                    "customer_rut",
                    "signee_ruts",
                    "legacy_bank_rut",
                    "normalized_bank_rut",
                )
            ):
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
        if request.email and any(
            _matches_delimited(request.email, row.get(field))
            for field in ("customer_email", "signee_emails")
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
        if request.phone and any(
            _matches_delimited(request.phone, row.get(field), digits=True)
            for field in ("customer_phone", "signee_phones")
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


def _identity_candidate(
    row: dict[str, object],
    request: PaymentCandidateQuery | VerifyCandidateQuery,
    *,
    verified: bool,
) -> InvestigationCandidate:
    evidence: list[EvidenceSignal] = []
    customer_name = str(row["customer_name"])
    transferor = getattr(request, "transferor_name", None)
    requested_address = getattr(request, "glosa_or_address", None) or getattr(
        request, "address", None
    )
    if transferor:
        if _strong_name_match(transferor, customer_name):
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
        elif _any_strong_name_match(transferor, row.get("signee_names")):
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.SIGNEE_NAME,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.MEDIUM,
                    description="El transferente coincide con un firmante del contrato.",
                )
            )
        elif _name_fragments(
            transferor,
            " | ".join((customer_name, str(row.get("signee_names") or ""))),
        ):
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.NAME_FRAGMENT,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.WEAK,
                    description="El transferente comparte sólo una parte del nombre registrado.",
                )
            )
    if requested_address:
        if _strong_name_match(requested_address, customer_name):
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.CUSTOMER_NAME,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.MEDIUM,
                    description="La glosa contiene el nombre del cliente.",
                )
            )
        elif _any_strong_name_match(requested_address, row.get("signee_names")):
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.SIGNEE_NAME,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.MEDIUM,
                    description="La glosa contiene el nombre de un firmante del contrato.",
                )
            )
    if isinstance(request, PaymentCandidateQuery):
        if request.transferor_rut and any(
            _matches_delimited(request.transferor_rut, row.get(field), digits=True)
            for field in ("customer_rut", "signee_ruts")
        ):
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
        if request.email and any(
            _matches_delimited(request.email, row.get(field))
            for field in ("customer_email", "signee_emails")
        ):
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.EMAIL,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.MEDIUM,
                    description="El correo coincide con la identidad almacenada.",
                )
            )
        if request.phone and any(
            _matches_delimited(request.phone, row.get(field), digits=True)
            for field in ("customer_phone", "signee_phones")
        ):
            evidence.append(
                _signal(
                    row,
                    verified=verified,
                    kind=EvidenceKind.PHONE,
                    polarity=EvidencePolarity.SUPPORTING,
                    strength=EvidenceStrength.MEDIUM,
                    description="El teléfono coincide con la identidad almacenada.",
                )
            )
    return InvestigationCandidate(
        customer_name=customer_name,
        order_id=UUID(str(row["order_id"])),
        order_number=int(str(row["order_number"])),
        evidence=evidence,
        verified=verified,
    )


def _is_meaningful_candidate(candidate: InvestigationCandidate) -> bool:
    meaningful = {
        EvidenceKind.EXACT_ADDRESS,
        EvidenceKind.PARTIAL_ADDRESS,
        EvidenceKind.CUSTOMER_NAME,
        EvidenceKind.SIGNEE_NAME,
        EvidenceKind.RUT,
        EvidenceKind.EMAIL,
        EvidenceKind.PHONE,
        EvidenceKind.BANK_NAME,
        EvidenceKind.BANK_ACCOUNT,
        EvidenceKind.EXACT_OUTSTANDING,
        EvidenceKind.VAMBE_CONTEXT,
    }
    return any(
        signal.polarity is EvidencePolarity.SUPPORTING and signal.kind in meaningful
        for signal in candidate.evidence
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
        if request.topic == "general_capabilities":
            summary = (self.knowledge_dir / "finops-general-policy.md").read_text(encoding="utf-8")
        elif request.topic == "identification_policy":
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

    async def _search_customer_identities(self, request: PaymentCandidateQuery) -> QueryResult:
        params: list[Any] = []

        def parameter(value: Any) -> str:
            params.append(value)
            return f"${len(params)}"

        matches: list[tuple[str, str]] = []
        for alias, value in (
            ("transferor_identity_match", request.transferor_name),
            ("glosa_identity_match", request.glosa_or_address),
        ):
            if not value:
                continue
            raw_parameter = parameter(value)
            tokens = sorted(_person_name_tokens(value))
            token_match = "FALSE"
            if len(tokens) >= 2:
                token_parameter = parameter(tokens)
                token_match = (
                    "(SELECT COUNT(DISTINCT token.value) FROM UNNEST("
                    f"{token_parameter}::text[]) AS token(value) WHERE "
                    "(' ' || REGEXP_REPLACE(immutable_unaccent(LOWER(identity_names)), "
                    "'[^a-z0-9]+', ' ', 'g') || ' ') LIKE '% ' || "
                    "immutable_unaccent(LOWER(token.value)) || ' %') >= 2"
                )
            matches.append(
                (
                    alias,
                    "(immutable_unaccent(LOWER(identity_names)) LIKE '%' || "
                    f"immutable_unaccent(LOWER({raw_parameter})) || '%' OR {token_match})",
                )
            )
        if request.transferor_rut:
            value = parameter(request.transferor_rut)
            matches.append(
                (
                    "rut_identity_match",
                    "REGEXP_REPLACE(CONCAT_WS(' ', customer_rut, signee_ruts), "
                    "'[^0-9]', '', 'g') LIKE '%' || "
                    f"REGEXP_REPLACE({value}, '[^0-9]', '', 'g') || '%'",
                )
            )
        if request.email:
            value = parameter(request.email.lower())
            matches.append(
                (
                    "email_identity_match",
                    "(' | ' || LOWER(CONCAT_WS(' | ', customer_email, signee_emails)) || "
                    f"' | ') LIKE '% | ' || {value} || ' | %'",
                )
            )
        if request.phone:
            value = parameter(request.phone)
            matches.append(
                (
                    "phone_identity_match",
                    "REGEXP_REPLACE(CONCAT_WS(' ', customer_phone, signee_phones), "
                    "'[^0-9]', '', 'g') LIKE '%' || "
                    f"REGEXP_REPLACE({value}, '[^0-9]', '', 'g') || '%'",
                )
            )
        if not matches:
            return QueryResult((), (), 0, False)
        aliases = [name for name, _ in matches]
        select_matches = ",\n".join(f"{expression} AS {name}" for name, expression in matches)
        ordering = ", ".join(f"{name} DESC" for name in aliases)
        query = f"""
        WITH identities AS ({_CUSTOMER_IDENTITY_CORE}), scored AS (
          SELECT identities.*, {select_matches} FROM identities
        )
        SELECT customer_name, customer_rut, customer_email, customer_phone,
               signee_names, signee_ruts, signee_phones, signee_emails,
               identity_names, order_id, order_number, full_address
        FROM scored
        WHERE {" OR ".join(aliases)}
        ORDER BY {ordering}, order_number DESC
        LIMIT 20
        """
        return await self.database.fetch_bounded(query, *params, max_rows=20)

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
                        "immutable_unaccent(LOWER(identity_names)) LIKE '%' || "
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
            name_tokens = sorted(_person_name_tokens(request.transferor_name))
            token_match = "FALSE"
            if len(name_tokens) >= 2:
                token_parameter = parameter(name_tokens)
                token_match = (
                    "(SELECT COUNT(DISTINCT token.value) FROM UNNEST("
                    f"{token_parameter}::text[]) AS token(value) WHERE "
                    "(' ' || REGEXP_REPLACE(immutable_unaccent(LOWER(identity_names)), "
                    "'[^a-z0-9]+', ' ', 'g') || ' ') LIKE '% ' || "
                    "immutable_unaccent(LOWER(token.value)) || ' %') >= 2"
                )
            matches.append(
                (
                    "customer_name_match",
                    "(immutable_unaccent(LOWER(identity_names)) LIKE '%' || "
                    f"immutable_unaccent(LOWER({p})) || '%' OR {token_match})",
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
                    "REGEXP_REPLACE(CONCAT_WS(' ', customer_rut, signee_ruts, legacy_bank_rut, "
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
            matches.append(
                (
                    "email_match",
                    "(' | ' || LOWER(CONCAT_WS(' | ', customer_email, signee_emails)) || "
                    f"' | ') LIKE '% | ' || {p} || ' | %'",
                )
            )
        if request.phone:
            p = parameter(request.phone)
            matches.append(
                (
                    "phone_match",
                    "REGEXP_REPLACE(CONCAT_WS(' ', customer_phone, signee_phones), "
                    "'[^0-9]', '', 'g') LIKE '%' || "
                    f"REGEXP_REPLACE({p}, '[^0-9]', '', 'g') || '%'",
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
               matched.customer_phone, matched.signee_names, matched.signee_ruts,
               matched.signee_phones, matched.signee_emails, matched.identity_names,
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
        candidates = [candidate for candidate in candidates if _is_meaningful_candidate(candidate)]
        identity_result = QueryResult((), (), 0, False)
        has_identity_input = any(
            (
                request.glosa_or_address,
                request.transferor_name,
                request.transferor_rut,
                request.email,
                request.phone,
            )
        )
        if has_identity_input and not candidates:
            identity_result = await self._search_customer_identities(request)
            identity_candidates = [
                _identity_candidate(row, request, verified=False) for row in identity_result.rows
            ]
            candidates.extend(
                candidate
                for candidate in identity_candidates
                if _is_meaningful_candidate(candidate)
            )
        return ToolObservation(
            source="payment_candidates",
            available=True,
            summary=f"Se encontraron {len(candidates)} candidatos para investigar.",
            candidates=candidates,
            limitations=[
                "Las cuentas bancarias son evidencia de apoyo, no decisiva.",
                "Una identidad puede no tener una cuenta por cobrar actualmente elegible.",
            ],
            audit=ToolAuditMetadata(
                row_count=result.row_count + identity_result.row_count,
                truncated=result.truncated or identity_result.truncated,
            ),
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
        identity_result = QueryResult((), (), 0, False)
        if not candidates and request.account_receivable_id is None:
            identity_result = await self.database.fetch_bounded(
                f"""
                WITH identities AS ({_CUSTOMER_IDENTITY_CORE})
                SELECT * FROM identities WHERE order_id = $1
                """,
                request.order_id,
                max_rows=1,
            )
            candidates = [
                _identity_candidate(row, request, verified=True) for row in identity_result.rows
            ]
        return ToolObservation(
            source="candidate_verification",
            available=True,
            summary=(
                "Cliente y cuenta por cobrar verificados contra la réplica."
                if candidates and candidates[0].account_receivable_id is not None
                else "Cliente verificado; no tiene una cuenta por cobrar actualmente elegible."
                if candidates
                else "La orden no tiene una cuenta por cobrar elegible."
            ),
            candidates=candidates,
            limitations=(
                ["No se verificó una cuenta por cobrar actualmente elegible."]
                if candidates and candidates[0].account_receivable_id is None
                else []
            ),
            audit=ToolAuditMetadata(
                row_count=result.row_count + identity_result.row_count,
                truncated=result.truncated or identity_result.truncated,
            ),
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
