# Postmortem: Ledger Vault Outage, 30 March 2026

## Summary

### What Happened

On Monday 30 March 2026, during the last week of busy season, Ledger Vault, Globex's client document portal, was unavailable for 6 hours 10 minutes (370 minutes), from 09:05 to 15:15 PKT. The incident was classified Severity 1. The incident commander was Kwame Mensah, Head of IT.

### Why It Happened

The Ledger Vault metadata database ran out of storage after a surge of client uploads in the final days of busy season. Storage alerts were set at 95% of capacity and fired too late to act before the disk filled. Once the disk was full, the database stopped accepting writes and the application could not serve any page that needed a session record. A storage resize request to Tessera Cloud, the hosting provider, took 2 hours 40 minutes.

### Status

This postmortem is blameless. All five action items are complete.

## Impact

### Client and Engagement Impact

Audit teams could not download client evidence or upload working-paper attachments for the whole outage. Clients could not upload documents. Several December year-end audits were in their final day of fieldwork, including the FY2025 audit of Marlowe Retail Group plc, a UK retailer. Two audit report sign-offs, including Marlowe's, were delayed by one day; Marlowe's FY2025 audit report was signed on 1 April 2026 instead of 31 March.

No client files were lost. Uploads attempted during the outage failed with an error and had to be repeated.

### Internal Impact

About 120 audit staff in Lahore, Abu Dhabi and Manchester were unable to work on evidence for most of the day. Engagement managers moved teams to review work in Fernbook that did not need new evidence.

### Contractual Impact

Ledger Vault's availability for March 2026 was 99.17% (44,640 minutes in the month, 370 minutes of downtime). Tessera Cloud's agreement TC-7720 commits to 99.95% monthly availability, with a Service Credit of 15% of the USD 15,000 Monthly Fee when availability falls below 99.5%. Claims must be filed within 15 days of the incident.

## Timeline (all times PKT)

### Build-Up

- 23 to 29 March: client uploads run at three times the normal daily volume as busy season closes. Metadata database storage rises from 71% to 94%.
- 29 March, 22:40: database storage reaches 95%. An alert is emailed to the IT team mailbox, which is not monitored overnight. No page is sent.

### Outage

- 30 March, 09:05: database storage reaches 100%. The database stops accepting writes. Ledger Vault returns errors for all users.
- 09:12: service desk receives the first calls from audit teams.
- 09:20: Severity 1 declared. Kwame Mensah takes incident command.
- 09:35: cause identified as a full database disk.
- 09:42: urgent storage resize requested from Tessera, ticket TES-55190, raised as Priority 2 because the support portal classified resize requests as changes.
- 10:30: no progress on the ticket. Globex escalates by phone and the ticket is raised to Priority 1.
- 10:45: IT team deletes 40 GB of expired session logs to free space, but the database will not restart writes until it has 5% free.
- 12:22: Tessera completes the resize from 500 GB to 750 GB, 2 hours 40 minutes after the request.
- 12:30 to 14:50: database recovery runs. The database replays its write-ahead log and runs integrity checks, which take longer than expected because of the volume of recent writes.
- 15:15: Ledger Vault available again for all users.
- 15:40: Engagement partners informed that service has been restored.

## Root Cause Analysis

### Primary Cause

The metadata database was provisioned with 500 GB of storage in April 2024 and had not been resized. Upload volumes grew 60% year on year, mainly because more clients used Ledger Vault instead of email during busy season.

### Contributing Cause 1: Alerting

The only storage alert fired at 95% and went to an unmonitored mailbox. There was no paging alert and no trend-based forecast.

### Contributing Cause 2: Slow Resize

Tessera's support portal classified the urgent resize as a Priority 2 change request. Escalation to Priority 1 required a phone call. The agreement allows Priority 1 classification for resize requests when the service is down, but the IT team did not know this.

### Contributing Cause 3: No Capacity Review Before Busy Season

Globex had no routine capacity review before busy season, when demand on Ledger Vault peaks.

## What Went Well

- Detection of the cause took 30 minutes once the incident was declared.
- Engagement managers quickly moved teams to other work.
- No data was lost.

## What Went Badly

- An alert fired ten hours before the outage, but nobody saw it.
- The resize took 2 hours 40 minutes.
- Clients were not told about the outage until the afternoon.

## Action Items

| # | Action | Owner | Status |
|---|---|---|---|
| 1 | Enable automatic storage scaling on the database (scale at 80% in 25% steps) | IT team | Done, 2 April 2026 |
| 2 | Lower storage alerts to 75% and route them to the IT on-call phone | IT team | Done, 2 April 2026 |
| 3 | Claim the Service Credit from Tessera Cloud under TC-7720 | Finance (Laura Bennett) | Done, claim filed 8 April 2026 |
| 4 | Run a capacity review of Ledger Vault before each busy season, every December | Kwame Mensah | Done, first review scheduled December 2026 |
| 5 | Update the restore runbook and IT on-call guide: raise urgent resize tickets as Priority 1 when the service is down | IT team | Done |

## Service Credit Follow-Up

The claim was filed on 8 April 2026, within the 15-day window that ended on 14 April 2026, quoting TC-7720 and TES-55190. Tessera initially argued that the full disk was a Globex configuration issue, which would be excluded from availability. After discussion, Tessera accepted that its slow resize had extended the outage and approved the full credit of USD 2,250 (15% of the USD 15,000 Monthly Fee, because availability of 99.17% was below 99.5%). The credit was applied to the invoice for June 2026 hosting, dated 3 July 2026, which came to USD 12,750.

## SLA Calculation

March 2026 had 44,640 minutes. With 370 minutes of downtime, availability was (44,640 − 370) ÷ 44,640 = 99.171%. The Tessera thresholds are 99.95% (5% credit below it) and 99.5% (15% credit below it). The outage would have needed to be shorter than 224 minutes to fall into the 5% tier, and shorter than 23 minutes to earn no credit.

## Client Communications

- 13:00: email to all engagement partners with a status summary.
- 13:30: engagement managers called clients with fieldwork deadlines that week.
- 31 March: written apology sent to affected clients by Imran Siddiqui, Managing Partner.
- For FY2026, the Marlowe engagement letter plans final fieldwork to finish by 26 March 2027, leaving more contingency before reporting deadlines.

## Lessons for the Tessera Renewal

The Tessera agreement renews automatically on 31 March 2027 unless Globex gives notice by 30 January 2027. The IT and finance teams will consider this outage, the slow resize, and the dispute about the exclusion in the renewal decision. Henrik Dahl, Legal Counsel, also recorded the incident in the evidence pack for the March 2027 ISO 27001 surveillance audit.

## Five Whys

1. Why was Ledger Vault down? Because its metadata database stopped accepting writes.
2. Why did the database stop accepting writes? Because its disk was full.
3. Why was the disk full? Because upload volumes had grown 60% and the database had never been resized since April 2024.
4. Why did nobody act before it filled? Because the only alert fired at 95% into an unmonitored mailbox ten hours earlier.
5. Why was there no earlier warning? Because Globex had no capacity review before busy season, when demand peaks.

## Detection and Response Metrics

| Metric | Target | Actual |
|---|---|---|
| Time from first alert to human awareness | 15 minutes | About 10.5 hours |
| Time from outage start to Severity 1 declaration | 15 minutes | 15 minutes |
| Time to identify cause | 30 minutes | 15 minutes after declaration |
| Time from resize request to completion | 1 hour (Tessera's urgent target) | 2 hours 40 minutes |
| Time to restore (recovery time objective) | 4 hours | 6 hours 10 minutes |
| Data loss | None | None |

The recovery time objective for Ledger Vault is four hours, so the outage missed it by more than two hours. The recovery point objective of 24 hours was met, as no data was lost.

## Review and Sign-Off

This postmortem was reviewed at the IT team's incident review on 6 April 2026 and approved by Kwame Mensah, Head of IT. It was presented to the partners' meeting on 9 April 2026, where Laura Bennett confirmed the Service Credit claim had been filed the previous day and Imran Siddiqui asked for a capacity review to be added to the annual busy-season preparation plan.

## Appendix A — Capacity Data

| Date | Database storage used | Daily uploads (files) |
|---|---|---|
| 1 March 2026 | 64% | 2,100 |
| 15 March 2026 | 69% | 3,400 |
| 23 March 2026 | 71% | 6,300 |
| 27 March 2026 | 86% | 7,900 |
| 29 March 2026 | 94% to 95% | 6,800 |
| 30 March 2026 | 100% at 09:05 | Uploads failed |

Each uploaded file creates metadata records, version history and audit log entries in the database. During busy season, version history grew faster than in the rest of the year because teams replaced draft documents many times.

## Appendix B — Changes to Monitoring

After the outage the IT team added the following alerts, all routed to the IT on-call phone through the paging tool as well as email:

- database storage above 75% (warning) and 85% (urgent);
- storage forecast to reach 90% within 7 days, based on the 14-day trend;
- automatic storage scaling events, so the team knows when scaling has occurred and can check the cost;
- failed uploads above 1% of attempts over 10 minutes.

## Appendix C — Glossary

- Metadata database: the PostgreSQL database that stores file records, versions, permissions and sessions for Ledger Vault. Client files themselves are in object storage.
- Write-ahead log: the database's record of changes, replayed during recovery.
- Busy season: 15 January to 31 March, when most December year-end audits are completed.
- TC-7720: Globex's agreement reference with Tessera Cloud.
- TES-55190: Tessera's ticket reference for the urgent resize request.

## Appendix D — Text of the Client Apology (31 March 2026)

"Dear client, on Monday 30 March, Ledger Vault, our secure document portal, was unavailable from 09:05 to 15:15 Pakistan time. During that period you could not upload or view documents, and our audit teams could not access evidence. No documents were lost, and documents you tried to upload during the outage should now be uploaded again. The cause was a storage capacity issue in our hosting environment, which has now been fixed, and we have added automatic capacity scaling and earlier warnings so that it cannot happen in the same way again. Where this affected your audit timetable, your engagement partner will contact you directly. We apologise for the disruption at the busiest time of the year. Imran Siddiqui, Managing Partner."

## Appendix E — Busy Season Capacity Review Plan

The first capacity review under action item 4 is scheduled for December 2026, before the 2027 busy season. It will:

1. Compare current database and object storage use with the forecast peak, using the 2026 upload data in Appendix A as a baseline and adding expected growth of 40%.
2. Confirm automatic storage scaling is enabled and that the maximum scaling limit is high enough for the forecast peak.
3. Check that Tessera's support portal will classify urgent resize requests correctly, and that the IT on-call engineer knows to raise them as Priority 1 when the service is down.
4. Run a restore test from the Frankfurt backups to confirm the four-hour recovery time objective can be met at busy-season data volumes.
5. Agree with Tessera that no scheduled maintenance will take place in the Bahrain region between 15 January and 31 March 2027.

The review results will be presented to the partners' meeting in January 2027 and filed as evidence for the ISO 27001 surveillance audit in March 2027.

## Appendix F — Related Documents

- Cloud Services Agreement with Tessera Cloud Ltd, TC-7720 (SLA, claim window and support priorities).
- Ledger Vault Platform Architecture (components, regions and alerting).
- Runbook: Ledger Vault Backup and Restore.
- Audit engagement letter with Marlowe Retail Group plc (fieldwork timetable and lessons from FY2025).
- Invoice Log Q3 2026 (application of the Service Credit).
- Globex Staff Handbook, section 8 (IT service desk and reporting incidents).

## Distribution

This postmortem is shared with all partners, the IT team, the finance team and the Legal Counsel. A summary without internal details may be shared with clients on request.

## Appendix G — Technical Detail

### Why a Full Disk Stopped the Whole Application

Ledger Vault writes a session record and an audit log entry for every page view, so even read-only actions such as viewing a file list need a database write. When the disk filled, every request failed, not only uploads. A later design change, scheduled for 2027, will move session storage to an in-memory store so that read-only browsing can continue during database write failures.

### Why Recovery Took So Long After the Resize

After the resize at 12:22, the database had to replay its write-ahead log and run integrity checks across tables that had grown quickly during busy season. Recovery took 2 hours 28 minutes. Tessera's root cause analysis noted that recovery would have been about 40 minutes if the database had been resized before it filled, because no crash recovery would have been needed.

### What Was in the 500 GB

| Data | Size on 30 March 2026 |
|---|---|
| File metadata and permissions | 118 GB |
| Version history records | 196 GB |
| Audit log entries | 141 GB |
| Session records | 40 GB (expired sessions, deleted during the incident) |
| Indexes and other | 5 GB |

Audit log entries are kept for seven years for regulatory reasons. The IT team is planning to move audit log entries older than one year to cheaper archive storage in 2027, with Albion Assurance Certification's agreement that this still meets ISO 27001 logging requirements.

## Appendix H — Earlier Incidents on Ledger Vault

| Date | Incident | Duration | Cause |
|---|---|---|---|
| 14 November 2024 | Slow uploads | 3 hours degraded | Web application firewall rule blocking large files |
| 6 February 2025 | Login failures for clients | 50 minutes | Email one-time passcode provider outage |
| 30 March 2026 | Full outage | 6 hours 10 minutes | Database storage full (this postmortem) |

## Appendix I — Cost of the Incident

| Item | Estimate |
|---|---|
| Lost audit staff time (about 120 staff, about 4 productive hours each) | About 480 hours |
| Delayed report signings | 2 (including Marlowe Retail Group's FY2025 audit report, signed 1 April 2026) |
| Service Credit received from Tessera | USD 2,250, applied to the June 2026 hosting invoice |
| Additional storage cost after automatic scaling | About USD 75 per month |
| Client goodwill | Apology letter sent by the Managing Partner; no formal complaints received |

## Appendix J — Questions Raised at the Partners' Meeting

**Should Globex keep Ledger Vault in-house?** The partners agreed to keep Ledger Vault, because it gives clients a single secure place to share evidence and integrates with Fernbook, but asked IT to report on the renewal options with Tessera before the notice deadline of 30 January 2027.

**Could clients have been told sooner?** Yes. The first client communication was at 13:30, more than four hours into the outage. The IT on-call guide now requires engagement partners to be informed within 30 minutes of a Sev1 affecting Ledger Vault, so they can contact clients with imminent deadlines.

**Was any client data at risk?** No. The failure prevented writes but did not corrupt or expose data. The Legal Counsel confirmed that no client notification under the engagement letters' breach clauses was needed.

**What happens if this repeats during the 2027 busy season?** Automatic scaling, earlier alerts and the December capacity review should prevent a repeat. If Ledger Vault is unavailable for more than four hours during final fieldwork, engagement letters such as Marlowe's now allow a temporary encrypted transfer approved by the Head of IT, keeping UK files in the UK.

## Appendix K — Tessera's Root Cause Analysis (Summary)

Tessera's written root cause analysis for TES-55190 was received on 9 April 2026. It stated that:

1. The Globex metadata database reached 100% of its 500 GB allocation at 09:05 PKT. Automatic scaling was not enabled, as it is an opt-in setting.
2. The resize request was received at 09:42 PKT as a Priority 2 change. It was reclassified as Priority 1 at 10:30 after Globex's phone call.
3. The Bahrain resize queue was handled by a single engineer that morning because of a staff shortage; the resize itself took 52 minutes once started.
4. Tessera will staff the resize queue with at least two engineers during business hours and update its portal so that resize requests on a database reporting a full disk are automatically flagged as Priority 1.

Tessera's analysis initially classified the outage as excluded from availability under clause 6.4 because the full disk was caused by Globex's configuration. Globex disputed this, pointing to the 2 hours 40 minutes taken to complete an urgent resize. Tessera accepted the Service Credit claim in full in May 2026 without conceding the point, and the IT team considers the dispute a factor in the 2027 renewal decision.

## Appendix L — Timeline of Follow-Up Work

| Date | Activity |
|---|---|
| 31 March 2026 | Client apology sent by Imran Siddiqui |
| 2 April 2026 | Automatic storage scaling enabled; alerts lowered to 75% and routed to on-call phone |
| 6 April 2026 | Postmortem reviewed by IT team |
| 8 April 2026 | Service Credit claim filed with Tessera (within the 15-day window) |
| 9 April 2026 | Tessera root cause analysis received; partners' meeting review |
| May 2026 | Tessera approves USD 2,250 credit; exit plan updated |
| 3 July 2026 | Credit applied on the invoice for June hosting (USD 12,750) |
| December 2026 | First busy-season capacity review |
| By 30 January 2027 | Tessera renewal decision |

## Appendix M — Metrics Now Reported Monthly to the Partners

- Ledger Vault availability for the month, against the internal 99.9% target and Tessera's 99.95% commitment.
- Peak database storage use and number of automatic scaling events.
- Number and duration of Sev1 and Sev2 incidents.
- Restore test result and time.
- Any Service Credit due and its claim date.

## Appendix N — Lessons Shared With Other Teams

The finance team learned that the Tessera claim window is only 15 days and now records claim deadlines in the vendor register. The audit methodology team added a step to the busy-season plan: engagement managers agree with clients, before final fieldwork, which documents are needed in the last week, so that a portal outage on the final day has less impact. HR added a note to the Staff Handbook's busy-season guide on what to do if Ledger Vault is unavailable.

## Appendix O — Who Was Involved

| Person | Role in the incident |
|---|---|
| Kwame Mensah | Head of IT; incident commander |
| Two IT engineers | Diagnosis, cleanup of expired sessions, recovery monitoring |
| Tessera account engineer | Completed the resize under TES-55190 |
| Laura Bennett | CFO; filed the Service Credit claim on 8 April 2026 |
| Imran Siddiqui | Managing Partner; sent the client apology on 31 March 2026 |
| Nadia Hussain | Engagement partner for Marlowe Retail Group; agreed the one-day delay to the FY2025 report |
| Henrik Dahl | Legal Counsel; confirmed no client breach notification was required |
