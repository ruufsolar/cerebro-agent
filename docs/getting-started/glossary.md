# Glossary

- **Account receivable / AR / accrecc:** money a customer owes Ruuf. `accrecc` is the
  common code shorthand.
- **Payment:** an `AccountReceivablePayment`, potentially a partial contribution. Matching
  uses outstanding balance, not only original total.
- **Cartola:** bank account statement and its incoming/outgoing movements.
- **Glosa:** transfer comment/description. Customers are asked to put the installation
  address there; this is the strongest identification signal.
- **Vambe:** WhatsApp integration whose stored messages can provide payment context.
- **FinOps CRM:** internal customer page at
  `https://tutu.ruuf.cl/account-receivables/crm-finops/{orderId}`.
- **Hold:** a future operational action when a due payment was not received. What it stops
  and its reversal semantics are not defined yet.
- **Surface:** where a person interacts with the agent; Slack is the only V0 surface.
- **Tool:** bounded code the model may call to read knowledge/data or, later, request an
  approved action.
- **Run:** one durable investigation attempt, including inputs, tool calls, result, budget,
  and errors.
- **Confidence:** categorical conclusion (`high`, `medium`, `low`, `unknown`), not a
  pseudo-scientific probability.
- **Evidence:** information supporting or contradicting a candidate. WhatsApp/email are
  context, never the eventual bank trigger.
- **Read replica:** operational database copy used only for bounded investigation reads.
