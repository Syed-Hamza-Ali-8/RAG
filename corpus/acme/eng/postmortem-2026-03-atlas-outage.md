# Postmortem: Atlas Outage, 14 March 2026

## Summary

### What Happened

On Saturday 14 March 2026, Atlas was unavailable to all clients for 3 hours 40 minutes (220 minutes), from 06:10 to 09:50 UTC. The incident was classified Severity 1. The incident commander was Bilal Ahmed, with Mei Lin Zhou (CTO) as the executive on call.

### Why It Happened

A storage incident in Cobalt Cloud's Frankfurt region made the primary Atlas PostgreSQL cluster read-only. The team tried to fail over to the disaster recovery replica in the Dubai region, but the database failover runbook was out of date: it referenced a replication setting that had been renamed in the January 2026 platform upgrade. Working out the correct procedure under pressure took about two hours.

### Status

This postmortem is blameless. All action items are tracked in Jira under the epic ATL-1120. As of 30 June 2026, five of seven action items are complete.

## Impact

### Client Impact

All Atlas dashboards were unavailable for all clients for 220 minutes. Data ingestion stopped during the incident and caught up within 40 minutes after recovery. No client data was lost: the Dubai replica was 47 seconds behind the primary when the primary became read-only, and the missing writes were replayed from the ingestion workers' queues.

The most affected client was Halvorsen Logistics. Their Monday-to-Saturday morning operations review at 07:00 Central European Time relies on the warehouse throughput and dock-to-stock dashboards, and their Bergen and Oslo sites ran the Saturday review from spreadsheets. Ingrid Solberg, Halvorsen's Head of Data, was informed at 06:55 UTC.

Two smaller Atlas clients in insurance were also affected but reported no business impact, as the outage fell outside their business hours.

### Contractual Impact

Atlas availability for March 2026 was 99.51% (44,640 minutes in the month, 220 minutes of downtime). The Halvorsen Logistics MSA commits to 99.5% monthly availability, so the commitment was met by a margin of about four minutes and no Service Credit was owed to Halvorsen. Had the outage lasted 224 minutes or more, a 5% Service Credit on the EUR 38,000 Monthly Fee would have been due.

Cobalt Cloud's own availability in the Frankfurt region for March was also 99.51%, below the 99.9% commitment in enterprise agreement CC-ENT-4471. Under that agreement Acme is entitled to a Service Credit of 10% of March's Frankfurt Regional Fees, provided it is claimed within 30 days of the end of the incident.

### Internal Impact

Eleven engineers and consultants were involved over a Saturday morning. Time off in lieu was granted to all of them.

## Timeline (all times UTC)

### Detection

- 06:10 Grafana alerts fire for failed writes from the ingestion workers to the primary database. PagerDuty pages the on-call engineer, Hamza Iqbal.
- 06:14 On-call engineer acknowledges the page (within the 15-minute Severity 1 target).
- 06:18 Dashboards begin returning errors for all users. External monitoring confirms Atlas is down.
- 06:20 Severity 1 declared. Bilal Ahmed takes incident command.

### Diagnosis

- 06:25 Cobalt Cloud's status portal confirms a storage incident in Frankfurt availability zone fra-2, Cobalt incident reference COB-INC-88213.
- 06:28 Priority 1 ticket opened with Cobalt support quoting CC-ENT-4471. Cobalt responds at 06:36, within its 15-minute target, but cannot give a recovery estimate.
- 06:35 Decision taken to fail over to the Dubai region rather than wait for Cobalt.

### Failed Failover

- 06:40 Failover starts using the database failover runbook.
- 06:52 Step 4 of the runbook fails. The runbook told the engineer to set replication.standby_name before promotion, but that setting was renamed to replication.replica_slot in platform version 4.2, deployed on 19 January 2026. The promotion command was rejected.
- 07:05 Mei Lin Zhou joins the incident call.
- 07:10 Status page updated for the first time, 52 minutes after the outage began. (Our target is 15 minutes.)
- 07:15 to 08:50 Engineers reconstruct the correct promotion sequence from the platform 4.2 release notes and a staging environment. Two attempts in staging fail because the staging replica had a different configuration from production.

### Recovery

- 08:55 Corrected failover procedure identified and validated in staging.
- 09:20 Dubai replica promoted to primary in production.
- 09:35 Atlas database endpoint switched to Dubai in the configuration service. Ingestion workers and dashboard service restarted.
- 09:50 Dashboards load for all clients. Service restored. Status page updated.
- 10:30 Ingestion backlog cleared.

### Aftermath

- 11:40 Cobalt resolves COB-INC-88213. Frankfurt storage returns to normal.
- 15 March, 02:00 to 04:30 Frankfurt rebuilt as a replica of Dubai.
- 22 March, 02:00 Planned fail-back to Frankfurt during the Sunday maintenance window, completed in 18 minutes.

## Root Cause Analysis

### Primary Cause: Hosting Provider Storage Failure

Cobalt's root cause analysis, received on 26 March 2026, attributed the incident to a firmware defect in a storage controller cluster in availability zone fra-2. The defect caused volumes to switch to read-only mode to protect data integrity. Atlas's primary database volumes were all in fra-2. Cobalt applied a firmware fix across the region on 2 April 2026.

### Contributing Cause 1: Outdated Runbook

The runbook had not been updated after the January platform upgrade. The upgrade checklist did not include a step to review operational runbooks, and the change log for platform 4.2 did not flag the setting rename as affecting failover.

### Contributing Cause 2: Stale Failover Drill

The last failover drill took place in November 2025, before the platform upgrade. Our MSA with Halvorsen commits us to test failover at least quarterly; the drill planned for February 2026 had been postponed because of client delivery pressure. Had it gone ahead, the runbook defect would have been caught.

### Contributing Cause 3: Single Availability Zone

All primary database volumes sat in a single Frankfurt availability zone. A multi-zone layout would probably have kept the primary writable.

### Contributing Cause 4: Slow Client Communication

The status page was first updated 52 minutes into the outage because the incident commander was also running the failover. There was no separate communications lead.

## What Went Well

- Detection and paging worked: the on-call engineer acknowledged within four minutes.
- Asynchronous replication kept the Dubai replica within 47 seconds of the primary, and no data was lost.
- Cobalt support responded within its contractual target.
- The engineers recorded their attempts in the incident channel, which made reconstructing the timeline easy.

## What Went Badly

- The runbook failed at the critical step and nobody knew the correct sequence.
- Staging did not match production, which slowed validation.
- Clients learned about the outage from their own users before Acme told them.

## Action Items

| ID | Action | Owner | Due | Status |
|---|---|---|---|---|
| ATL-1121 | Rewrite the database failover runbook for platform 4.2 and test it end to end in staging | Bilal Ahmed | 2 April 2026 | Done |
| ATL-1122 | Claim the Cobalt Cloud Service Credit for the Frankfurt incident under CC-ENT-4471 | Finance team (Daniel Okafor) | 13 April 2026 | Done, claim filed 3 April 2026 |
| ATL-1123 | Run failover drills every quarter and record the results for clients | Mei Lin Zhou | Quarterly from Q2 2026 | Done for Q2 and Q3 |
| ATL-1124 | Add "review affected runbooks" to the platform upgrade checklist | Platform team | 30 April 2026 | Done |
| ATL-1125 | Spread primary database volumes across three Frankfurt availability zones | Platform team | 30 September 2026 | In progress |
| ATL-1126 | Appoint a separate communications lead for every Severity 1 incident and update the status page within 15 minutes | Bilal Ahmed | 30 April 2026 | Done |
| ATL-1127 | Align staging database configuration with production and check it monthly | Platform team | 31 December 2026 | Not started |

## Follow-Up on the Service Credit

The Service Credit claim (ATL-1122) was filed on 3 April 2026, within the 30-day window that ended on 13 April 2026. Cobalt approved it on 28 April 2026. The credit was EUR 1,650, which is 10% of March's Frankfurt Regional Fees of EUR 16,500. It was deducted from the July 2026 Cobalt invoice, as recorded in the Q3 2026 invoice log.

## Lessons for Contracts and Vendors

The incident was reviewed by the Risk and Compliance practice. Two lessons were recorded for the Cobalt renewal negotiation, which must conclude before the agreement expires on 31 December 2026: Acme will ask Cobalt to commit to multi-zone placement for managed PostgreSQL, and to extend the Service Credit claim window from 30 to 60 days so that it matches the claim window Acme offers its own clients.

## Five Whys

1. Why were dashboards unavailable? Because the primary database was read-only and the dashboard service could not write session data.
2. Why was the primary database read-only? Because Cobalt Cloud's storage controllers in availability zone fra-2 switched all volumes to read-only after a firmware fault.
3. Why did failover take more than two hours? Because the runbook's promotion step referenced a setting that no longer existed after the platform 4.2 upgrade.
4. Why was the runbook out of date? Because the upgrade checklist did not require runbook review, and nobody owned runbook accuracy after upgrades.
5. Why was the defect not caught earlier? Because the quarterly failover drill that would have exercised the runbook had been postponed from February 2026.

## Detection and Response Metrics

| Metric | Target | Actual |
|---|---|---|
| Time to page (alert to on-call paged) | 2 minutes | 1 minute |
| Time to acknowledge (Severity 1) | 15 minutes | 4 minutes |
| Time to first status page update | 15 minutes | 52 minutes |
| Time to first client email to Halvorsen | 30 minutes | 45 minutes |
| Time to restore (recovery time objective) | 30 minutes | 220 minutes |
| Data loss (recovery point objective) | 5 minutes | 0 minutes (47 seconds of lag, replayed) |

The recovery time objective of 30 minutes in the Halvorsen MSA was missed by more than three hours. The MSA treats the recovery objectives as targets rather than as commitments that carry Service Credits, but the miss was reported to Halvorsen in the written incident report as required by clause 7.3 of the MSA.

## Client Communications Log

- 06:55 Phone call from Bilal Ahmed to Ingrid Solberg, Head of Data at Halvorsen Logistics.
- 06:55 Email to Halvorsen's operations analytics manager, Jonas Eriksen.
- 07:10 First status page update for all clients.
- 08:00, 09:00 Hourly updates to Halvorsen by email, as required during a Severity 1 incident.
- 09:55 Recovery confirmed to all clients by email and status page.
- 24 March 2026 Written incident report sent to Halvorsen, within the ten Business Days required by the MSA.

## SLA Calculations

### Atlas Availability for Halvorsen

March 2026 had 31 days, which is 44,640 minutes. Downtime was 220 minutes. Availability was therefore (44,640 − 220) ÷ 44,640 = 99.507%, reported as 99.51%. The Halvorsen MSA threshold is 99.5%, so no Service Credit was due. The largest outage that would have stayed above 99.5% in March is 223 minutes.

### Cobalt Cloud Availability for Acme

Cobalt measured Frankfurt region availability at 99.51% for March. The CC-ENT-4471 threshold is 99.9%, so the Frankfurt region earned the 10% Service Credit tier (below 99.9% but at least 99.0%). March's Frankfurt Regional Fees were EUR 16,500, so the credit was EUR 1,650. The Dubai and London regions were unaffected and earned no credit.

## Follow-Up Failover Drills

### Q2 2026 Drill (12 May 2026)

The rewritten runbook was used to fail Atlas over from Frankfurt to Dubai in a planned drill during the Sunday maintenance window. Failover completed in 19 minutes, inside the 30-minute recovery time objective. One issue was found: the configuration service cached the old database endpoint for five minutes. The cache time was reduced to 30 seconds.

### Q3 2026 Drill (9 August 2026)

The drill was run by a newer engineer who had never performed a failover, to test whether the runbook could be followed without help. Failover completed in 24 minutes. The drill summary was shared with Halvorsen Logistics, as the MSA requires on request.

## Glossary

- Primary: the database instance that accepts writes, normally in Frankfurt.
- Replica: a read-only copy in Dubai kept up to date by asynchronous replication.
- Promotion: turning a replica into the new primary.
- Fail back: returning the primary role to the original region after recovery.

## Review and Sign-Off

This postmortem was reviewed at the platform team's incident review on 25 March 2026 and signed off by Mei Lin Zhou, CTO, on 27 March 2026. It was also presented to Acme's leadership team on 1 April 2026, where Daniel Okafor (CFO) confirmed that the Cobalt Cloud Service Credit claim would be filed before the 13 April deadline and Tomás Ferreira (General Counsel) asked for the incident to be added to the evidence pack for the February 2027 ISO 27001 recertification audit, as an example of the incident management process working end to end.

The leadership team also agreed that the outage, and Cobalt's root cause analysis, should inform the Cobalt Cloud renewal negotiation. In particular, the renewal should address single-zone placement of managed database volumes and the 30-day claim window, which left Acme only 13 business days to file once Cobalt's root cause analysis had arrived on 26 March.

## Appendix A — Technical Detail of the Failed Promotion

### Configuration Before and After Platform 4.2

Before platform 4.2, the Atlas database cluster used a setting called replication.standby_name to identify the replica. Promotion required clearing this setting on the replica and then issuing the promotion command. Platform 4.2, deployed on 19 January 2026, replaced the setting with replication.replica_slot as part of a move to replication slots, which prevent the primary from discarding write-ahead log segments that a replica still needs.

### What the Runbook Said

Step 4 of the old runbook told the operator to clear replication.standby_name. On platform 4.2 the setting no longer existed, so the configuration command returned an "unknown parameter" error. The operator then ran the promotion command anyway, which the cluster rejected because the replica was still attached to a replication slot.

### What Worked

The working sequence, reconstructed between 07:15 and 08:55 UTC, was: pause ingestion; fence the old primary in the Frankfurt security group; set replication.replica_slot to none on the Dubai replica; then promote. This is the sequence now documented in steps 5 to 8 of the revised runbook.

### Why Staging Did Not Help at First

The staging cluster had been upgraded to platform 4.2 but still had a leftover replication.standby_name entry from a manual test in January. The first two staging attempts therefore behaved differently from production. Action item ATL-1127 will align staging with production and check it monthly.

## Appendix B — Written Incident Report Sent to Halvorsen Logistics (Summary)

The written incident report sent to Ingrid Solberg on 24 March 2026 contained: a description of the outage and its 220-minute duration; the root cause at Cobalt Cloud and the runbook defect at Acme; confirmation that no Halvorsen data was lost; the calculation showing March availability of 99.51% against the 99.5% commitment, so no Service Credit was due; the missed recovery time objective; and the seven action items with owners and dates. Halvorsen replied on 27 March asking for the Q2 failover drill results, which were sent on 15 May 2026.

## Appendix C — Cost of the Incident

| Item | Estimate |
|---|---|
| Engineering and consulting time during the incident (11 people, about 4 hours each) | 44 hours |
| Time off in lieu granted | 11 days |
| Postmortem, runbook rewrite and drill preparation | About 60 hours |
| Service Credit owed to Halvorsen | None (availability 99.51%) |
| Service Credit received from Cobalt Cloud | EUR 1,650, applied to the July 2026 invoice |
| Contractual exposure had the outage lasted 4 more minutes | EUR 1,900 (5% of the EUR 38,000 Monthly Fee) |

## Appendix D — Related Incidents

| Date | Incident | Link to this incident |
|---|---|---|
| 21 November 2025 | Planned failover drill, completed in 26 minutes on platform 4.1 | Last successful drill before the upgrade |
| 19 January 2026 | Platform 4.2 upgrade | Introduced the renamed setting |
| 2 July 2026 | SSO certificate expiry, 95-minute login outage | Separate cause; also led to a new automated expiry check |
| August 2025 | Dubai region availability 99.86% at Cobalt | Earlier Cobalt Service Credit of EUR 410 |

## Appendix E — Changes Made to Other Documents

- Database failover runbook: rewritten for platform 4.2 (ATL-1121).
- On-call runbook: added the communications lead role and the requirement to send Cobalt incident references to finance on the day.
- Platform architecture document: added the multi-zone work (ATL-1125) and the failover drill results.
- Vendor register: recorded the Cobalt Service Credit.
- ISO 27001 audit plan: added this postmortem to the incident management evidence.
- Cobalt Cloud renewal term sheet: added multi-zone placement and a longer claim window as negotiation points.

## Appendix F — Questions Asked at the Leadership Review

**Could we have avoided the outage entirely?** Not the storage failure, which was Cobalt's. But with an up-to-date runbook and a recent drill, recovery would probably have taken about 30 minutes instead of 220.

**Did we breach the Halvorsen MSA?** No. Availability stayed above 99.5%. We missed the 30-minute recovery time objective, which the MSA states as a target, and we reported that openly.

**What would it take to fail over automatically?** Automatic promotion would need a reliable way to decide that Frankfurt is truly down, to avoid two primaries. The platform team recommends finishing multi-zone placement first, which addresses the most likely failure mode, and revisiting automatic failover in 2027.

**Does this affect the Cobalt renewal?** Yes. The renewal term sheet now asks for multi-zone placement for managed PostgreSQL at no extra charge and a 60-day Service Credit claim window.

## Appendix G — Status of Action Items at 30 September 2026

| ID | Status | Comment |
|---|---|---|
| ATL-1121 | Done | Runbook used successfully in Q2 and Q3 drills |
| ATL-1122 | Done | EUR 1,650 credit applied to July 2026 Cobalt invoice |
| ATL-1123 | Done for Q2 and Q3 | Q4 drill scheduled for 15 November 2026 |
| ATL-1124 | Done | Checklist used for platform 4.3 upgrade in June 2026; two runbooks updated |
| ATL-1125 | In progress | Multi-zone placement for Frankfurt database depends on the Cobalt renewal terms; target date moved to 31 March 2027 |
| ATL-1126 | Done | Communications lead role used in the July SSO incident; status page updated within 12 minutes |
| ATL-1127 | Not started | Planned for Q4 2026 |

## Appendix H — Checklist Added to the Platform Upgrade Process (ATL-1124)

1. List every runbook that references a component changed by the upgrade.
2. Diff configuration settings between the old and new versions and search the runbooks for renamed or removed settings.
3. Update affected runbooks before the production upgrade.
4. Run the database failover runbook in staging on the new version before production is upgraded.
5. Record the runbook review in the upgrade ticket, as evidence for the ISO 27001 audit.

The checklist was first used for platform 4.3 in June 2026, when two runbooks were updated before the upgrade: the database failover runbook (a changed CLI flag) and the ingestion worker restart procedure.

## Appendix I — Who Was Involved

| Person | Role in the incident |
|---|---|
| Hamza Iqbal | On-call engineer; acknowledged the page at 06:14 |
| Bilal Ahmed | Incident commander; also ran client communications until 09:00, which the review identified as a gap |
| Mei Lin Zhou | CTO; executive on call; joined at 07:05 |
| Two platform engineers | Reconstructed the promotion sequence in staging |
| Daniel Okafor | CFO; owned the Cobalt Service Credit claim |
| Ingrid Solberg | Halvorsen's Head of Data; informed at 06:55 |

Future Severity 1 incidents use a separate communications lead (ATL-1126), first used successfully in the July 2026 SSO outage.
