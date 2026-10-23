# sources/ — downloaded third-party tool installers and reference docs

Gitignored (see `.gitignore`, `sources/*` with `sources/README.md` re-included). Not
project source — vendor installers/docs this repo depends on but doesn't vendor.
Re-fetch and verify by hash per entry below.

## Altera / Intel FPGA tooling

Oracle toolchain for the Cyclone V lifter work (Mistral cross-check, device-db
validation) — see `CLAUDE.md` device-db section and `scripts/cyclonev_die_probe.py`.

Installed at `/mnt/2tb/opt/altera/quartus-25.1` (outside the repo — large, ~24 GB).

| File | SHA1 | Size | Source |
|---|---|---|---|
| `altera/qinst-lite-linux-25.1std-1129.run` | `6738aa50c698b894402cf516b10e4c89f5a50fdf` | 121 MB | [Quartus Prime Lite 25.1 Linux](https://www.altera.com/downloads/fpga-development-tools/quartus-prime-lite-edition-design-software-version-25-1-linux) — "Quartus Prime Lite Edition Installer (SFX)" |
| `altera/cyclonev-25.1std.0.1129.qdz` | `a7225ec1bd36ccfd6826ea6273df5d21dd95633b` | 1.4 GB | same page — "Cyclone V device support" |
| `altera/Cyclone_V_Device_Datasheet.pdf` | — | 1.1 MB | [docs.altera.com 683801](https://docs.altera.com/r/docs/683801/current/cyclone-v-device-datasheet/configuration-files) via Digi-Key mirror (the JS reader app doesn't render through automated fetch) |
| `altera/Cyclone_IV_Device_Handbook_vol1.pdf` | `5dab2b718d3c28bbee51dd299385c17809e454c7` | 8.3 MB, 268 pages | Cyclone IV Device Handbook vol 1, CYIV-5V1-2.2 (May 2013), via [Waveshare mirror](https://files.waveshare.com/upload/7/7f/Cyiv-5v1.pdf). Good copy: contains "Table 8–2. Uncompressed Raw Binary File (.rbf) Sizes for Cyclone IV Devices" |
| `altera/cyclone-25.1std.0.1129.qdz` | `835d2b1732549294eed625b692d044135499b5e8` | 466 MB | same Quartus page — "Cyclone IV device support". Fetched 2026-10-24 (signed-in browser), sha1 verified. Installed with `scripts/quartus_device_install.py` (below) |
| `altera/AN556_design_security.pdf` | `4484fbbbcce5b50bed0983962b68893823837488` | 1.3 MB, 34 pages | [AN 556 rev 2.1 (June 2012)](https://docs.altera.com/r/docs/683269/current/an-556-using-the-design-security-features-in-altera-fpgas) via an EDN mirror PDF; covers Arria II / Stratix IV / Stratix V / Arria V / Cyclone V design security: AES-256, key modes, `KEY_VERIFY` bits. Header/option-bit layout of encrypted images is not in it. Good copy: 34 pages, contains "Table 9. Security Mode Verification for 28-nm FPGAs" |
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

Adding a device package to that install (Cyclone IV, 2026-10-24):
- `scripts/quartus_device_install.py --qdz-dir <dir holding only the .qdz> --component cyclone --family "Cyclone IV E" --family "Cyclone IV GX"`.
- It runs the install's own `quartus/common/devinfo/dev_install/dev_install.run` unattended.
- `--enable-components cyclone` is required. Without it the run exits 0 and installs nothing. The flag is not in `--help`.
- The installer unzips the `.qdz` into the install root. It adds only `quartus/common/devinfo/cycloneive/` and `cycloneivgx/`.
- Verify: `quartus_sh --tcl_eval get_family_list` -> `{Cyclone IV E} {Cyclone V} {Cyclone IV GX}`.

The Cyclone V config-data compression scheme is **not** documented in either PDF (the
handbook section only covers the Quartus GUI toggle) — Mistral's own decompressor
(`libmistral/cv-files.cc` `rbf_load()`) is the actual spec, reverse engineered by its
maintainer, not published anywhere by Altera.
