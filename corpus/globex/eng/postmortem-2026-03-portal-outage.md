# Postmortem: Ledger Vault Outage, 30 March 2026

## Summary

On 30 March 2026, during the last week of busy season, Ledger Vault was unavailable for 6 hours 10 minutes. Severity: Sev1. Incident commander: Kwame Mensah.

## Impact

Audit teams could not download client evidence for the final day of fieldwork for several December year-end audits, including Marlowe Retail Group. Two audit report sign-offs were delayed by one day.

## Root Cause

The metadata database ran out of storage after a surge of client uploads. Storage alerts were set at 95% and fired too late to act before the disk filled. A Tessera Cloud storage resize request also took longer than expected.

## Action Items

1. Enable automatic storage scaling on the database. Owner: IT team. Done.
2. Lower storage alerts to 75%. Owner: IT team. Done.
3. Claim the SLA credit from Tessera Cloud. Owner: finance. Claim filed 8 April 2026.
4. Run a capacity review before each busy season. Owner: Kwame Mensah.
