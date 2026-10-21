# Postmortem: Atlas Outage, 14 March 2026

## Summary

On 14 March 2026, Atlas was unavailable to all clients for 3 hours 40 minutes, from 06:10 to 09:50 UTC. Severity: Sev1. Incident commander: Bilal Ahmed.

## Impact

All Atlas dashboards were unavailable. The most affected client was Halvorsen Logistics, whose morning operations review relies on Atlas. No data was lost.

## Root Cause

A storage incident in Cobalt Cloud's Frankfurt region made the primary PostgreSQL cluster read-only. The team attempted failover to the Dubai region, but the database failover runbook was out of date: it referenced a replication setting that had been renamed in a platform upgrade in January. Working out the correct steps took about two hours.

## Timeline (UTC)

- 06:10 Alerts fire for failed writes.
- 06:25 Cobalt Cloud confirms a storage incident in Frankfurt.
- 06:40 Failover to Dubai starts and fails on step 4 of the runbook.
- 08:55 Corrected failover procedure identified.
- 09:50 Service restored from the Dubai region.

## Action Items

1. Update the database failover runbook and test it. Owner: Bilal Ahmed. Done 2 April 2026.
2. Claim the SLA credit from Cobalt Cloud for the outage. Owner: finance team. Claim filed 3 April 2026.
3. Run failover drills quarterly. Owner: Mei Lin Zhou.
4. Add a runbook review step to the platform upgrade checklist. Owner: platform team.
