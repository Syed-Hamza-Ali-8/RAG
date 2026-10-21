# Postmortem: Phishing Incident, 19 August 2026

## Summary

On 19 August 2026, three staff mailboxes were compromised after a phishing email led to repeated multi-factor authentication (MFA) push requests that the users eventually approved, a technique known as MFA fatigue. Severity: Sev2. Incident commander: Kwame Mensah, Head of IT. Legal lead: Henrik Dahl, Legal Counsel.

## Impact

### Mailboxes

The attacker sent internal phishing emails from the three compromised mailboxes for about 40 minutes. 212 staff received at least one of these emails; 9 clicked the link, and none entered credentials, because the second-stage page was blocked by the web filter after the first report.

### Client Data

No client files in Ledger Vault were accessed: Ledger Vault requires a separate login from Microsoft 365 and the attacker never obtained Ledger Vault access. The compromised mailboxes did contain emails with client names and some routine correspondence. Henrik Dahl reviewed the mailbox contents and concluded that no personal data breach requiring client notification had occurred, because no confidential client documents were present in the mailboxes and there was no evidence that mail content was exported.

### Business

The three affected staff, all in the Abu Dhabi office, were unable to use email for most of the afternoon while their accounts were secured.

## Timeline (Gulf Standard Time)

- 13:02 Phishing email, posing as a Microsoft 365 storage warning, received by 41 staff in Abu Dhabi.
- 13:10 to 13:25 Three users enter their passwords on the phishing page. Each then receives repeated MFA push requests and approves one.
- 13:31 Attacker begins sending internal phishing emails from the compromised accounts.
- 13:48 A Manchester employee reports a suspicious internal email using the "Report phishing" button.
- 13:55 IT service desk confirms the compromise and blocks sign-ins for the three accounts.
- 14:11 Kwame Mensah declares a Sev2 incident; Henrik Dahl is notified, within the one-hour rule.
- 14:15 Web filter blocks the phishing domain for all staff.
- 15:30 Passwords reset, sessions revoked, mailbox rules created by the attacker removed.
- 17:00 Mailbox audit logs reviewed; no evidence of mail export.

## Root Cause

Staff accounts used simple push MFA, which lets a user approve a sign-in with one tap. Under repeated prompts, users approved a sign-in they had not started. The phishing email itself passed email filtering because it was sent from a newly registered domain with valid email authentication records.

## Contributing Factors

- No number matching in MFA prompts.
- No alert for repeated MFA denials followed by an approval.
- Phishing awareness training had last run in 2024.

## What Went Well

- A staff member reported the internal email within 17 minutes of the first internal send.
- The Legal Counsel was notified within the one-hour target.
- Ledger Vault's separate login protected client files.

## Action Items

| # | Action | Owner | Status |
|---|---|---|---|
| 1 | Enable MFA number matching for all staff in Microsoft Entra ID | IT team | Done 22 August 2026 |
| 2 | Run phishing awareness training for all staff by 30 September 2026 | HR and IT | Done; 97% completion |
| 3 | Notify the Legal Counsel of every suspected mailbox compromise within one hour | All staff (policy) | In place |
| 4 | Alert on repeated MFA denials followed by an approval | IT team | Done 5 September 2026 |
| 5 | Block sign-ins from newly registered domains' lookalike pages through the web filter | IT team | Done |

## Contract and Compliance Considerations

Globex's engagement letters, such as the Marlowe Retail Group letter, commit Globex to notify clients within 72 hours of a personal data breach affecting their data. Because the Legal Counsel concluded no client data breach occurred, no client notifications were sent. The incident and its review were added to the evidence pack for the ISO 27001 surveillance audit in March 2027, under incident management.

## Lessons

Separate authentication for Ledger Vault limited the damage. The IT team will keep Ledger Vault's login separate from Microsoft 365 for now, even though a single sign-on integration would be more convenient for staff.

## Follow-Up Metrics

| Measure | Before the incident | After |
|---|---|---|
| Staff with number-matching MFA | 0% | 100% (from 22 August 2026) |
| Phishing training completion | Last run in 2024 | 97% by 30 September 2026 |
| Simulated phishing click rate (October 2026 test) | 14% (2024 test) | 4% |
| Reports of suspicious emails per month | About 20 | About 75 |

## Related Documents

- Staff Handbook, section 8 (multi-factor authentication and phishing).
- Procurement policy, data protection section (12-hour incident notification target for vendors).
- ISO 27001 surveillance audit plan 2027 (incident management evidence).
- Ledger Vault Platform Architecture (separate login for Ledger Vault).
