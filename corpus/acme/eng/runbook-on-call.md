# Runbook: On-Call Rotation

## Rotation

The platform on-call rotation changes every Monday at 10:00 PKT. Each engineer is on call for one week at a time. The schedule is maintained in PagerDuty.

## Response Times

- Sev1 (Atlas down for all clients): acknowledge within 15 minutes.
- Sev2 (major feature broken or one client down): acknowledge within 30 minutes.
- Sev3: next business day.

## Escalation

If the on-call engineer cannot resolve a Sev1 within 30 minutes, escalate to the incident commander on duty, then to Mei Lin Zhou (CTO).

## Allowance

Engineers receive an on-call allowance of PKR 15,000 per week on call, plus time off in lieu for any incident handled between midnight and 06:00.

## Handover

At handover, the outgoing engineer posts a summary of open incidents and alerts in the platform channel.
