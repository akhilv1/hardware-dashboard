# Hardware Dashboard

This repository owns the multiplatform monitoring UI, read-only APIs, host
collectors, GPU builder, and Docker/LXC packaging. Mac Pro fan control belongs
to https://github.com/akhilv1/neofand. Read SECURITY.md and docs/ARCHITECTURE.md
before modifying collectors or API boundaries.

Run `bash tools/check.sh`. Source stays under dashboard/ to preserve deployment
paths. Do not introduce raw SMC readers: only the daemon control thread may
access the shared raw SMC key register. Consume its published API instead.
Never mount Docker sockets or host devices into web/API containers. Host
collectors with Docker or root access remain trusted administrative code.
Missing readings must remain unavailable, not fabricated zeroes. Keep
`[hidden] { display: none !important; }` for grid-based tab panes.
