# Updates page and optional host updater

The **Updates** page shows the installed release, latest stable release, last
check, last automatic update and current result. Automatic updates start **off**.
An administrator unlocks the toggle with this host's key. The browser keeps only
a one-hour HttpOnly, SameSite=Strict session cookie; it does not save the key.
Use TLS or an authenticated private TLS proxy: HTTP on a trusted LAN does not
protect the key or session from an on-path observer.

The host checks `akhilv1/hardware-dashboard` hourly. Enabling automatic updates
also installs an already available newer stable release, usually within a minute.
The worker never downgrades or installs prereleases. The dashboard may briefly
disconnect. Application and collector files are backed up; failed health checks
restore the prior version. A repeated failure of the same release pauses retries
until an administrator reviews the journal and disables/re-enables the toggle.

Updates do not change telemetry data, host configuration, Compose manifests,
Caddy configuration, OS/container base images, unrelated workloads or the Mac Pro
fan daemon. Keep dependencies and the host OS patched separately.

## One-time host installation

Install only on the **physical host**, as its administrator, from reviewed source.
Python 3.9+, systemd and an existing release-pinned ChassisDeck deployment are
required. Docker deployments need the Docker CLI; Proxmox needs `pct`. Install
the first release manually using [RELEASES.md](RELEASES.md).

Create a root-owned JSON configuration, adapting the example to your deployment:

```json
{
  "host": "workstation",
  "targets": [{
    "profile": "p620",
    "destination": "/opt/hardware-dashboard",
    "backup_root": "/opt/chassisdeck/backups/app",
    "containers": ["neofand-dashboard-1", "neofand-telemetry-1"],
    "units": ["neofand-linux.service"],
    "start_units": ["neofand-linux.service"],
    "health_urls": ["http://127.0.0.1:4791/assets/build-info.json", "http://127.0.0.1:4791/api/latest"]
  }]
}
```

Include the deployment's collector services and timers in `units`; `start_units`
can start just the continuous sampler and timers, avoiding an immediate heavy
one-shot scan. Only list ChassisDeck services. Mac uses profile `macpro`, with
`neofand-dashboard-1` and `neofand-memory-1`; **never add `neofand.service`**.

For Proxmox, use two targets in order: `proxmox-host` at `/opt/neofand-host`,
then `lxc` at `/opt/neofand` with `ctid` set to the monitoring container's ID.
The latter uses `units: ["neofand-web.service", "neofand-api.service"]`, no
`containers`, and health URLs inside that LXC, including
`http://127.0.0.1:8080/hardware/assets/build-info.json` and
`http://127.0.0.1:4792/health`. Create `/opt/chassisdeck/releases` inside the LXC.
Host and LXC are rolled back together if a target fails.

```sh
sudo python3 dashboard/updater/install-updater.py \
  --config /root/chassisdeck-targets.json \
  --origin https://hardware.example.net
```

Origins must exactly match the browser's scheme, hostname and port, without a
path. The installer creates a dedicated unprivileged API account, root-owned
code/config, a root-only admin key, and a timer. Reinstallation preserves the key
and auto-update setting. Retrieve the key privately on the physical host:

```sh
sudo cat /etc/chassisdeck-updater/admin-token
```

Mount **only** `/var/lib/chassisdeck-update-api/run` read-only into the frontend
at `/run/chassisdeck-updates`. Docker: add this bind to the dashboard service's
`volumes`, then recreate only that service. Proxmox: add a read-only bind mount
using an unused `mpN`, then restart only the dashboard LXC if required. Never
mount the settings directory, key directory, Docker socket, or host root.

Current Caddy templates include the narrow `/api/updates` proxy to
`unix//run/chassisdeck-updates/control.sock`. Older deployments must add that
specific matcher before the generic GET-only API handler and validate/reload
Caddy. Without the optional host agent/socket, the page reports Unavailable.
Other API writes remain blocked.

## Security and recovery

The settings API is unprivileged, Unix-only, capability-free and filesystem
restricted. It accepts only a boolean preference and a rate-limited release
check request after exact-origin checking and admin authentication. Web clients
cannot choose repositories, commands, paths, services or download URLs.

The separate worker is **trusted root administrative code**, not a sandboxed
read-only collector. Enabling it trusts future code published by this repository
and its release administrators. It uses fixed GitHub HTTPS origins, canonical
asset URLs, size/time limits, SHA-256 verification and path-safe extraction.
Published checksums detect corruption; they are not independent signatures.
The same verified release updates the worker's Python code after app checks pass;
unit files and configuration changes still need explicit host administration.

Settings persist in `/var/lib/chassisdeck-update-api/settings.json`; status is
`/var/lib/chassisdeck-updates/status.json`. Back up these with the protected
`/etc/chassisdeck-updater` configuration. Do not include admin keys in public
support bundles. Settings take effect within a minute; disabling does not cancel
an installation already in progress.

Inspect `journalctl -u chassisdeck-update-worker.service` for detailed failures.
Release backups are retained under each configured `backup_root`; prune older
ones deliberately after verifying the current version. The worker requires at
least 1 GiB free at the destination and download cache before updating, and
removes temporary download/LXC staging files after use. A power interruption or
host/storage failure can require manual recovery; rollback is not an atomic OS
snapshot. Use the release installer's `--restore` with the current pin's backup
as described in RELEASES.md. Never bypass a modified-file refusal without review.

To stop all automatic work, disable the toggle, or run
`systemctl disable --now chassisdeck-update-worker.timer` on the host. The
dashboard and fan daemon continue to run independently.
