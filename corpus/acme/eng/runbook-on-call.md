# Runbook: On-Call Rotation

## Purpose

The platform on-call engineer protects Atlas availability outside and inside business hours. This runbook explains the rotation, response times, escalation and pay.

## Rotation

The platform on-call rotation changes every Monday at 10:00 PKT. Each engineer is on call for one week at a time, at most one week in every four. The schedule is maintained in PagerDuty. Engineers swap shifts in PagerDuty and tell the platform lead; swaps must be in place before the shift starts.

## Before Your Shift

- Check that PagerDuty can reach you by phone call and push notification.
- Confirm your hardware security key works for production access.
- Read the handover notes from the previous engineer.
- Make sure you can reach a laptop and a reliable internet connection within 15 minutes at all times.

## Severity Levels and Response Times

| Severity | Definition | Acknowledge within |
|---|---|---|
| Sev1 | Atlas down for all clients, or data loss risk | 15 minutes |
| Sev2 | Major feature broken, or one client fully down | 30 minutes |
| Sev3 | Minor issue with a workaround | Next business day |

The Halvorsen Logistics MSA requires Acme to acknowledge Severity 1 incidents within 30 minutes and Severity 2 incidents within two hours. Our internal targets are stricter so that we meet the contract with margin.

## Handling an Incident

1. Acknowledge the page in PagerDuty.
2. Open an incident channel in Slack and post what you know.
3. For a Sev1, page the incident commander on duty immediately. The incident commander appoints a communications lead, who updates the status page within 15 minutes.
4. If the cause is Cobalt Cloud infrastructure, open a Priority 1 ticket with Cobalt support quoting CC-ENT-4471. Cobalt's first response target for Priority 1 is 15 minutes.
5. If the primary database is unavailable for more than 10 minutes, follow the database failover runbook.
6. Record every action and its time in the incident channel.

## Escalation

If the on-call engineer cannot resolve a Sev1 within 30 minutes, escalate to the incident commander on duty, then to Mei Lin Zhou (CTO). For incidents that may involve a security breach, also page the security lead and inform Tomás Ferreira (General Counsel), because client contracts require breach notification within 48 hours.

## Allowance and Time Off

Engineers receive an on-call allowance of PKR 15,000 per week on call, paid with the next month's salary. Engineers also receive time off in lieu for any incident handled between midnight and 06:00, equal to the time spent plus one hour, to be taken within a month.

## Handover

At handover, the outgoing engineer posts a summary of open incidents, alerts that fired, and anything unusual in the platform channel, and tags the incoming engineer. The incoming engineer acknowledges the handover before 10:30 PKT.

## Postmortems

Every Sev1, and any Sev2 lasting more than an hour, needs a blameless postmortem within ten business days. Postmortems list action items with owners and due dates in Jira. Severity 1 incidents affecting Halvorsen also require a written incident report to the client within ten Business Days.

## Tools

- PagerDuty: paging and schedules.
- Grafana Cloud: dashboards, logs and alerts.
- Cobalt Cloud support portal: infrastructure tickets.
- Status page: client communication.
- Jira: postmortem action items.

## Common Alerts

- Replication lag above 60 seconds on the Dubai replica: check Cobalt's status portal for network issues between Frankfurt and Dubai before anything else.
- Ingestion failures for one client: usually expired client credentials; contact the client's system owner listed in the client's contract key contacts.
- Certificate expiry warning: rotate the SAML signing certificate and give clients 14 days' notice.

## Example: Handling a Cobalt Cloud Incident at Night

At 02:30 PKT, alerts fire for failed writes and Cobalt's status portal reports a Frankfurt storage incident. The on-call engineer acknowledges within 15 minutes, declares a Sev1, and pages the incident commander, who appoints a communications lead. The engineer opens a Priority 1 ticket with Cobalt quoting CC-ENT-4471 and records the Cobalt incident reference. If the primary database remains read-only for more than 10 minutes with no recovery estimate, the incident commander decides to follow the database failover runbook. After recovery, the engineer sends the incident reference and outage times to finance the same day, because Cobalt Service Credits must be claimed within 30 days, and records time off in lieu for the hours worked between midnight and 06:00.

## Contacts

| Who | When |
|---|---|
| Incident commander on duty (PagerDuty schedule) | Every Sev1, and Sev2 lasting over an hour |
| Mei Lin Zhou, CTO | Sev1 unresolved after 30 minutes |
| Security lead and Tomás Ferreira, General Counsel | Any suspected security breach |
| Cobalt Cloud support (CC-ENT-4471) | Infrastructure faults; Priority 1 response in 15 minutes |
| Finance team | Same day, with Cobalt incident references for Service Credit claims |
