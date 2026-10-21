# Statement of Work — Brightwater Health Trust Cloud Migration

## 1. Introduction

### 1.1 Parties

This Statement of Work ("SOW") is between Acme Advisory Group ("Acme") and Brightwater Health Trust, a UK healthcare provider running four community hospitals and twelve clinics in the north of England ("the Trust").

### 1.2 Framework

This SOW is issued under the framework services agreement signed by the parties on 14 November 2025. If this SOW conflicts with the framework agreement, the framework agreement prevails, except for the data residency terms in section 7, which prevail over any other term.

### 1.3 Signature

This SOW was signed on 22 April 2026 by Sara Qureshi, CEO, for Acme, and by Dr Helen Marsh, Chief Information Officer, for the Trust.

## 2. Objectives

The Trust wants to retire two ageing on-premises systems hosted in its own data centre, whose hardware support ends in March 2027:

- PatientFlow, the patient scheduling system used by all clinics and outpatient departments.
- TrustReports, the reporting system that produces operational and regulatory reports from PatientFlow and other sources.

The objectives are to migrate both systems to the cloud, keep all patient data in the United Kingdom, improve availability from the current 98.7% to at least 99.5%, and hand over a supportable platform to the Trust's own IT team.

## 3. Scope

### 3.1 In Scope

- Discovery and assessment of PatientFlow and TrustReports, including integrations and data flows.
- Design and build of a secure landing zone in Cobalt Cloud's London region.
- Migration of PatientFlow (database and application tier) and TrustReports (database, reporting engine and report schedules).
- Performance and security testing, including an independent penetration test.
- Cutover planning and execution, with rollback plans for each system.
- Handover, knowledge transfer and 30 days of hypercare after the final cutover.

### 3.2 Out of Scope

- Changes to PatientFlow or TrustReports functionality.
- Migration of the Trust's electronic patient record, which remains on premises.
- Ongoing managed services after hypercare, which may be agreed in a separate SOW.
- Licences for PatientFlow and TrustReports, which the Trust holds directly with the software vendors.

## 4. Term and Timetable

### 4.1 Term

This SOW runs from 1 May 2026 to 15 December 2026.

### 4.2 Phases

| Phase | Dates | Main activities |
|---|---|---|
| Discovery | 1 May – 12 June 2026 | System inventory, data flow mapping, data protection impact assessment, target design |
| Landing zone | 15 June – 31 July 2026 | London-region landing zone, networking, identity, logging, backup |
| First migration | 3 August – 28 August 2026 | Migrate TrustReports, test, cut over |
| Second migration | 31 August – 23 October 2026 | Migrate PatientFlow, test, cut over |
| Handover and hypercare | 26 October – 15 December 2026 | Knowledge transfer, documentation, 30 days of hypercare |

### 4.3 Status

As of the October 2026 steering committee, Discovery, Landing zone and First migration are complete and accepted. The PatientFlow migration was cut over on 17 October 2026 and is in its acceptance period.

## 5. Deliverables and Acceptance

### 5.1 Deliverables

| ID | Deliverable | Phase |
|---|---|---|
| D1 | Discovery report and target architecture | Discovery |
| D2 | Data protection impact assessment (DPIA) support pack | Discovery |
| D3 | Landing zone built and documented | Landing zone |
| D4 | TrustReports migrated and live | First migration |
| D5 | PatientFlow migrated and live | Second migration |
| D6 | Operations manual, runbooks and training | Handover |
| D7 | Hypercare completion report | Handover |

### 5.2 Acceptance

The Trust has ten business days after a deliverable is submitted to accept it or to give written reasons for rejection. If the Trust does not respond in that time, the deliverable is treated as accepted. Acme will correct rejected deliverables and resubmit them within ten business days.

### 5.3 Acceptance Criteria for Migrations

A migrated system is accepted when: all agreed test cases pass; performance is equal to or better than the on-premises baseline for the ten busiest transactions; no Severity 1 or Severity 2 defects remain open; and the system has run in production for ten business days without a Severity 1 incident.

## 6. Fees and Payment

### 6.1 Fixed Fee

The total fixed fee is GBP 410,000, excluding VAT, payable on milestones:

| Milestone | Amount | Due |
|---|---|---|
| 1. Discovery complete (D1, D2 accepted) | GBP 80,000 | June 2026 |
| 2. Landing zone and first system migrated (D3, D4 accepted) | GBP 120,000 | August 2026 |
| 3. Second system migrated (D5 accepted) | GBP 130,000 | October 2026 |
| 4. Handover and hypercare complete (D6, D7 accepted) | GBP 80,000 | December 2026 |

### 6.2 Invoicing

Acme invoices each milestone from Ledgerline after the related deliverables are accepted. Invoices are payable within 30 days.

### 6.3 Cloud Hosting Costs

Cobalt Cloud hosting costs for the London region during the SOW term are included in the fixed fee up to GBP 3,000 per month. Hosting costs above that amount, and all hosting costs after 15 December 2026, are payable by the Trust under a separate agreement to be signed before handover.

### 6.4 Expenses

Travel to Trust sites is included in the fixed fee.

## 7. Data Residency and Protection

### 7.1 Residency Requirement

All patient data, including backups, logs that contain patient identifiers and test copies, must remain in the United Kingdom. All Trust workloads run in Cobalt Cloud's London region only and must not be replicated to Frankfurt, Dubai or any other region. This requirement follows UK GDPR and the Trust's data security policy and overrides any other term.

### 7.2 Separation from Other Workloads

The Trust's workloads run in a dedicated Cobalt Cloud account, separate from the Atlas platform. No Trust data may be loaded into Atlas.

### 7.3 Test Data

Testing uses anonymised data generated by the Trust's information governance team. Real patient data is used only in production and in the final rehearsal of each cutover, inside the London region.

### 7.4 Roles and Subprocessors

The Trust is the controller and Acme is a processor. Cobalt Cloud GmbH acts as Acme's subprocessor for hosting, under Acme's enterprise agreement CC-ENT-4471. Acme will not engage any other subprocessor with access to Trust data without the Trust's prior written consent.

### 7.5 Breach Notification

Acme will notify the Trust's Data Protection Officer of any personal data breach within 24 hours of becoming aware of it.

### 7.6 Hosting Contract Dependency

Acme's agreement with Cobalt Cloud expires on 31 December 2026, after this SOW ends. Before handover, the parties will agree whether the Trust contracts with Cobalt Cloud directly or continues under a managed service from Acme.

## 8. Team and Key Personnel

### 8.1 Acme Team

| Role | Name |
|---|---|
| Engagement lead | Mei Lin Zhou |
| Delivery manager | Hassan Raza |
| Lead cloud architect | Daniyal Sheikh |
| Database migration lead | Ayesha Malik |
| Security lead | Oliver Grant (London office) |

### 8.2 Trust Team

| Role | Name |
|---|---|
| Executive sponsor | Dr Helen Marsh, CIO |
| Project manager | Rachel Okonjo |
| Information governance lead | Tom Barker |
| Data Protection Officer | Sunita Patel |

### 8.3 Replacing Key Personnel

The engagement lead, delivery manager and lead cloud architect are key personnel. Acme will not replace them without the Trust's written consent, except for illness or resignation, and will give at least ten business days of handover to any replacement.

## 9. Governance

### 9.1 Meetings

A weekly status meeting is held between the delivery manager and the Trust's project manager. A monthly steering committee, chaired by Dr Helen Marsh, reviews progress, risks and change requests.

### 9.2 Reporting

Acme provides a written weekly status report covering progress against plan, risks and issues, decisions needed, and hosting spend in the London region.

## 10. Risks and Assumptions

### 10.1 Key Risks

| Risk | Mitigation |
|---|---|
| PatientFlow vendor support needed for the database upgrade is slow | Trust to raise a priority support contract with the vendor before August 2026 |
| Clinic downtime during PatientFlow cutover | Cut over over a weekend with a tested rollback plan |
| Hosting provider outage | Multi-zone deployment within the London region; no cross-region failover allowed because of residency |
| Hosting agreement expires shortly after the SOW | Decide hosting contract route before handover (section 7.6) |

### 10.2 Assumptions

The Trust provides access to its data centre and systems within five business days of request; the Trust's network team configures the private connection to Cobalt's London region by 10 July 2026; and the Trust's information governance team supplies anonymised test data for each system before testing starts.

## 11. Change Control

Changes to scope, timetable or fees follow the change control procedure in the framework agreement. Acme will provide an impact assessment within five business days of a change request. No change is binding until signed by both parties.

## 12. Hypercare

For 30 days after the final cutover, Acme will provide hypercare: a named engineer available during Trust business hours, a response to Severity 1 issues within 30 minutes at any time, and a daily check-in with the Trust's IT team. Hypercare ends with the hypercare completion report (D7).

## 13. Testing Approach

### 13.1 Test Stages

Each migration passes through four test stages: functional testing of every agreed test case; integration testing of all interfaces with other Trust systems; performance testing of the ten busiest transactions against the on-premises baseline; and a full cutover rehearsal using production-sized data inside the London region.

### 13.2 Security Testing

Before the PatientFlow cutover, an independent penetration test of the London landing zone and both migrated systems is carried out by a CREST-accredited tester chosen by the Trust. Critical and high findings must be fixed before go-live; medium findings must have an agreed remediation date.

### 13.3 Defect Severity

| Severity | Definition | Fix target during testing |
|---|---|---|
| 1 | System unusable or patient safety risk | Before cutover, no exceptions |
| 2 | Major function broken with no workaround | Before cutover |
| 3 | Function broken with a workaround | Within 20 business days of cutover |
| 4 | Cosmetic | Backlog |

## 14. Cutover Plans

### 14.1 TrustReports Cutover (Completed)

TrustReports was cut over on Saturday 22 August 2026. The on-premises system was set to read-only at 18:00 on Friday, the final data sync ran overnight, and reports were validated by the Trust's information team on Saturday morning. The rollback point was 12:00 on Saturday; it was not needed. TrustReports was accepted on 8 September 2026.

### 14.2 PatientFlow Cutover (Completed)

PatientFlow was cut over over the weekend of 17 and 18 October 2026, when clinics are closed. Clinic staff used printed schedules for Monday morning as a precaution. The rollback window closed at 20:00 on Sunday 18 October. Acceptance is expected by early November 2026, after ten business days without a Severity 1 incident.

## 15. Responsibilities (RACI Summary)

| Activity | Acme | Trust |
|---|---|---|
| Target architecture | Responsible, accountable | Consulted |
| DPIA | Consulted (support pack) | Responsible, accountable |
| Landing zone build | Responsible, accountable | Informed |
| Private network connection | Consulted | Responsible, accountable |
| Anonymised test data | Informed | Responsible, accountable |
| Migration and cutover | Responsible | Accountable (go/no-go decision) |
| User acceptance testing | Consulted | Responsible, accountable |

## 16. Knowledge Transfer and Training

Acme will run six knowledge transfer sessions for the Trust's IT team covering the landing zone, monitoring, backup and restore, patching, cost management and incident response. Each session is recorded. The Trust's engineers will shadow Acme engineers during the PatientFlow cutover and lead a supervised backup restore test during hypercare.

## 17. Communications

Acme and the Trust's project manager agree a communications plan for each cutover, including notices to clinic managers two weeks and two days before cutover, a helpdesk briefing, and a post-cutover message confirming success or any workarounds.

## 18. Handover Criteria

Handover is complete when: the operations manual and runbooks (D6) have been accepted; the Trust's IT team has completed all six knowledge transfer sessions and led a supervised restore test; monitoring alerts for both systems route to the Trust's own on-call rota; and the hosting contract route for the London region after 15 December 2026 has been agreed and signed. Acme will not release the final milestone invoice of GBP 80,000 until the Trust has signed the handover certificate.

## 19. Landing Zone Design (Deliverable D3 Summary)

### 19.1 Account Structure

The Trust's workloads run in a dedicated Cobalt Cloud account under Acme's enterprise agreement CC-ENT-4471, separate from the Atlas account. The account has three environments: production, pre-production and test. Only the production environment holds real patient data.

### 19.2 Network

A private connection links the Trust's data centre in Leeds to Cobalt's London region. Internet access for clinic users goes through a web application firewall. There is no network path from the Trust account to Frankfurt or Dubai.

### 19.3 Identity

Trust staff sign in through the Trust's own identity provider. Acme engineers access the Trust account only through a separate identity with hardware-key multi-factor authentication, and their access is logged and reviewed monthly with the Trust's security lead.

### 19.4 Backup

Databases are backed up every night and retained for 35 days, in a separate London-region storage account with immutable retention, so backups cannot be deleted by mistake or by an attacker. Restores are tested monthly.

### 19.5 Monitoring

Alerts are sent to Acme's on-call engineer during the SOW and to the Trust's IT on-call rota after handover.

## 20. Migration Approach by System

### 20.1 TrustReports

TrustReports was migrated with a lift-and-shift of its reporting engine and a database migration using native backup and restore. Report schedules were exported, re-created and compared output-for-output against the on-premises system for two weeks before cutover.

### 20.2 PatientFlow

PatientFlow required a database version upgrade, supported by the software vendor. The database was migrated with continuous replication from the on-premises database to London, so that the final cutover only needed a short replication catch-up. Interfaces to the Trust's electronic patient record, which stays on premises, now run over the private connection.

## 21. Status Report Extract — October 2026 Steering Committee

| Item | Status |
|---|---|
| Milestone 1 (Discovery) | Accepted 16 June 2026; invoiced and paid |
| Milestone 2 (Landing zone and TrustReports) | Accepted 8 September 2026; GBP 120,000 invoiced 30 August and paid 24 September |
| Milestone 3 (PatientFlow) | Cut over 17 to 18 October 2026; acceptance period running |
| Milestone 4 (Handover and hypercare) | Starts 26 October 2026 |
| Penetration test | Completed 2 October 2026; two high findings fixed before cutover; four medium findings scheduled |
| Hosting spend in London region | Average GBP 2,350 per month, within the GBP 3,000 included in the fee |
| Main open risk | Hosting contract route after 15 December 2026 not yet agreed |

## 22. Options for Hosting After Handover

The steering committee considered three options for hosting after the SOW ends:

1. **The Trust contracts directly with Cobalt Cloud.** The Trust would need its own agreement covering the London region, data processing terms and support. Cobalt has offered terms, but the Trust's procurement process may take three months.
2. **Acme provides a managed hosting service.** Acme would keep the Trust account under CC-ENT-4471 and charge a monthly managed service fee. This depends on Acme's renewal with Cobalt, which must be signed by 30 November 2026.
3. **Short-term bridge.** Acme continues hosting at cost for up to six months while the Trust completes its own procurement.

The committee chose option 3 as a bridge, with a decision between options 1 and 2 by March 2027. The bridge will be documented in a short change request to this SOW, and the Trust's Data Protection Officer has confirmed that the existing data processing terms continue to apply during the bridge period.

## 23. Lessons From the Atlas Outage Applied to This SOW

After Acme's March 2026 Atlas outage, the Trust asked how a similar hosting failure would affect PatientFlow. Because cross-region failover is not allowed under the data residency terms, the design uses three availability zones within the London region for the PatientFlow database and application tier, and the failover procedure between zones was tested in pre-production before cutover.

## 24. Acceptance Certificates Issued

| Deliverable | Submitted | Accepted | Signed by |
|---|---|---|---|
| D1 Discovery report and target architecture | 5 June 2026 | 16 June 2026 | Dr Helen Marsh |
| D2 DPIA support pack | 5 June 2026 | 16 June 2026 | Sunita Patel (DPO) |
| D3 Landing zone | 24 July 2026 | 3 August 2026 | Rachel Okonjo |
| D4 TrustReports migrated and live | 22 August 2026 | 8 September 2026 | Dr Helen Marsh |
| D5 PatientFlow migrated and live | 18 October 2026 | Pending (acceptance period running) | — |

## 25. Change Requests

| CR | Date | Summary | Impact |
|---|---|---|---|
| CR-01 | 2 July 2026 | Trust's private network connection delayed by two weeks | No fee change; landing zone acceptance moved from 31 July to 3 August |
| CR-02 | 14 September 2026 | Add a second PatientFlow cutover rehearsal at the Trust's request | GBP 6,500 additional fee, invoiced with milestone 3 |
| CR-03 (draft) | October 2026 | Bridge hosting for up to six months after 15 December 2026, at cost | To be agreed before handover |

## 26. Data Protection Impact Assessment Support

Acme's DPIA support pack (D2) described the data flows for PatientFlow and TrustReports, the location of every data store in the London region, the people with access, the security measures in the landing zone, and the residual risks. The Trust's DPIA, signed by its Data Protection Officer on 30 June 2026, concluded that the residual risk was acceptable on three conditions: no replication outside the UK; monthly access reviews of Acme engineers; and breach notification by Acme within 24 hours. All three conditions are reflected in sections 7 and 19 of this SOW.

## 27. Glossary

- PatientFlow: the Trust's patient scheduling system for clinics and outpatient departments.
- TrustReports: the Trust's operational and regulatory reporting system.
- Landing zone: the secure, pre-configured cloud environment into which systems are migrated.
- Hypercare: the 30-day period of enhanced support after the final cutover.
- CC-ENT-4471: Acme's enterprise agreement with Cobalt Cloud GmbH, under which the Trust's London-region account is provided.

## 28. Questions From the Trust's Board (September 2026)

**Could patient data end up outside the UK if Cobalt has an outage?** No. There is no replication or network path outside the London region. Resilience comes from three availability zones within London.

**Who is responsible for a data breach?** The Trust is the controller and Acme the processor. Acme must notify the Trust's Data Protection Officer within 24 hours, and Cobalt Cloud must notify Acme within 24 hours under Acme's enterprise agreement.

**What happens if Acme's agreement with Cobalt is not renewed?** Acme's agreement expires on 31 December 2026 and must be renewed by 30 November 2026 for Acme's own purposes. If it were not renewed, Cobalt's 60-day exit period would allow the Trust's workloads to be moved, but the bridge arrangement agreed by the steering committee assumes renewal.

**What does the Trust pay after 15 December 2026?** Under the bridge arrangement in draft CR-03, hosting at cost for up to six months, until the Trust decides between a direct contract with Cobalt and a managed service from Acme.
