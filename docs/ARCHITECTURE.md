# Application and host boundary

| Component | Owner | Runtime responsibility |
|---|---|---|
| Dashboard, charts, chassis diagrams, GPU builder | hardware-dashboard | Static frontend |
| Read-only HTTP API and snapshot readers | hardware-dashboard | Unprivileged Docker/LXC services |
| Linux, storage, events, Docker and Proxmox collectors | hardware-dashboard | Host services; privileges scoped per collector |
| Mac Pro fan control, SMC decoding, telemetry writer and native API | neofand | Host systemd service |

The repositories are independently cloneable, testable and deployable. The app
does not compile or vendor Rust. Linux/P620 and Proxmox do not install neofand.
The daemon keeps its embedded diagnostic console because it is compiled into
the optional web feature; this is separate from the full application.

## Mac Pro API compatibility

The existing contract remains unchanged by the repository split. The known
baseline is neofand commit 98d1157f80cffacd59c8c86ae27a48350b322f12, built with
`--features web`; the split does not require upgrading an installed daemon.
There is currently no version-negotiation endpoint. A future incompatible API
change must introduce an explicit version/capability contract and a documented
compatibility window rather than silently requiring matching Git heads.

- `GET /api/metrics` discovers channels by subsystem, name and unit.
- `GET /api/latest` supplies timestamped readings.
- `GET /api/series?subsystem=&name=&from=&to=&step=` supplies history; names may
  be comma-separated and timestamps/ranges use Unix seconds.
- Native events, energy, service and boot views remain daemon-specific and
  optional. Linux/Proxmox expose only their supported views.
- The app's `/hardware/api/` proxy preserves these shapes and permits GET only.
  Extra host-memory/storage/events/Portainer routes are supplied by app readers.

Neither the application nor an independent collector may read raw SMC keys
while neofand runs. The SMC key-selection register is shared; only the daemon's
control thread may access it. Fan control must not depend on web availability.
Missing values remain unavailable; the frontend uses sample timestamps to flag
stale data rather than substituting zero or treating HTTP success as freshness.

See SECURITY.md for host privilege, data disclosure and ingress boundaries.
Docker socket access belongs only to a trusted host collector, never the web
container. Existing root Proxmox collectors remain trusted administrative code.

The optional [update agent](UPDATES.md) adds an authenticated settings-only Unix
socket and a separate trusted host release worker. This is the sole write
exception to the GET-only monitoring proxies; the web container still receives
no Docker socket, host shell, device access or root credentials.
