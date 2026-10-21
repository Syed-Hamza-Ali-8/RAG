# Runbook: Atlas Database Failover

## When to Use

Use this runbook when the primary Atlas PostgreSQL cluster in Frankfurt is unavailable or read-only for more than 10 minutes. Revised on 2 April 2026 after the March outage.

## Targets

Recovery point objective: 5 minutes. Recovery time objective: 30 minutes.

## Steps

1. Declare a Sev1 incident and page the on-call engineer and the incident commander.
2. Open a priority-one ticket with Cobalt Cloud support, quoting enterprise agreement CC-ENT-4471.
3. Confirm replication lag on the Dubai replica is under 5 minutes in Grafana.
4. Promote the Dubai replica using the platform CLI command for replica promotion.
5. Switch the Atlas database endpoint in the configuration service to the Dubai cluster.
6. Restart the ingestion workers and the dashboard service.
7. Verify dashboards load for at least two clients.
8. Post a status update to affected clients through the status page.

## After Failover

Rebuild Frankfurt as a replica of Dubai once Cobalt Cloud confirms the region is healthy. Fail back during the next maintenance window, not during business hours.

## Drills

This runbook is exercised in a failover drill every quarter.
