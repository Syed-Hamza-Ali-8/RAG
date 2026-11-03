# Postmortem: SSO Login Outage, 2 July 2026

## Summary

On 2 July 2026, client users could not log in to Atlas for 95 minutes because the SSO signing certificate had expired. Severity: Sev2. Incident commander: Mei Lin Zhou.

## Impact

Users with existing sessions were unaffected. New logins failed for all clients. Internal staff could not log in to the Atlas admin console.

## Root Cause

The SAML signing certificate was issued for one year in July 2025. Its expiry was tracked in a spreadsheet that had not been updated after the previous platform engineer left the company.

## Resolution

A new certificate was generated and uploaded, and each client's identity provider was updated with the new certificate fingerprint.

## Action Items

1. Monitor certificate expiry automatically and alert 30 days before expiry. Owner: platform team. Done.
2. Move certificate ownership to the platform team's on-call rota. Owner: Mei Lin Zhou.
3. Notify clients 14 days before any planned certificate rotation.
