# sources/ — downloaded third-party tool installers and reference docs

Gitignored (see `.gitignore`, `sources/*` with `sources/README.md` re-included). Not
project source — vendor installers/docs this repo depends on but doesn't vendor.
Re-fetch and verify by hash per entry below.

## Altera / Intel FPGA tooling

Oracle toolchain for the Cyclone V lifter work (Mistral cross-check, device-db
validation) — see `CLAUDE.md` device-db section, `scripts/cyclonev_die_probe.py`, and
awto-au/awto-dji#3 (the air Lightbridge FPGA die-ID investigation this was built for).

Installed at `/mnt/2tb/opt/altera/quartus-25.1` (outside the repo — large, ~24 GB).

| File | SHA1 | Size | Source |
|---|---|---|---|
| `altera/qinst-lite-linux-25.1std-1129.run` | `6738aa50c698b894402cf516b10e4c89f5a50fdf` | 121 MB | [Quartus Prime Lite 25.1 Linux](https://www.altera.com/downloads/fpga-development-tools/quartus-prime-lite-edition-design-software-version-25-1-linux) — "Quartus Prime Lite Edition Installer (SFX)" |
| `altera/cyclonev-25.1std.0.1129.qdz` | `a7225ec1bd36ccfd6826ea6273df5d21dd95633b` | 1.4 GB | same page — "Cyclone V device support" |
| `altera/Cyclone_V_Device_Datasheet.pdf` | — | 1.1 MB | [docs.altera.com 683801](https://docs.altera.com/r/docs/683801/current/cyclone-v-device-datasheet/configuration-files) via Digi-Key mirror (the JS reader app doesn't render through automated fetch) |
| `altera/Cyclone_V_Device_Handbook_vol1.pdf` | — | 2.5 MB | [docs.altera.com 683375](https://docs.altera.com/r/docs/683375/current/cyclone-v-device-handbook-volume-1-device-interfaces-and-integration/configuration-data-compression), "Configuration Data Compression" section, via Digi-Key mirror |

Both installer files require an Altera account (SSO + email OTP) and a EULA
click-through per file — not scriptable without a signed-in session. Arria II and
Quartus Programmer download attempts hit `ERR_INVALID_RESPONSE` from
`download.altera.com` on 2026-10-23; not retried since neither is needed for Cyclone V
work. Retry from the same download page if wanted later.

Install (what was actually run): extract the SFX, then run its embedded `qinst` CLI
pointed at `sources/altera/` as the download dir so it reuses the pre-fetched
`.qdz` instead of re-downloading:
```
chmod +x altera/qinst-lite-linux-25.1std-1129.run
./altera/qinst-lite-linux-25.1std-1129.run --nox11 -- --cli \
  --download-dir sources/altera --install-dir /mnt/2tb/opt/altera/quartus-25.1 \
  --components quartus,cyclonev --accept-eula --auto-install
```

The Cyclone V config-data compression scheme is **not** documented in either PDF (the
handbook section only covers the Quartus GUI toggle) — Mistral's own decompressor
(`libmistral/cv-files.cc` `rbf_load()`) is the actual spec, reverse engineered by its
maintainer, not published anywhere by Altera.
