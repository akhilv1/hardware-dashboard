# ChassisDeck releases and updates

Deploy a specific tag from [GitHub Releases](https://github.com/akhilv1/hardware-dashboard/releases).
The bundle contains application code, static assets and host collectors. It does
not contain telemetry, credentials, host configuration or the neofand fan daemon.
It updates the app inside existing Docker or LXC deployments; it is not a Docker
base-image upgrade or a new LXC root filesystem.

## Download and verify

```sh
release_tag=v0.1.0
gh release download "$release_tag" --repo akhilv1/hardware-dashboard \
  --pattern "chassisdeck-$release_tag.tar.gz" --pattern SHA256SUMS
sha256sum -c SHA256SUMS
tar -xzf "chassisdeck-$release_tag.tar.gz"
cd "chassisdeck-$release_tag"
```

Download from the expected repository over HTTPS. Checksums detect corruption;
they are not independent cryptographic signatures. Review the release notes
and retain the previous bundle. Updates are explicit, not unattended.

## Installation profiles

| Profile | Existing destination | Installs |
|---|---|---|
| `macpro` | Dashboard Compose bind-mount directory | Mac UI, companion API, common host collectors |
| `p620` | Dashboard Compose bind-mount directory | Linux UI/API/collectors, P620 GPU builder default |
| `linux` | Dashboard Compose bind-mount directory | Linux UI/API/collectors, generic builder |
| `lxc` | `/opt/neofand` inside the LXC | `www/` static UI/assets and `linux_api.py` |
| `proxmox-host` | `/opt/neofand-host` on the physical host | Linux/events/storage/SMART/Proxmox collectors and exporter |

Keep existing service names, file paths, UID/GID, Compose configuration, API
bindings, private ingress, telemetry mounts and host data directories. This
installer deliberately does not alter them. The Mac Pro native fan-control
service is a separate project and must not be stopped for dashboard updates.

Before installing, stop only the affected dashboard/API containers or LXC
services. Stop the matching collector service/timers when replacing host code.
Do not stop unrelated workloads. Containers using individual file bind mounts
must be stopped and started after replacement so they remount the new files.

Example for an existing P620 deployment (adjust paths/account to your install):

```sh
python3 install-release.py --profile p620 \
  --destination /home/neo/services/neofand-dashboard \
  --backup-root /home/neo/services/chassisdeck-backups
```

Run with the account that owns the deployment; use root for root-owned LXC and
Proxmox host directories. The destination must exist. The installer verifies
the selected payload hashes, refuses symlink targets and records changed-file
backups outside the deployment. It never deletes telemetry or scans it into
backups. A `.chassisdeck-release.json` pin records the repository, tag, source
commit, installed file hashes, installation profile and rollback directory.
Subsequent upgrades refuse changed release files so local work is not silently
overwritten. Reconcile modifications with source before updating.

Restart the same services after installation. Verify the footer's release and
commit, live sample timestamps, health endpoints, storage/event data and any
platform-specific pages. Check the Proxmox host and LXC separately. A new tag
does not prove live collectors are healthy or erase earlier telemetry gaps.

## Rollback

Stop the same affected services, then use the backup path printed by installation:

```sh
python3 install-release.py --restore /path/to/chassisdeck-backups/v0.1.0-EXAMPLE \
  --destination /path/to/deployment
```

The restore checks backup hashes and refuses files modified since deployment.
It restores previous code and release metadata, removes only files that this
installation newly added, and leaves telemetry/configuration untouched. Restart
and validate the services. Keep backups until the release has been verified.

## Maintainer build

From a clean checkout at the release source commit:

```sh
bash tools/check.sh
python3 tools/build-release.py v0.1.0 /tmp/chassisdeck-dist
```

Tag that exact commit and publish the generated archive, `SHA256SUMS` and
`release.json`. Do not retarget a published tag or silently replace release
assets. Publish a new version for changes. The footer links to the ChassisDeck
release and commit; legacy build metadata continues to link to neofand.

## Automatic updates

The optional [Updates page and host agent](UPDATES.md) can install future stable
releases after administrator opt-in. First installation and changes to deployment
configuration remain explicit host-administrator tasks.
