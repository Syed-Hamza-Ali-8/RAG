# Enterprise Cloud Services Agreement — Cobalt Cloud GmbH

## 1. Parties, Reference and Signature

### 1.1 Parties

This Enterprise Cloud Services Agreement ("Agreement") is between Cobalt Cloud GmbH, a cloud infrastructure provider registered in Germany ("Cobalt"), and Acme Advisory Group ("Acme" or "the Customer").

### 1.2 Agreement Reference

The agreement reference is CC-ENT-4471. Acme must quote this reference on every support ticket, invoice query and contract notice.

### 1.3 Signature

This Agreement was signed on 1 September 2023 by Daniel Okafor, Chief Financial Officer, on behalf of Acme, and by Lukas Brandt, Vice President Enterprise Sales, on behalf of Cobalt. Acme's internal business owner for the Agreement is Mei Lin Zhou, Chief Technology Officer. Cobalt's named customer success manager for Acme is Anja Weber.

### 1.4 Purpose

Acme uses Cobalt's infrastructure to host Atlas, its managed analytics platform, and client-specific workloads that Acme delivers under client Statements of Work, including the Brightwater Health Trust cloud migration in Cobalt's London region.

## 2. Definitions

- "Region" means a Cobalt data centre region. The Regions used by Acme are Frankfurt, Dubai and London.
- "Regional Fees" means the fees charged for services consumed in a single Region in a calendar month.
- "Availability" means the percentage of minutes in a calendar month during which the services in a Region are operational, as measured by Cobalt's monitoring and published on the Cobalt status portal.
- "Incident" means an unplanned interruption to, or degradation of, the services.
- "Security Incident" means any unauthorised access to, or loss, alteration or disclosure of, Customer data.
- "Customer Data" means all data stored by Acme on Cobalt's services, including the data of Acme's clients.

## 3. Services

### 3.1 Service Catalogue

Cobalt provides the following services to Acme under this Agreement: managed Kubernetes clusters; managed PostgreSQL clusters with cross-Region asynchronous replication; block and object storage; virtual private networking and private interconnects; key management; and 24x7 enterprise support.

### 3.2 Regions in Use

| Region | Purpose for Acme | Typical monthly Regional Fees |
|---|---|---|
| Frankfurt | Primary Region for Atlas production | about EUR 16,500 |
| Dubai | Disaster recovery Region for Atlas | about EUR 4,200 |
| London | Brightwater Health Trust workloads (UK data residency) | about EUR 2,700 |

### 3.3 Data Location

Cobalt will store Customer Data only in the Region where Acme places it. Cobalt will not replicate Customer Data between Regions unless Acme configures replication. Acme is responsible for configuring Regions in line with its own client contracts, including keeping UK healthcare data in the London Region only.

## 4. Term and Renewal

### 4.1 Term

This Agreement runs from 1 September 2023 to 31 December 2026.

### 4.2 No Automatic Renewal

This Agreement does not renew automatically. Any renewal must be agreed in a written amendment signed by both parties before 31 December 2026. If no renewal is signed, the services end on 31 December 2026 and the exit provisions in clause 13 apply.

### 4.3 Renewal Pricing

If the parties renew, Cobalt will not increase unit prices by more than 5% compared with the prices in force on 30 November 2026.

## 5. Fees, Committed Spend and Invoicing

### 5.1 Committed Spend

Acme commits to a minimum spend of EUR 22,000 per month across all Regions ("Committed Spend"). If actual consumption in a month is below the Committed Spend, Cobalt invoices the Committed Spend. Consumption above the Committed Spend is charged at the unit prices in Schedule A.

### 5.2 Discount

In return for the Committed Spend, Cobalt applies a 12% discount to its published list prices for all services consumed under this Agreement.

### 5.3 Invoicing

Cobalt invoices monthly in arrears on the fifth day of each month, itemised by Region. Invoices are payable within 30 days. Acme's finance team processes Cobalt invoices in Ledgerline and matches them to the vendor register entry for CC-ENT-4471.

### 5.4 Disputed Invoices

Acme must notify Cobalt of a disputed invoice line within 20 days of the invoice date. Undisputed lines remain payable on time.

## 6. Service Level Agreement

### 6.1 Availability Commitment

Cobalt commits to 99.9% Availability in each Region in each calendar month.

### 6.2 Service Credits

If Availability in a Region falls below the commitment, Acme is entitled to a Service Credit calculated as a percentage of that month's Regional Fees for the affected Region:

| Monthly Availability in the Region | Service Credit |
|---|---|
| 99.9% or higher | None |
| Below 99.9% but at least 99.0% | 10% of the Region's monthly fees |
| Below 99.0% | 25% of the Region's monthly fees |

### 6.3 Claiming Service Credits

Service Credits must be claimed in writing, quoting CC-ENT-4471 and the Cobalt incident reference, within 30 days of the end of the Incident. Cobalt does not honour late claims. Approved Service Credits are deducted from a subsequent monthly invoice, normally within three billing cycles.

### 6.4 Exclusions

Availability does not count downtime caused by Acme's own configuration errors, by scheduled maintenance announced at least seven days in advance, or by force majeure events.

### 6.5 Worked Example

In March, a month of 44,640 minutes, an Incident in the Frankfurt Region lasting 220 minutes gives Availability of 99.51%. That is below 99.9% but above 99.0%, so the Service Credit is 10% of March's Frankfurt Regional Fees.

## 7. Support

### 7.1 Support Tiers

Acme receives Enterprise support. Priority 1 tickets (production service down) receive a first response within 15 minutes, 24 hours a day. Priority 2 tickets (production degraded) receive a first response within one hour. Priority 3 tickets receive a response within one business day.

### 7.2 Escalation

If a Priority 1 ticket is not progressing, Acme may escalate to the Cobalt duty manager through the support portal, and then to the customer success manager, Anja Weber.

### 7.3 Incident Communication

During a Priority 1 Incident, Cobalt will publish updates on its status portal at least every 30 minutes and will provide a written root cause analysis within ten business days of resolution.

## 8. Security

### 8.1 Certifications

Cobalt maintains ISO 27001 and SOC 2 Type II reports covering all Regions used by Acme and will provide current copies on request, at least once a year. Acme relies on these reports as evidence for its own ISO 27001 certification.

### 8.2 Security Incident Notification

Cobalt will notify Acme of any Security Incident affecting Customer Data without undue delay and in any event within 24 hours of becoming aware of it. This timeline supports Acme's commitments to its own clients, such as the 48-hour breach notification commitment in Acme's agreement with Halvorsen Logistics.

### 8.3 Encryption and Keys

All storage is encrypted at rest. Acme manages its own encryption keys in Cobalt's key management service, and Cobalt staff cannot access them.

### 8.4 Personnel

Cobalt staff with access to infrastructure hosting Customer Data are background-checked and complete annual security training.

## 9. Data Processing

### 9.1 Processor Role

For personal data in Customer Data, Cobalt acts as a processor (or sub-processor, where Acme acts as processor for its own clients). The data processing terms in Schedule B apply.

### 9.2 Cobalt's Own Subprocessors

Cobalt uses a limited number of its own subprocessors for data centre operations and support tooling. Cobalt will give Acme 30 days' notice of any new subprocessor with access to Customer Data. This notice period matches the subprocessor notice that Acme gives its own clients.

### 9.3 Deletion

On termination Cobalt deletes all Customer Data within 30 days after the end of the exit period described in clause 13 and certifies deletion in writing on request.

## 10. Audit Rights

Once a year, on 30 days' notice, Acme may audit Cobalt's compliance with clauses 8 and 9, either by reviewing Cobalt's certifications and audit reports or, if those do not answer Acme's questions, through a remote audit. Acme's certification body may rely on these materials for Acme's own ISO 27001 audits.

## 11. Liability

Each party's total liability in any 12-month period is capped at the fees paid by Acme in that period. The cap does not apply to Cobalt's breach of clauses 8 (Security) or 9 (Data Processing), which is capped at three times the annual fees. Neither party is liable for indirect or consequential loss.

## 12. Termination

Either party may terminate this Agreement for material breach not remedied within 30 days of notice. Acme may terminate without penalty if Availability in the Frankfurt Region falls below 99.0% in three months within any 12-month period.

## 13. Exit

### 13.1 Exit Period

On expiry or termination, Cobalt will continue to provide the services for an exit period of up to 60 days at the prices then in force, so that Acme can migrate Customer Data to another provider.

### 13.2 Data Export

During the exit period Acme can export all Customer Data using standard tools, at no extra charge for data egress up to 50 TB.

### 13.3 Exit Plan

Because Atlas and the Brightwater Health migration depend on Cobalt, Acme classes Cobalt as a critical vendor and keeps a documented exit plan. The exit plan names an alternative hosting provider and estimates a migration time of ten weeks for Atlas.

## 14. Notices and Governing Law

Contract notices must be sent in writing to the addresses in Schedule C, quoting CC-ENT-4471. This Agreement is governed by German law, and the courts of Frankfurt am Main have exclusive jurisdiction.

## Schedule A — Unit Prices (After Discount)

| Service | Unit | Frankfurt | Dubai | London |
|---|---|---|---|---|
| Managed Kubernetes worker | per vCPU-month | EUR 21.10 | EUR 23.80 | EUR 22.40 |
| Managed PostgreSQL | per vCPU-month | EUR 38.50 | EUR 42.20 | EUR 40.10 |
| Block storage | per GB-month | EUR 0.09 | EUR 0.11 | EUR 0.10 |
| Object storage | per GB-month | EUR 0.021 | EUR 0.025 | EUR 0.023 |
| Cross-Region replication | per GB transferred | EUR 0.018 | EUR 0.018 | not used |

## Schedule B — Data Processing Terms (Summary)

Cobalt processes Customer Data only on Acme's documented instructions; keeps it confidential; implements the security measures in clause 8; assists Acme with data subject requests and data protection impact assessments; notifies Security Incidents within 24 hours; and deletes Customer Data at the end of the Agreement.

## Schedule C — Contacts

| Role | Cobalt | Acme |
|---|---|---|
| Contract owner | Lukas Brandt, VP Enterprise Sales | Daniel Okafor, CFO |
| Customer success / business owner | Anja Weber | Mei Lin Zhou, CTO |
| Support escalation | Cobalt duty manager (support portal) | Platform on-call engineer |
| Legal notices | Cobalt Legal Department, Frankfurt | Tomás Ferreira, General Counsel |

## Schedule D — Renewal Status (Internal Note Appended by Acme Legal)

As of October 2026, renewal negotiations are under way, led by Daniel Okafor with technical input from Mei Lin Zhou. Acme is seeking a two-year renewal with Committed Spend reduced to EUR 20,000 per month and the London Region added to the 99.9% commitment schedule. Acme's ISO 27001 audit plan requires the renewal to be signed by 30 November 2026 so that an in-force agreement is in place for the February 2027 recertification audit.

## Schedule E — Additional Terms

### E.1 Business Continuity

Cobalt maintains a business continuity and disaster recovery plan for each Region, tested at least annually. Cobalt will provide a summary of the most recent test on request. Cobalt does not guarantee cross-Region failover for Acme's workloads; designing and testing failover between Regions is Acme's responsibility.

### E.2 Capacity Reservations

Cobalt reserves capacity for Acme in the Frankfurt Region equal to 150% of Acme's average consumption over the previous three months, so that Acme can scale during client onboarding. Capacity in the Dubai Region is reserved at 100% of the Frankfurt production footprint, so that a full failover of Atlas to Dubai is always possible.

### E.3 Changes to the Services

Cobalt may change or retire a service with at least 12 months' notice, or 90 days' notice if required for security reasons. Cobalt will provide a migration path to an equivalent service at no extra cost.

### E.4 Scheduled Maintenance

Scheduled maintenance is announced on the status portal at least seven days in advance and takes place between 00:00 and 04:00 local time in the affected Region. Acme schedules its own Atlas maintenance window on Sundays from 01:00 to 05:00 Central European Time, which overlaps with Cobalt's Frankfurt window.

### E.5 Subcontracting and Assignment

Cobalt may not subcontract the core hosting services without Acme's consent, other than to its approved subprocessors. Neither party may assign this Agreement without the other's consent, except to an acquirer of all or substantially all of its business, with written notice.

### E.6 Insurance

Cobalt maintains professional liability and cyber insurance of at least EUR 20 million per claim and will provide certificates on request.

### E.7 Compliance with Laws

Each party will comply with all laws that apply to it, including data protection, export control and anti-bribery laws. Cobalt confirms that no Customer Data is transferred outside the Region where Acme stores it.

### E.8 Force Majeure

Neither party is liable for failure to perform caused by events beyond its reasonable control, such as natural disasters, war or widespread power failures. Force majeure does not excuse Cobalt from its obligations to maintain backups and business continuity plans. If a force majeure event affects a Region for more than 30 days, Acme may terminate the services in that Region without penalty.

### E.9 Dispute Resolution

Before starting court proceedings, the parties will escalate any dispute to Cobalt's VP Enterprise Sales and Acme's CFO, who will meet within 15 business days to try to resolve it.

### E.10 Usage Reporting

Cobalt provides a monthly usage report per Region, which Acme's finance team uses to check invoices before approval in Ledgerline and to track spend against the 2026 cloud hosting budget of USD 310,000.

### E.11 Service Credit History

| Month | Region | Availability | Credit claimed | Status |
|---|---|---|---|---|
| March 2026 | Frankfurt | 99.51% | EUR 1,650 (10% of EUR 16,500) | Approved 28 April 2026, applied to July 2026 invoice |
| August 2025 | Dubai | 99.86% | EUR 410 (10% of EUR 4,100) | Approved, applied to October 2025 invoice |

## Schedule F — Service Descriptions

### F.1 Managed Kubernetes

Cobalt operates the Kubernetes control plane and patches it within 14 days of a security release. Acme manages its own workloads, namespaces and node pools. Atlas runs its ingestion workers and dashboard service on managed Kubernetes in Frankfurt, with a smaller standby node pool in Dubai that is scaled up during failover.

### F.2 Managed PostgreSQL

Cobalt provides PostgreSQL clusters with automated backups, point-in-time recovery for up to 14 days, and asynchronous replication to another Region. Cobalt does not promote replicas automatically; promotion is performed by Acme. Cobalt offers multi-zone placement within a Region as an option, which Acme did not select when the Agreement was signed. Acme's request to move Atlas to multi-zone placement in Frankfurt was submitted on 10 April 2026 and is being implemented as action item ATL-1125.

### F.3 Storage

Block storage is used for database and worker volumes. Object storage holds backups and exports. Object storage in the London Region is used only for Brightwater Health Trust data.

### F.4 Networking

Each Region has a private network for Acme. Frankfurt and Dubai are connected by a private interconnect used for database replication. The London Region has no interconnect to Frankfurt or Dubai, by design, so that Brightwater data cannot be replicated out of the UK.

### F.5 Key Management

Acme creates and controls encryption keys in Cobalt's key management service. Keys for the London Region are separate from keys for Frankfurt and Dubai.

## Schedule G — Support Procedure

### G.1 Raising Tickets

Tickets are raised through the Cobalt support portal by named Acme contacts: the platform team members and the on-call engineer. Each ticket must quote CC-ENT-4471, the Region, the affected resource and the business impact. Priority 1 tickets should also be phoned through to the support hotline.

### G.2 Priority Definitions

| Priority | Definition | First response |
|---|---|---|
| P1 | Production service in a Region is down or data is at risk | 15 minutes, 24x7 |
| P2 | Production service degraded | 1 hour, 24x7 |
| P3 | Non-production issue or question | 1 business day |
| P4 | Feature request | 5 business days |

### G.3 Root Cause Analysis

For every P1 Incident, Cobalt provides a written root cause analysis within ten business days. For the 14 March 2026 Frankfurt storage incident (Cobalt reference COB-INC-88213), the root cause analysis was received on 26 March 2026 and attributed the incident to a storage controller firmware defect in availability zone fra-2.

## Schedule H — Draft Renewal Term Sheet (Under Negotiation, October 2026)

| Term | Current Agreement | Acme's proposal | Cobalt's position |
|---|---|---|---|
| Term | To 31 December 2026 | Two years, to 31 December 2028 | Three years preferred |
| Committed Spend | EUR 22,000 per month | EUR 20,000 per month | EUR 22,000 for two years, EUR 21,000 for three |
| Discount | 12% | 15% | 13% |
| Multi-zone PostgreSQL in Frankfurt | Not included | Included at no extra charge | Included, with a 6% uplift on database prices |
| Service Credit claim window | 30 days | 60 days | 45 days |
| London Region SLA | Covered by 99.9% | Confirm explicitly | Agreed |
| Renewal price cap | 5% | 3% | 5% |

Acme needs the renewal signed by 30 November 2026, so that an in-force agreement exists for the ISO 27001 recertification audit in February 2027 and so that Acme can offer Halvorsen Logistics the improved availability commitment it has requested. If agreement cannot be reached, Acme's fallback is a six-month extension of the current terms while the exit plan is executed.

## Schedule I — Data Processing Terms (Full)

### I.1 Subject Matter and Duration

Cobalt processes Customer Data to provide the hosting services for the duration of the Agreement and the exit period, plus the 30-day deletion period in clause 9.3.

### I.2 Nature and Purpose

Processing consists of storing, replicating (where Acme configures it), backing up and restoring Customer Data, and operating the infrastructure that Acme's applications run on. Cobalt does not access the content of Customer Data except where necessary to provide support requested by Acme, and then only with Acme's approval in the support ticket.

### I.3 Categories of Data and Data Subjects

Customer Data may include personal data of Acme's clients' employees and contractors (such as names, work email addresses and driver identifiers in logistics telemetry processed by Atlas) and, in the London Region only, health data of patients of Brightwater Health Trust. Health data is special category data and is subject to the residency terms in clause 3.3.

### I.4 Cobalt's Obligations

Cobalt will: process Customer Data only on Acme's documented instructions; ensure its personnel are bound by confidentiality; implement the security measures in clause 8 and Schedule J; not engage new subprocessors without 30 days' notice; assist Acme with data subject requests and data protection impact assessments, including the assessment Brightwater Health Trust carried out for its migration; notify Security Incidents within 24 hours; delete or return Customer Data at the end of the Agreement; and make available information needed to demonstrate compliance.

### I.5 International Transfers

Cobalt does not transfer Customer Data outside the Region in which Acme stores it. Support staff outside the European Union may access infrastructure metadata, but not Customer Data, under the standard contractual clauses attached to the Agreement.

## Schedule J — Technical and Organisational Security Measures

| Area | Measure |
|---|---|
| Physical security | Data centres with 24x7 guards, biometric access and video monitoring |
| Encryption | AES-256 at rest with customer-managed keys; TLS 1.2+ in transit |
| Access control | Named administrators, multi-factor authentication, just-in-time access approvals |
| Logging | Infrastructure audit logs kept 12 months; available to Acme on request |
| Vulnerability management | Critical vulnerabilities patched within 7 days; monthly scanning |
| Resilience | Three availability zones per Region; customer chooses single- or multi-zone placement |
| Incident response | 24x7 security operations centre; notification to customers within 24 hours |
| Personnel | Background checks and annual security training |

## Schedule K — Monthly Regional Fees, 2026

| Month | Frankfurt | Dubai | London | Total invoiced | Notes |
|---|---|---|---|---|---|
| January | EUR 16,200 | EUR 4,150 | EUR 1,100 | EUR 22,000 (Committed Spend applied) | London build started |
| March | EUR 16,500 | EUR 4,200 | EUR 1,900 | EUR 22,600 | Frankfurt outage on 14 March |
| June | EUR 16,600 | EUR 4,200 | EUR 2,600 | EUR 23,400 | |
| July | EUR 16,700 | EUR 4,250 | EUR 2,650 | EUR 21,950 after EUR 1,650 credit (EUR 23,600 before) | March Service Credit applied |
| August | EUR 16,400 | EUR 4,200 | EUR 2,500 | EUR 23,100 | |

The London Region fees relate to the Brightwater Health Trust workloads. Under the Brightwater SOW, London hosting costs up to GBP 3,000 per month are included in Acme's fixed fee until 15 December 2026.

## Schedule L — Questions Answered for Acme's Finance and Platform Teams

**Who can raise a Priority 1 ticket?** Any named Acme platform contact, including the on-call engineer. Quote CC-ENT-4471 and phone the support line.

**How long do we have to claim a Service Credit?** 30 days from the end of the Incident (clause 6.3). Finance needs the Cobalt incident reference and the outage times on the day of the Incident.

**What if we use less than EUR 22,000 in a month?** Cobalt invoices the Committed Spend of EUR 22,000 anyway (clause 5.1).

**Is London covered by the 99.9% commitment?** Yes; clause 6.1 applies to every Region Acme uses, although the renewal term sheet asks Cobalt to confirm this explicitly.

**What happens on 1 January 2027 if no renewal is signed?** The Agreement ends on 31 December 2026, and the 60-day exit period in clause 13 begins. Atlas, the Brightwater workloads and Acme's ISO 27001 recertification would all be at risk, which is why the renewal must be signed by 30 November 2026.
