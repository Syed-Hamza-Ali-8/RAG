# Ledger Vault Platform Architecture

## Overview

Ledger Vault is Globex's secure client document portal. Clients upload trial balances, contracts and audit evidence, and audit teams link those files to working papers in Fernbook. The technical owner is Kwame Mensah, Head of IT.

## Hosting

Ledger Vault is hosted on Tessera Cloud under agreement TC-7720. The primary region is Bahrain and the disaster recovery region is Frankfurt. UK client files are stored in a separate storage bucket in Tessera Cloud's London region.

## Components

- A web application behind a web application firewall.
- Object storage for uploaded files, with versioning enabled.
- A PostgreSQL database for metadata, backed up nightly.
- Microsoft Entra ID for staff single sign-on; clients use email one-time passcodes.

## Integrations

Fernbook, the audit working-paper platform, links to Ledger Vault files through an API connector maintained by the IT team.

## Availability

Ledger Vault targets 99.9% availability, with an RPO of 24 hours and an RTO of 4 hours.
