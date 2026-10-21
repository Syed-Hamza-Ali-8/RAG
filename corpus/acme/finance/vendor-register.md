# Vendor Register

## About the Register

The vendor register lists every supplier with an active contract. It is maintained by the finance team, owned by Daniel Okafor (CFO), and reviewed quarterly. It is a key piece of evidence for Acme's ISO 27001 supplier relationship controls.

## Active Vendors

| Vendor | Service | Contract reference | Business owner | Annual value | Contract end | Critical |
|---|---|---|---|---|---|---|
| Cobalt Cloud GmbH | Cloud hosting for Atlas and Brightwater workloads | CC-ENT-4471 | Mei Lin Zhou | EUR 264,000 (committed) | 31 Dec 2026 | Yes |
| Ledgerline Software | Invoicing and expense management | LL-2025-118 | Finance team | USD 18,000 | 30 Jun 2027 | Yes |
| Nordcert | ISO 27001 certification audits | NC-ACME-2027 | Tomás Ferreira | EUR 24,000 | 28 Feb 2027 | No |
| GitHub | Source code hosting and CI | Online subscription | Platform team | USD 21,000 | 31 Mar 2027 | No |
| Grafana Labs | Observability for Atlas | Online subscription | Platform team | USD 16,500 | 31 May 2027 | No |
| PagerDuty | On-call paging | Online subscription | Platform team | USD 6,800 | 31 Jan 2027 | No |
| Google Workspace | Email and documents | Online subscription | IT team | USD 34,000 | 31 Aug 2027 | No |

## Vendor Details

### Cobalt Cloud GmbH

Cobalt hosts Atlas in its Frankfurt (primary) and Dubai (disaster recovery) regions, and the Brightwater Health Trust workloads in its London region. Committed spend is EUR 22,000 per month; actual monthly invoices in 2026 have ranged from EUR 21,950 (after a Service Credit) to EUR 23,400. Cobalt processes all Atlas client data and is listed as a subprocessor in the Halvorsen Logistics data processing addendum. Last security review: September 2025 (ISO 27001 and SOC 2 reports checked). The agreement does not renew automatically; renewal must be signed by 30 November 2026 under the ISO audit plan. The exit plan estimates ten weeks to migrate Atlas to an alternative provider.

### Ledgerline Software

Ledgerline is Acme's invoicing and expense system. It generates client invoices, including Atlas subscription invoices calculated from the nightly Atlas billing export, and processes employee expense claims and travel requests. Ledgerline receives billing contacts and usage volumes only, and is listed as a limited subprocessor in the Halvorsen DPA. Classed as critical because client invoicing depends on it. Last security review: March 2025. Exit plan: export of all invoices and ledgers in CSV, with a manual invoicing fallback for up to two months.

### Nordcert

Nordcert is Acme's ISO 27001 certification body. The recertification audit is scheduled for 15 to 19 February 2027.

### Grafana Labs

Grafana Cloud provides metrics, logs and alerting for Atlas. It receives system metrics only, no client data. Listed in the Halvorsen DPA for transparency.

## Vendor Risk Classification

A vendor is critical if a client service depends on it. Critical vendors need a named business owner, an exit plan, a security review at least every two years, and a renewal review at least 120 days before the contract ends, as required by the procurement policy. Both critical vendors are within the review window: the Cobalt Cloud renewal review started on 2 September 2026, 120 days before its 31 December 2026 end date.

## Spend Against Budget

The 2026 budget allows USD 310,000 for cloud hosting (Cobalt Cloud) and USD 145,000 for software subscriptions. Year-to-date hosting spend to the end of September 2026 was about USD 228,000, in line with budget.

## Changes This Quarter

- Added Google Workspace, previously paid by credit card, to bring it under the procurement policy.
- Recorded the Cobalt Cloud Service Credit of EUR 1,650 for the March 2026 outage, applied to the July invoice.
- Started the Cobalt Cloud renewal review.

## Renewal Calendar

| Vendor | Contract end | Review start (120 days for critical, 60 days otherwise) | Notice or signature deadline |
|---|---|---|---|
| Cobalt Cloud GmbH | 31 Dec 2026 | 2 Sep 2026 | Renewal to be signed by 30 Nov 2026 |
| PagerDuty | 31 Jan 2027 | 2 Dec 2026 | Auto-renews |
| Nordcert | 28 Feb 2027 | 30 Dec 2026 | Next certification cycle quote due after the February 2027 audit |
| GitHub | 31 Mar 2027 | 30 Jan 2027 | Auto-renews |
| Ledgerline Software | 30 Jun 2027 | 2 Mar 2027 | 60 days' notice |

## Questions This Register Answers

- Which vendor hosts Atlas, and under which contract? Cobalt Cloud GmbH, CC-ENT-4471.
- Which vendors appear in client data processing addenda? Cobalt Cloud, Ledgerline Software and Grafana Labs (Halvorsen DPA).
- Which contracts end before the February 2027 ISO audit? Cobalt Cloud (31 December 2026) and PagerDuty (31 January 2027, auto-renews).
- Who owns each critical vendor? Mei Lin Zhou for Cobalt Cloud; the finance team for Ledgerline.
