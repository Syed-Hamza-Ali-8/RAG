# Runbook: Ledger Vault Backup and Restore

## Purpose

This runbook describes how Ledger Vault is backed up and how to restore it, either after data loss or to fail over to the Frankfurt disaster recovery region. It is owned by Kwame Mensah, Head of IT.

## Backups

### Database

The Ledger Vault metadata database is backed up nightly at 01:00 PKT. Backups are kept for 35 days. Each backup is encrypted with a Globex-managed key and copied to Tessera Cloud's Frankfurt region.

### Files

Client file storage uses object versioning with 90-day retention. UK client files in the London bucket are versioned in the London region only and are never copied to Frankfurt, so that they stay in the UK.

### Targets

Recovery point objective: 24 hours. Recovery time objective: 4 hours.

## When to Restore

- Data loss or corruption in the metadata database.
- Accidental deletion of a client folder beyond what versioning can recover.
- The Bahrain region is unavailable and Tessera cannot give a recovery estimate within one hour, in which case a restore into Frankfurt is considered.

The Head of IT decides whether to restore. During busy season (15 January to 31 March) the decision should be made quickly, because audit deadlines depend on Ledger Vault.

## Restore Procedure

1. Declare an incident and inform the Head of IT. For a full outage, declare Sev1 and follow the IT on-call escalation rules.
2. Raise a ticket with Tessera Cloud support quoting agreement TC-7720. If the service is down, raise it as Priority 1, including any storage resize request.
3. Identify the backup to restore: normally the most recent nightly backup, unless the problem started earlier.
4. Restore the backup to a new database instance in the chosen region (Bahrain, or Frankfurt for disaster recovery).
5. Point Ledger Vault at the restored instance in the application configuration.
6. Run the integrity check script, which compares database file records with object storage and lists any mismatches.
7. Re-attach the London bucket for UK client files if the restore is in Frankfurt; the files themselves stay in London.
8. Confirm with two audit teams that recent files are visible, including one UK engagement.
9. Tell engagement partners which uploads, if any, need to be repeated because they happened after the backup.

## Restoring a Single Client Folder

To recover a deleted folder, first try object versioning (deleted files can be restored within 90 days). If folder permissions or metadata are lost, restore the database backup to a temporary instance, export the affected records and re-import them. Never restore the full production database to recover a single folder.

## Restore Tests

A restore test is run on the first Monday of every month and the result is recorded in the IT log, including the time taken. The busy-season capacity review in December includes a full restore test at peak data volumes, to confirm the four-hour recovery time objective can still be met.

| Test | Date | Time to restore | Result |
|---|---|---|---|
| Monthly | 6 July 2026 | 1 h 50 m | Passed |
| Monthly | 3 August 2026 | 2 h 05 m | Passed |
| Monthly | 7 September 2026 | 2 h 20 m | Passed; integrity check flagged 3 orphan files, cleaned up |
| Monthly | 5 October 2026 | 2 h 10 m | Passed |

## Related Contract Terms

Tessera's agreement TC-7720 makes cross-region failover Globex's responsibility; Tessera provides the backup storage and the infrastructure, but not the restore itself. If an outage caused by Tessera reduces monthly availability below 99.95%, finance must claim the Service Credit within 15 days of the incident. Send the Tessera ticket reference and outage times to the finance team on the day of the incident.

## Lessons From March 2026

The 30 March 2026 outage did not need a restore: the database disk was full, and service returned after Tessera resized it. The postmortem nonetheless updated this runbook to make clear that urgent resize requests are Priority 1 when the service is down, because the resize took 2 hours 40 minutes as a Priority 2 change request.

## Example: Recovering a Deleted Client Folder

During busy season an engagement manager deletes the wrong folder for a Sunridge Schools Trust tax engagement. The IT service desk first restores the files from object versioning, which keeps deleted versions for 90 days. Folder permissions were also removed, so IT restores the previous night's database backup to a temporary instance, exports the permission records for that folder and re-imports them into production. The full production database is not restored. The engagement manager confirms the restored folder with the client's financial controller, and the incident is logged as a Sev3.

## Contacts

| Who | When |
|---|---|
| Kwame Mensah, Head of IT | Any decision to restore; Sev1 escalation after 45 minutes |
| Tessera Cloud support (TC-7720) | Infrastructure faults, resizes; Priority 1 when Ledger Vault is down |
| Engagement partners | Within 30 minutes of a Sev1 affecting Ledger Vault |
| Finance team | Same day, with the Tessera ticket reference, for Service Credit claims within 15 days |
| Henrik Dahl, Legal Counsel | Any suspected loss or exposure of client data |
