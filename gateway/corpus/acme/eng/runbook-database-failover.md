# Runbook: Atlas Database Failover

## When to Use

Use this runbook when the primary Atlas PostgreSQL cluster in Frankfurt is unavailable or read-only for more than 10 minutes and Cobalt Cloud cannot give a recovery estimate within that time. Revised on 2 April 2026 for platform version 4.2 after the March outage (action item ATL-1121), and tested in the Q2 and Q3 2026 drills.

## Targets

Recovery point objective: 5 minutes. Recovery time objective: 30 minutes. These targets appear in the Halvorsen Logistics MSA, so every failover must be recorded for client reporting.

## Roles

- Incident commander: coordinates and decides go/no-go for promotion.
- Operator: runs the commands in this runbook.
- Communications lead: updates the status page within 15 minutes and every 30 minutes after, and emails Halvorsen's operations team hourly.

One person must not hold more than one role during a Severity 1 incident.

## Pre-Checks

1. Declare a Severity 1 incident in PagerDuty and page the incident commander on duty.
2. Open a Priority 1 ticket with Cobalt Cloud support, quoting enterprise agreement CC-ENT-4471. Record the Cobalt incident reference; finance needs it to claim a Service Credit.
3. Check Cobalt's status portal for the Frankfurt region and note the start time of the incident.
4. In Grafana, confirm replication lag on the Dubai replica is under 5 minutes. If it is higher, the incident commander decides whether to wait or accept the data loss, and records the decision.

## Promotion Steps

5. Pause the ingestion workers so that no new writes are attempted: scale every ingestion deployment to zero replicas.
6. Fence the old primary by revoking its network access in the Frankfurt security group, so that it cannot accept writes if it recovers mid-procedure.
7. Set replication.replica_slot to none on the Dubai replica. (Before platform 4.2 this setting was called replication.standby_name; the old name no longer works.)
8. Promote the Dubai replica using the platform CLI promotion command and wait for it to report the primary role.
9. Run the write check script against Dubai and confirm it succeeds.

## Switch Traffic

10. In the configuration service, change the Atlas database endpoint to the Dubai cluster.
11. Wait 30 seconds for client caches to expire.
12. Scale the ingestion workers back up. They will replay queued writes from their buffers.
13. Restart the dashboard service.

## Verification

14. Load dashboards for at least two clients, including Halvorsen Logistics.
15. Confirm in Grafana that ingestion has resumed and the backlog is shrinking.
16. Ask the communications lead to post a recovery update.

## After Failover

### Rebuild and Fail Back

Rebuild Frankfurt as a replica of Dubai once Cobalt Cloud confirms the region is healthy. Fail back during the next Sunday maintenance window (01:00 to 05:00 Central European Time), not during business hours, following steps 5 to 16 in the opposite direction.

### Records

Within two business days, the incident commander records the incident timeline, the replication lag at promotion, and the total downtime. Downtime is needed for the monthly availability report to clients and to check whether a Service Credit is owed under the Halvorsen MSA (below 99.5% in the month).

### Service Credit From Cobalt

Send the Cobalt incident reference and the outage times to the finance team the same day. Cobalt Service Credits must be claimed within 30 days of the end of the incident, and late claims are not honoured.

## Drills

This runbook is exercised in a failover drill every quarter. Results are recorded in the platform log and shared with Halvorsen Logistics on request. Q2 2026 drill: 19 minutes. Q3 2026 drill: 24 minutes, run by an engineer who had never performed a failover.

## Common Mistakes

- **Promoting before fencing the old primary.** If Frankfurt recovers during the procedure, two primaries could accept writes. Always complete step 6 before step 8.
- **Using the old setting name.** replication.standby_name was removed in platform 4.2. Use replication.replica_slot.
- **Forgetting the ingestion workers.** Workers left running during promotion produce a burst of failed writes and misleading alerts. Scale them to zero first.
- **Failing back during business hours.** Fail back only in the Sunday maintenance window.
- **Not telling finance.** Cobalt's 30-day Service Credit window starts at the end of the incident, not when the postmortem is finished.

## Drill Checklist

Before each quarterly drill: confirm the date with the communications lead; post a planned maintenance notice to clients at least five Business Days ahead, as the Halvorsen MSA requires for maintenance that may cause more than 30 minutes of unavailability; make sure an engineer who did not run the last drill operates this one; and record the time taken for each step.
