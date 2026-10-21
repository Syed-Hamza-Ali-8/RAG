# Cloud Services Agreement — Tessera Cloud Ltd

## 1. Parties and Signature

### 1.1 Parties

This Cloud Services Agreement ("Agreement") is between Tessera Cloud Ltd, a cloud hosting provider ("Tessera"), and Globex Partners LLP ("Globex" or "the Customer").

### 1.2 Reference

The agreement reference is TC-7720. Globex must quote this reference on all support tickets, Service Credit claims and notices.

### 1.3 Signature

This Agreement was signed on 1 April 2024 by Laura Bennett, Chief Financial Officer, on behalf of Globex, and by Rahul Menon, Regional Director, on behalf of Tessera. Globex's business owner for the Agreement is Kwame Mensah, Head of IT.

### 1.4 Purpose

Globex uses Tessera to host Ledger Vault, its secure client document portal, including the Ledger Vault web application, its metadata database and the object storage that holds client files.

## 2. Definitions

- "Region" means a Tessera data centre region. Globex uses the Bahrain, Frankfurt and London Regions.
- "Monthly Fee" means the fixed fee in clause 5.1.
- "Availability" means the percentage of minutes in a calendar month in which the hosted services are operational, as measured by Tessera's monitoring.
- "Incident" means an unplanned interruption to or degradation of the services.
- "Security Incident" means unauthorised access to, or loss or disclosure of, Customer Data.
- "Customer Data" means all data stored by Globex on Tessera's services, including client files uploaded to Ledger Vault.

## 3. Services

### 3.1 Included Services

Tessera provides: virtual machines and a managed web application firewall for the Ledger Vault application; a managed PostgreSQL database for Ledger Vault metadata, with nightly backups; object storage with versioning for client files; private networking; and 24x7 support.

### 3.2 Regions

| Region | Use |
|---|---|
| Bahrain | Primary Region for Ledger Vault application, database and most client files |
| Frankfurt | Disaster recovery Region; receives encrypted backups |
| London | Dedicated storage bucket for UK client files, such as Marlowe Retail Group |

### 3.3 Data Location

Tessera will keep Customer Data in the Region where Globex stores it. UK client files stay in the London Region and are not copied to Bahrain or Frankfurt, other than encrypted metadata records needed to locate them.

### 3.4 Storage Scaling

Following the March 2026 Ledger Vault outage, Globex enabled automatic storage scaling on the metadata database. Tessera will scale storage automatically when usage exceeds 80% of allocated capacity, in increments of 25%, and charges the additional storage at the unit prices in Schedule 1.

## 4. Term and Renewal

### 4.1 Term

The Agreement runs for three years, from 1 April 2024 to 31 March 2027.

### 4.2 Automatic Renewal

The Agreement renews automatically for one year unless either party gives at least 60 days' written notice of non-renewal before the end of the current term. For the initial term, notice must be given by 30 January 2027.

### 4.3 Renewal Pricing

On renewal Tessera may increase prices by no more than 4%.

## 5. Fees

### 5.1 Monthly Fee

The Monthly Fee is USD 15,000, covering the services in clause 3.1 up to the capacity in Schedule 1. Additional capacity is charged at the Schedule 1 unit prices.

### 5.2 Invoicing

Tessera invoices monthly in arrears on the third day of each month. Invoices are payable within 30 days. Globex's finance team checks each invoice against Tessera's usage report before approval.

## 6. Service Level Agreement

### 6.1 Availability Commitment

Tessera commits to 99.95% monthly Availability for the hosted services in the Bahrain Region.

### 6.2 Service Credits

| Monthly Availability | Service Credit |
|---|---|
| 99.95% or higher | None |
| Below 99.95% but at least 99.5% | 5% of the Monthly Fee |
| Below 99.5% | 15% of the Monthly Fee |

### 6.3 Claims

Service Credits must be claimed in writing within 15 days of the Incident, quoting TC-7720 and the Tessera ticket reference. Late claims are not honoured. Approved credits are deducted from a later invoice.

### 6.4 Exclusions

Availability excludes downtime caused by Globex's own actions or configuration, scheduled maintenance announced at least five days in advance, and force majeure. Tessera's position after the March 2026 outage was that the database running out of storage was partly a configuration matter; after discussion, Tessera accepted that its slow storage resize extended the outage and approved the full 15% credit.

### 6.5 Worked Example

March has 44,640 minutes. An outage of 370 minutes gives Availability of 99.17%, which is below 99.5%, so the Service Credit is 15% of the USD 15,000 Monthly Fee, or USD 2,250.

## 7. Support

### 7.1 Response Times

Priority 1 (service down): response within 30 minutes, 24x7. Priority 2 (degraded): response within two hours. Priority 3: next business day.

### 7.2 Resize and Change Requests

Storage and compute resize requests are handled as Priority 2 unless the service is down, in which case they may be raised as Priority 1. Tessera aims to complete urgent resize requests within one hour. During the March 2026 outage a resize request (ticket TES-55190) took 2 hours 40 minutes.

## 8. Security

### 8.1 Certifications

Tessera holds ISO 27001 certification for all Regions used by Globex and will provide its certificate and statement of applicability on request.

### 8.2 Security Incident Notification

Tessera will notify Globex of any Security Incident affecting Customer Data within 12 hours of becoming aware of it. This allows Globex to meet the commitments in its client engagement letters, such as notifying Marlowe Retail Group within 72 hours of a personal data breach.

### 8.3 Encryption

All Customer Data is encrypted at rest with keys managed by Globex. Backups sent to the Frankfurt Region are encrypted before transfer.

## 9. Data Processing

Tessera acts as a processor of Customer Data and processes it only on Globex's instructions. Tessera may not use subprocessors with access to Customer Data without 30 days' notice to Globex. On termination, Tessera deletes all Customer Data within 30 days after the exit period and certifies deletion on request.

## 10. Audit

Globex may review Tessera's certifications and audit reports once a year. Globex's ISO 27001 certification body may rely on these materials for Globex's own audits.

## 11. Liability

Each party's liability in any 12-month period is capped at the fees paid in that period. Tessera's liability for breach of clauses 8 and 9 is capped at twice the annual fees. Neither party is liable for indirect loss.

## 12. Termination and Exit

Either party may terminate for material breach not remedied within 30 days. On expiry or termination, Tessera will provide an exit period of up to 45 days during which Globex can export all Customer Data at no additional egress charge.

## 13. Governing Law

This Agreement is governed by the laws of the Dubai International Financial Centre, and disputes are resolved by the DIFC Courts.

## Schedule 1 — Capacity and Unit Prices

| Item | Included in Monthly Fee | Additional unit price |
|---|---|---|
| Application virtual machines | 8 vCPU, 32 GB RAM | USD 45 per vCPU-month |
| Metadata database storage | 500 GB | USD 0.30 per GB-month |
| Client file object storage (all Regions) | 20 TB | USD 22 per TB-month |
| Backup storage (Frankfurt) | 10 TB | USD 18 per TB-month |

## Schedule 2 — Contacts

| Role | Tessera | Globex |
|---|---|---|
| Contract owner | Rahul Menon, Regional Director | Laura Bennett, CFO |
| Technical owner | Tessera account engineer | Kwame Mensah, Head of IT |
| Legal notices | Tessera Legal | Henrik Dahl, Legal Counsel |

## Schedule 3 — Service Credit History

| Month | Availability | Credit | Claim filed | Applied |
|---|---|---|---|---|
| March 2026 | 99.17% (370-minute outage on 30 March) | USD 2,250 (15%) | 8 April 2026, within the 15-day window | June 2026 invoice, dated 3 July 2026 |

## Schedule 4 — Renewal Position (Internal Note by Globex Legal)

The renewal decision is due by 30 January 2027, because the Agreement renews automatically for one year unless notice is given 60 days before 31 March 2027. The ISO 27001 surveillance audit on 8 to 10 March 2027 requires an agreement in force on the audit dates; the current term covers those dates either way. Kwame Mensah is assessing whether to renew, given the March 2026 outage and the slow resize, or to move Ledger Vault to another provider. Laura Bennett will decide by 15 January 2027 after a cost comparison.

## Schedule 5 — Business Continuity

Tessera maintains a business continuity plan for each Region and tests it annually. Failover of Ledger Vault from Bahrain to Frankfurt is Globex's responsibility and is performed by restoring the latest encrypted backup into a new Frankfurt environment. Globex's restore runbook targets a recovery time of four hours and a recovery point of 24 hours.

## Schedule 6 — Scheduled Maintenance and Change Notices

Tessera announces scheduled maintenance at least five days in advance on its status page and by email to the technical owner. Maintenance in the Bahrain Region takes place between 01:00 and 04:00 local time. Globex has asked Tessera not to schedule maintenance between 15 January and 31 March each year, which is Globex's busy season, and Tessera has agreed to do so where possible but has not made it a contractual commitment.

## Schedule 7 — Usage Reporting

Tessera provides a monthly usage report showing database storage, object storage per Region and compute consumption. Globex's IT team reviews the report monthly against the capacity included in the Monthly Fee, and the finance team uses it to check invoices before approval.

## Schedule 8 — Additional Terms

### 8.1 Subcontracting and Assignment

Tessera may not subcontract the core hosting services without Globex's consent. Neither party may assign this Agreement without the other's written consent, except to a successor of its whole business with written notice.

### 8.2 Insurance

Tessera maintains professional and cyber liability insurance of at least USD 10 million per claim.

### 8.3 Compliance With Laws

Each party complies with applicable laws, including data protection and anti-bribery laws. Tessera confirms it does not transfer Customer Data outside the Region where Globex stores it.

### 8.4 Force Majeure

Neither party is liable for delays caused by events beyond its reasonable control. Force majeure does not excuse Tessera from maintaining backups and business continuity plans. If a force majeure event affects the Bahrain Region for more than 21 days, Globex may terminate without penalty.

### 8.5 Escalation

Disputes are first escalated to Tessera's Regional Director and Globex's CFO, who will meet within ten business days. Operational escalations during an Incident go first to the Tessera duty manager, then to the account engineer, then to the Regional Director.

### 8.6 Customer Responsibilities

Globex is responsible for configuring the hosted services, including storage alert thresholds and automatic scaling settings, keeping the Ledger Vault application patched, managing user access to Ledger Vault, and testing its own restore procedures.

### 8.7 Changes to the Services

Tessera may change or retire a service with at least six months' notice, providing a migration path to an equivalent service at no extra charge.

## Schedule 9 — Security Requirements

| Requirement | Tessera commitment |
|---|---|
| Encryption at rest | AES-256 for all storage, keys managed by Globex |
| Encryption in transit | TLS 1.2 or higher for all connections |
| Administrative access | Named Tessera engineers only, with multi-factor authentication and logging |
| Vulnerability management | Critical infrastructure vulnerabilities patched within 7 days |
| Penetration testing | Annual independent test of the hosting platform; summary shared with Globex |
| Logging | Infrastructure logs retained for 12 months and available to Globex on request |
| Security Incident notification | Within 12 hours |

## Schedule 10 — Exit Plan Summary (Internal)

Because Ledger Vault is a critical service, Globex keeps an exit plan for Tessera. The plan assumes a 45-day exit period and covers: exporting the metadata database and all object storage, including the London bucket for UK clients, without moving UK files outside the UK; standing up Ledger Vault with an alternative provider in the same regions; re-pointing the Fernbook connector to the new storage; and notifying clients whose engagement letters name the hosting arrangements, such as Marlowe Retail Group. The estimated migration effort is eight weeks for two IT engineers. The plan is reviewed every year by Kwame Mensah and was last updated in May 2026, after the March outage.

## Schedule 11 — Onboarding History

Ledger Vault moved to Tessera in April and May 2024, from a server in Globex's Lahore office. The London storage bucket for UK clients was added in September 2024, when Globex began auditing UK clients from the Manchester office, so that UK client files would stay in the UK. The Frankfurt backup arrangement was added in January 2025 after Globex's ISO 27001 surveillance audit recommended off-region backups.

## Schedule 12 — Service Descriptions

### 12.1 Virtual Machines and Firewall

Tessera provides the virtual machines that run the Ledger Vault web application, patches the hypervisor and host operating systems, and operates a managed web application firewall in front of the application. Globex is responsible for patching the guest operating system and the Ledger Vault application, which the IT team does monthly and within seven days for critical vulnerabilities.

### 12.2 Managed PostgreSQL

Tessera operates the metadata database, takes nightly backups at 01:00 PKT, keeps them for 35 days and copies them in encrypted form to the Frankfurt Region. Point-in-time recovery is available for the most recent seven days. Storage scaling is manual unless Globex enables automatic scaling, which it did on 2 April 2026.

### 12.3 Object Storage

Object storage holds client files with versioning enabled. Versions are kept for 90 days. The London bucket for UK client files is configured with no cross-region replication.

### 12.4 Monitoring Provided by Tessera

Tessera monitors infrastructure health and publishes Region status on its status page. Tessera does not monitor Ledger Vault's application or alert Globex about database storage levels; those alerts are configured and owned by Globex.

## Schedule 13 — Support Procedure

### 13.1 Raising Tickets

Tickets are raised through Tessera's support portal by named Globex IT staff, quoting TC-7720, the Region and the affected resource. Priority 1 tickets must also be phoned through to Tessera's support line.

### 13.2 Classification of Resize Requests

Tessera's portal classifies resize requests as changes by default, which are handled as Priority 2. Under clause 7.2, Globex may raise an urgent resize as Priority 1 when the service is down. During the 30 March 2026 outage, ticket TES-55190 was first raised as Priority 2 and only raised to Priority 1 after a phone call 48 minutes later. Globex's IT on-call guide and restore runbook now instruct engineers to raise urgent resizes as Priority 1 from the start and to phone the support line.

### 13.3 Root Cause Analysis

For Priority 1 incidents, Tessera provides a written root cause analysis within ten business days. Tessera's analysis of TES-55190 acknowledged that the resize queue was handled by a single engineer that morning and committed to staffing the resize queue with at least two engineers during business hours in the Bahrain Region.

## Schedule 14 — Renewal Options Analysis (Internal, October 2026)

| Option | Annual cost (estimate) | Benefits | Risks |
|---|---|---|---|
| Renew with Tessera for one year (automatic) | USD 187,200 (4% increase) | No migration; known platform | Slow support on resizes; dispute over exclusions in March 2026 |
| Renegotiate with Tessera for two years | USD 175,000 to 180,000 | Lower price; chance to add a busy-season maintenance freeze and faster resize commitments | Tessera may refuse contractual changes |
| Move Ledger Vault to another provider | USD 160,000 to 200,000 plus migration effort of about eight weeks | Possible better support; Globex-managed failover options | Migration during or near busy season is high risk; UK files must stay in the UK throughout |

Kwame Mensah recommends renegotiating with Tessera for two years, provided Tessera agrees in writing to a busy-season maintenance freeze and a one-hour target for urgent resizes. If Tessera does not agree by 15 January 2027, Laura Bennett will decide whether to give notice by 30 January 2027 and plan a migration for April to June 2027, after busy season and after the ISO 27001 surveillance audit on 8 to 10 March 2027.

## Schedule 15 — Dependencies on This Agreement

| Dependent | How it depends on Tessera |
|---|---|
| Ledger Vault | Fully hosted on Tessera |
| Fernbook | Its connector links working papers to files stored in Ledger Vault on Tessera |
| Marlowe Retail Group engagement | Engagement letter states that files are stored in Ledger Vault's London storage hosted by Tessera |
| Sunridge Schools Trust agreement | Files stored in Ledger Vault's Bahrain storage hosted by Tessera |
| ISO 27001 certification | Supplier controls require an in-force agreement and monthly SLA monitoring |

## Schedule 16 — Monthly SLA Monitoring Log, 2026

| Month | Availability (Bahrain) | Credit due | Reviewed by finance |
|---|---|---|---|
| January | 100.00% | None | Yes |
| February | 99.98% | None | Yes |
| March | 99.17% | USD 2,250 (15%) | Yes; claim filed 8 April |
| April | 100.00% | None | Yes |
| May | 99.99% | None | Yes |
| June | 100.00% | None | Yes |
| July | 99.96% | None | Yes |
| August | 100.00% | None | Yes |
| September | 100.00% | None | Yes |

This log was introduced after Albion Assurance Certification's 2026 finding that Tessera's availability was not reviewed against the SLA each month. It forms part of the evidence for the March 2027 surveillance audit.

## Schedule 17 — Questions Answered for Globex's IT and Finance Teams

**What is the claim window for a Service Credit?** 15 days from the Incident (clause 6.3). Send the Tessera ticket reference and outage times to finance on the day.

**Should an urgent resize be Priority 1?** Yes, when Ledger Vault is down (clause 7.2 and Schedule 13). Phone the support line as well as raising the ticket.

**Where are UK client files?** In the London Region only (clause 3.3). They are not included in the Frankfurt backups.

**When must we decide on renewal?** Notice must be given by 30 January 2027, otherwise the Agreement renews for one year from 1 April 2027 with a price increase of up to 4%.

**Who signs a renewal or termination notice?** Laura Bennett, CFO, after review by Henrik Dahl, Legal Counsel.

## Schedule 18 — Data Flows Hosted on Tessera

| Flow | Region | Data |
|---|---|---|
| Client uploads to Ledger Vault | Bahrain (most clients) or London (UK clients) | Trial balances, contracts, audit evidence, payroll extracts for tax work |
| Metadata database | Bahrain | File records, versions, permissions, sessions, audit log entries |
| Nightly encrypted backups | Bahrain to Frankfurt | Metadata database only; UK client files excluded |
| Fernbook connector | Bahrain | References to files; no file copies |
| Staff access | All Regions, through Ledger Vault | Staff sign in with Microsoft Entra ID and number-matching MFA |

Tessera has no access to the content of client files except where Globex asks for support in a ticket and approves access, which has not happened to date.
