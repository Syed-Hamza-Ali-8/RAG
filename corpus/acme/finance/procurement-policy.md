# Procurement Policy

## Purpose and Scope

This policy makes sure Acme buys goods and services at fair prices, from vendors that protect client data, with contracts that meet Acme's obligations to its clients. It applies to all purchases by all offices. It is owned by Daniel Okafor, CFO.

## Purchase Requests

Every purchase above USD 1,000 starts with a purchase request in Ledgerline, stating the need, the budget line and the expected annual cost. Purchases below USD 1,000 may be made on a company card and claimed through the expense process.

## Quotes

Purchases above USD 10,000 require three written quotes, unless the vendor is the only supplier able to meet the requirement, which must be justified in writing and approved by the CFO. Quotes and the justification are attached to the purchase request in Ledgerline.

## Security Review

### When a Review Is Needed

Any vendor that will store or process client data needs a vendor security review by the platform team before the contract is signed. Vendors that only receive system metrics or billing contact data need a lighter review.

### What the Review Covers

The review covers certifications (such as ISO 27001 or SOC 2), data location, encryption, access controls, incident history and the vendor's own subprocessors. The platform team records the outcome and the review date in the vendor register.

### Client Obligations

Some client contracts restrict which subprocessors Acme may use. The Halvorsen Logistics MSA requires 30 days' notice to Halvorsen before adding or replacing any subprocessor that handles Halvorsen's data, and Brightwater Health Trust must consent in writing to any new subprocessor with access to its data. The legal team checks client contracts before any such vendor is signed.

## Contract Requirements

Contracts with vendors that process client data must include:

- a data processing agreement;
- security incident notification within 24 hours, so Acme can meet client notification commitments such as the 48-hour commitment to Halvorsen;
- data location commitments matching Acme's client contracts;
- audit rights or access to independent audit reports;
- deletion of data at the end of the contract.

## Contract Signature

- Contracts below USD 50,000 per year: practice lead.
- Contracts of USD 50,000 per year or more: Chief Financial Officer.
- All contracts are reviewed by legal before signature.

The Cobalt Cloud enterprise agreement, with committed spend of EUR 264,000 a year, was signed by the CFO under this rule.

## Critical Vendors

A vendor is critical if a client service depends on it. Critical vendors need a named business owner, an exit plan and a renewal review at least 120 days before the contract ends. Current critical vendors are Cobalt Cloud (hosting) and Ledgerline (invoicing).

## Renewals

The business owner starts each renewal review at least 120 days before the contract end date for critical vendors, and at least 60 days before for other vendors. Renewals follow the same quote and signature rules as new contracts, except that the three-quote rule may be waived for critical vendors where switching would put client services at risk, with the CFO's approval.

## Vendor Register

Every signed contract is added to the vendor register by the finance team within five business days of signature, with the contract reference, business owner, annual value, end date and criticality.

## Exceptions

Exceptions to this policy require written approval from the CFO, recorded in Ledgerline.

## Paying Vendors

Vendor invoices are entered in Ledgerline and matched to the purchase request and the vendor register entry before payment. Invoices from critical vendors are also checked against usage reports; for example, Cobalt Cloud invoices are checked against Cobalt's monthly per-region usage report. Any Service Credits owed to Acme, such as credits under the Cobalt Cloud SLA, are tracked in Ledgerline until they appear on an invoice.

## Training

Everyone who can raise purchase requests completes a short procurement training module in their first month.

## Example: Adding a New Monitoring Tool for Atlas

The platform team wants a new log analysis tool that will receive Atlas application logs, which may contain client user names. The annual cost is USD 14,000, so three quotes are needed. Because the logs may contain client personal data, the tool needs a vendor security review and a data processing agreement with 24-hour incident notification. The legal team checks the Halvorsen MSA, which requires 30 days' notice to Halvorsen before a new subprocessor handles its data. The practice lead signs, because the contract is below USD 50,000 a year, after legal review.
