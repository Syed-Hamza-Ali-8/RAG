# ISO 27001 Recertification Audit Plan 2027

## Audit Details

Acme's ISO 27001 recertification audit will be carried out by the certification body Nordcert from 15 to 19 February 2027. The audit covers all three offices (Karachi, Dubai and London) and the Atlas platform. Audit lead on Acme's side: Tomás Ferreira, General Counsel. Technical lead: Mei Lin Zhou, CTO. Acme has held ISO 27001 certification since 2019; the current certificate expires on 28 February 2027.

## Audit Fee

Nordcert's audit fee is EUR 24,000, under contract NC-ACME-2027. The 2026 budget includes USD 26,000 for the audit, which covers the fee and auditor travel.

## Preconditions

Before the audit:

- Every active client contract must have a current data processing addendum (DPA) listing the subprocessors actually in use.
- Every vendor processing client data must have an in-force agreement on the audit dates.
- Any contract that expires before the audit must either be renewed or have a documented exit plan.
- Every critical vendor must have a named business owner and a current security review.

## Contracts Expiring Before the Audit

| Contract | Counterparty | Expiry | Action owner | Required action |
|---|---|---|---|---|
| Enterprise Agreement CC-ENT-4471 | Cobalt Cloud GmbH | 31 December 2026 (no automatic renewal) | Daniel Okafor | Sign renewal by 30 November 2026 |
| Master Services Agreement | Halvorsen Logistics AS | 31 January 2027 (auto-renews unless notice by 2 November 2026) | Sara Qureshi | Confirm renewal; update DPA |
| Statement of Work | Brightwater Health Trust | 15 December 2026 | Mei Lin Zhou | Complete handover; agree hosting contract route |

### Why the Cobalt Renewal Is Critical

Cobalt Cloud hosts Atlas and the Brightwater Health workloads. If the Cobalt agreement lapses on 31 December 2026 with no renewal, Acme would have no in-force hosting agreement during the audit, which would be a major nonconformity. The legal team has therefore set an internal deadline of 30 November 2026 for signature, leaving a month of contingency.

### Halvorsen DPA Update

The Halvorsen DPA was last updated in March 2024. Its subprocessor list (Cobalt Cloud, Ledgerline Software, Grafana Labs) is still accurate, but its description of the disaster recovery region and the breach notification timelines must be re-confirmed after the March 2026 outage. The updated DPA should be signed together with the renewal confirmation.

## Control Areas in Focus

Nordcert flagged four control areas for closer review at the 2026 surveillance audit:

1. Supplier relationships: evidence that critical vendor contracts include security and incident notification terms.
2. Incident management: evidence that incidents are recorded, reviewed and lead to improvements.
3. Business continuity: evidence that recovery procedures are tested.
4. Access control: evidence of quarterly production access reviews.

## Evidence Plan

| Control area | Evidence | Owner | Due |
|---|---|---|---|
| Supplier relationships | Cobalt Cloud renewal, vendor register, security reviews for Cobalt, Ledgerline and Grafana Labs | Daniel Okafor | 31 December 2026 |
| Incident management | March 2026 Atlas outage postmortem, July 2026 SSO postmortem, action item status from Jira | Bilal Ahmed | 15 January 2027 |
| Business continuity | Q2 and Q3 2026 failover drill reports, Q4 drill report | Mei Lin Zhou | 15 January 2027 |
| Access control | Quarterly production access review records for 2026 | Platform team | 15 January 2027 |
| HR security | Security training completion records for all staff | Priya Raman | 15 January 2027 |

Evidence is collected in the compliance workspace by 31 January 2027.

## Timeline

- 2 November 2026: Halvorsen renewal notice deadline passes; renewal confirmed in writing.
- 30 November 2026: Cobalt Cloud renewal signed.
- 15 December 2026: Brightwater SOW ends.
- Week of 18 January 2027: internal audit dry run led by the Risk and Compliance practice.
- 31 January 2027: evidence pack complete.
- 15 to 19 February 2027: Nordcert recertification audit.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Cobalt renewal not signed in time | Major nonconformity on supplier relationships | Escalate to CEO by 15 November; prepare a short-term extension as fallback |
| ATL-1125 (multi-zone database) not complete | Minor nonconformity on continuity | Document the risk acceptance signed by the CTO |
| Evidence scattered across systems | Audit delays | Single compliance workspace with an owner per control |

## Lessons From the 2026 Surveillance Audit

Nordcert's 2026 surveillance audit raised one minor nonconformity: the platform upgrade process did not require operational runbooks to be reviewed. The March 2026 Atlas outage showed the consequence, and the corrective action (ATL-1124) added a runbook review step to the upgrade checklist. Nordcert will check that the step was followed for the platform 4.3 upgrade in June 2026. Nordcert also recorded two opportunities for improvement: tracking vendor Service Credit claims centrally, now done in the vendor register, and testing failover more often, now done quarterly.

## Audit Week Logistics

Nordcert's two auditors will spend 15 and 16 February 2027 in Karachi, 17 February in Dubai for the Atlas operations review, and 18 February remotely with the London office. The closing meeting is on 19 February 2027. Each control owner must be available for a one-hour interview on the day their area is audited, and the platform team must be able to demonstrate a live production access review and show the failover drill records. Interviews are booked by the Risk and Compliance practice by 31 January 2027.
