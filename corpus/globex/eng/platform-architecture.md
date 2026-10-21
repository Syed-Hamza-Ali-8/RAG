# Ledger Vault Platform Architecture

## Overview

Ledger Vault is Globex's secure client document portal. Clients upload trial balances, contracts and audit evidence, and audit teams link those files to working papers in Fernbook. The technical owner is Kwame Mensah, Head of IT. Ledger Vault is built and run in-house by the IT team.

## Hosting

### Provider

Ledger Vault is hosted on Tessera Cloud under agreement TC-7720 (USD 15,000 per month, term to 31 March 2027). Tessera commits to 99.95% monthly availability in the Bahrain region.

### Regions

- Bahrain: primary region for the application, the metadata database and most client files.
- Frankfurt: disaster recovery region, holding encrypted nightly backups.
- London: a dedicated storage bucket for UK client files, such as Marlowe Retail Group's, which must stay in the UK.

## Components

### Web Application

The Ledger Vault web application runs on Tessera virtual machines behind a managed web application firewall. Staff sign in with Microsoft Entra ID single sign-on and number-matching multi-factor authentication. Clients sign in with an email one-time passcode.

### Metadata Database

A managed PostgreSQL database stores file records, versions, permissions, sessions and audit log entries. Since the 30 March 2026 outage, automatic storage scaling is enabled (scaling at 80% usage in 25% steps), and storage alerts fire at 75% and 85%.

### Object Storage

Client files are stored in object storage with versioning enabled and 90-day version retention.

### Fernbook Connector

Fernbook, the audit working-paper platform supplied by Fernbook Ltd, links to Ledger Vault files through an API connector maintained by the IT team. When an auditor attaches evidence in Fernbook, the connector stores a reference to the Ledger Vault file rather than a copy.

## Availability and Recovery

Ledger Vault targets 99.9% availability, with a recovery point objective of 24 hours and a recovery time objective of 4 hours. Disaster recovery to Frankfurt is performed by restoring the latest backup into a new environment, following the backup and restore runbook. In March 2026 availability was 99.17% because of the 370-minute outage.

## Monitoring and On-Call

### Alerts

Alerts for database storage, failed uploads, application errors and certificate expiry are routed to the IT on-call phone and the IT team mailbox. Before April 2026 alerts went only to the mailbox.

### IT On-Call Rotation

The IT on-call rotation changes every Wednesday at 09:00 PKT. Sev1 incidents must be acknowledged within 20 minutes and Sev2 within one hour. Unresolved Sev1 incidents are escalated after 45 minutes to Kwame Mensah. The on-call allowance is PKR 12,000 per week. When the hosting platform is at fault, the on-call engineer raises a Priority 1 ticket with Tessera, quoting TC-7720; urgent resize requests are raised as Priority 1 whenever the service is down.

## IT Tooling Inventory

| Tool | Purpose | Owner | Contract |
|---|---|---|---|
| Tessera Cloud | Hosting for Ledger Vault (Bahrain, Frankfurt, London) | Kwame Mensah | TC-7720 |
| Fernbook | Audit working papers | Audit methodology team | Fernbook Ltd, FB-GLX-22 |
| Microsoft 365 and Entra ID | Email, documents, staff SSO | IT team | Enterprise agreement |
| Claimly | Expense claims | Finance | Annual subscription |
| Ledger Vault | Client document portal | IT team | Built in-house |

New tools that store client data need approval from the Head of IT and the Legal Counsel before purchase.

## Security

All client data is encrypted at rest with Globex-managed keys and in transit with TLS 1.2 or higher. Access to client folders is limited to the engagement team. Tessera must notify Globex of security incidents within 12 hours. Ledger Vault requires a separate login from email, which is why no client files were exposed in the August 2026 phishing incident.

## Capacity Planning

A capacity review runs every December before busy season (15 January to 31 March), when uploads peak at about three times the normal volume. The first review is scheduled for December 2026.

## Known Limitations

- Failover to Frankfurt is a manual restore, so the recovery time is hours rather than minutes.
- The Tessera agreement renews automatically on 31 March 2027 unless notice is given by 30 January 2027; the renewal decision is pending.
- Fernbook's contract (FB-GLX-22) ends on 31 December 2026, and the connector must be re-tested after any Fernbook upgrade.

## Change History

| Date | Change |
|---|---|
| April–May 2024 | Ledger Vault moved from a Lahore office server to Tessera Cloud (Bahrain) |
| September 2024 | London storage bucket added for UK client files |
| January 2025 | Encrypted backups to Frankfurt added after an ISO surveillance audit recommendation |
| 2 April 2026 | Automatic storage scaling enabled; alerts at 75% and 85% routed to the on-call phone |
| 22 August 2026 | MFA number matching enabled for staff sign-in after the phishing incident |
| December 2026 (planned) | First busy-season capacity review |
| 2027 (planned) | Session storage moved out of the database; old audit log entries archived |

## Frequently Asked Questions

**Why is Ledger Vault login separate from Microsoft 365?** It limits damage if a staff mailbox is compromised, as shown in the August 2026 phishing incident, where no Ledger Vault files were accessed.

**Why are UK files not in the Frankfurt backups?** Engagement letters with UK clients, such as Marlowe Retail Group, require their files to stay in the UK, so the London bucket relies on versioning within the London region instead.
