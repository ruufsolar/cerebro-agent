# Response contract

The agent produces structured data first and the Slack surface renders Spanish prose. This
prevents prompt wording from becoming an accidental API.

## Fields

- `recommended_customer`: name, `orderId`, CRM URL, and reason; nullable.
- `account_receivable_summary`: a one-line business description, nullable.
- `confidence`: `high`, `medium`, `low`, or `unknown`.
- `investigation_summary`: synthesized supporting and contradictory evidence.
- `unable_to_verify`: explicit missing checks.
- `alternatives`: zero to three ranked plausible candidates.

## Confidence rubric

- **High:** a strong signal is independently consistent (for example, installation address
  in glosa plus matching open AR/customer) and there is no material contradiction.
- **Medium:** multiple weaker signals agree, or one strong signal has a small unresolved
  issue.
- **Low:** a tentative candidate is useful for manual review but important signals are
  missing or contradictory.
- **Unknown:** no defensible candidate. This is a successful outcome, not a model failure.

Do not expose numeric probabilities until they are calibrated against labeled FinOps data.

## Example

> **Cliente recomendado:** Ana Pérez — [abrir en CRM FinOps](.../ORD-123)  
> **Cuenta por cobrar:** saldo final de instalación residencial en Providencia  
> **Confianza:** alta  
> La glosa contiene la dirección de instalación registrada para Ana y el monto coincide con
> el saldo pendiente después de sus abonos. No pude verificar un comprobante histórico en
> Vambe porque los adjuntos no están disponibles en la réplica.

When no candidate is found, say so directly and list the most important checks performed.
Do not pad the answer with weak candidates.
