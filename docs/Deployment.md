# Deployment

<!-- Update this whenever deployment process, environments, or rollback procedure change, in the same change. -->

## Environments

<!-- e.g. local, staging, production - what differs between them (config, data, scale). -->

### <!-- Environment name -->

- URL: <!-- ... -->
- Purpose: <!-- ... -->
- How it's provisioned: <!-- ... -->

## Deployment Process

<!-- Step-by-step: how a change gets from merged code to running in each environment. Include the trigger (manual, CI on merge, tag, etc.) and any approval gates. -->

1. <!-- ... -->

## Configuration & Secrets

<!-- Where config/secrets live per environment, and how they're set/rotated. Never put actual secret values in this file. -->

## Rollback

<!-- How to detect a bad deploy and how to revert it, per environment. -->

## Monitoring & Alerts

<!-- Where to check that a deploy succeeded and the system is healthy: dashboards, logs, alerts. -->

## Known Limitations

<!-- e.g. no zero-downtime deploys yet, manual steps that aren't automated. -->
