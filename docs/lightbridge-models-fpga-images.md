# Lightbridge models and FPGA images

Inventory, 2026-10-31. Read-only research; no firmware downloaded or executed. Related: #165, `docs/lightbridge-fpga.md`.
Evidence: **V** source quoted/checked in bytes, **I** inferred, **U** unknown.
Local scan list (untracked, has hashes): `tmp/lb_models/local_fpga_modules.tsv`.

## Image catalogue (module id, marking, family)

Marking = version string in the xV4 entry (`AA.BB.CCDD`). Images are named by marking only; hashes stay in the awto-dji store.

| Module | Marking | Role | Family | Held locally | Packages seen (local scan) |
|---|---|---|---|---|---|
| m1900 | 01.00.2107 | air (P3 launch) | Cyclone V e50f-class (die byte 0x05) | yes | P3X/P3S 01.01.0006..0009 (2) |
| m1900 | 01.00.2144 | air (P3 / Inspire 1 / M100) | Cyclone V, same die as 2107 | yes | P3X/P3S 01.02..01.11, WM610 01.11.01.50, MATRICE100 01.03.01.00 |
| m1900 | 01.00.2322 | air, Lightbridge 2 (`LBTX_FW`) | Cyclone V, header prefix identical to the P3 air images (I) | yes, 6 packages, identical bytes | LBTX_FW 01.01.00 .. 01.01.0041 |
| m2000 | 01.00.2107 | ground, GL300 | Cyclone V die 0x13 | yes | 20 packages |
| m2000 | 01.00.2321 / 01.00.2322 | ground, LB2-era | Cyclone V die 0x13 | yes | C1_FW 01.00.0004 / 01.00.0010 |
| m2001 | 01.01.2107 | ground | **Cyclone IV GX** (best match EP4CGX150) | yes | 20 packages, one image only |
| m2002 | 01.02.2107 / 01.02.2109 | ground, GL300 rev 2 | Cyclone V die 0x13 | yes (both) | 2107 in P3X 01.02.0006 only; 2109 in 15 packages |
| m2003 | 01.00.2322 | ground, Lightbridge 2 | Cyclone V die 0x13; bytes equal m2000 2322 | yes, 17 packages | C1_FW 01.01.0010 .. 01.01.0093 |

- Counts: 46 local package files carry an m19xx/m20xx module (awto-dji `firmware/raw` plus `sources/dji-fpga-images`); 9 distinct images.
- Distinct images (by content): m1900 x3, m2000 x3 (2107, 2321, 2322), m2001 x1, m2002 x2 = 9; m2003 adds none (equals m2000 2322).
- The o-gs wiki lists exactly these markings per module (m1900: 2107/2144/2322; m2000: 2107/2321/2322; m2001: 2107; m2002: 2107/2109; m2003: 2322). V (wiki `Firmware-m1900/2000/2001/2002/2003`). Every publicly catalogued FPGA image is already held.
- `sources/dji-fpga-images/PROVENANCE.md` still lists m2003 as "not found": stale. m2003 is in `firmware/raw/C1/C1_FW_V01.01.*` (awto-dji).
- Device detection from the image header: `scripts/cycloneiv_decompress.py` accepts m2001 only (valid 0x6a sync + header CRC); on the m1900/m2000/m2002/m2003 images it refuses ("no 0x6a sync"). Those start with the Cyclone V `afa6a6a6` preamble; air images share a prefix, ground images share another (die 0x13). Die byte per `docs/lightbridge-fpga.md` / awto-dji `fpga-images.md`.
- Wiki board text: air Cyclone V `5CEFA4U19I7` (P3 OFDM board P01007.06, LB2 air P00929.03); GL300 P01024.07 / P01298.01 `5CEFA4U19I7` + serial flash. V.

## Models and links

Board codes from the o-gs wiki (`DJI-Hardware`, board pages). Artosyn = AR8001/AR8003 ASIC replacing the FPGA, no image.

| Model | Link generation (evidence) | Air board / ground board | FPGA family, modules | Package versions (known) | Held | Source |
|---|---|---|---|---|---|---|
| Lightbridge (IG800, retail) | Lightbridge 1 (V) | IG800_ABP.V1 air, IG800_GPS_V1 ground (DM368) | air: "Altera Cyclone" family unnamed; no FPGA image in any package | ground controller fw 1.4.8 only | no air FPGA image; ground fw yes, no FPGA | wiki IG800 pages; awto-dji `sources/lightbridge-ig800-firmware/PROVENANCE.md` (DJI hosts no fw) |
| Phantom 3 Professional (WM, P3X) | Lightbridge 1 (V) | P01007.06/.08 FPGA, P01007.14 Artosyn / GL300A/B/C | Cyclone V air (m1900); ground m2000, m2001, m2002 | P3X_FW 01.01.0006 .. 01.11.0020 | yes | wiki P3X-OFDM-Receiver-board; `Firmware-m1900` |
| Phantom 3 Advanced (P3S) | Lightbridge 1 (V) | same boards | same modules | P3S_FW 01.01.0008 .. 01.11.0020 | yes | wiki `Firmware-m1900` package list |
| Phantom 3 Standard / SE / 4K | Wi-Fi, not Lightbridge (V) | P3C radio receiver, GL358 | none (no m19xx/m20xx) | P3C 01.08.0100/01.09.0200, P3SE 01.01.0000, P3XW 01.00.0010 | scanned, no FPGA | local module scan; wiki |
| Inspire 1 / 1 Pro / Raw (WM610) | Lightbridge 1 (V) | air = P3-type OFDM board (m1900 in WM610_FW); ground GL658A/B/C, board WM610_GRCP_MAIN_V3/V4 | air Cyclone V; GL658 board marking `EF4CGXF27AF` = **Cyclone IV GX** (V, wiki); Inspire RC package C1_FW 01.03.00.21 carries m2000+m2001 only, no m2002 (V) | WM610_FW 01.11.01.50 local; C1_FW 01.03.00.21 | yes | wiki GL658-Main-board; local scan |
| Matrice 100 | Lightbridge 1 (I: module m1900 inside MATRICE100_FW; wiki lists m0900 only) | M100 N1 encoder P00303.02 + OFDM board | Cyclone V air, same image as P3 2144 | MATRICE100_FW 01.03.01.00 | yes | local scan |
| Lightbridge 2 (IG810) | Lightbridge 2 (V) | air P00929.03 (5CEFA4U19I7N, LPC1549); ground GL858A/GL658C-class, board P01024.07 | air m1900 2322 (Cyclone V); ground m2003 | LBTX_FW 01.01.00..0041; C1_FW 01.01.0010..0093; `LB2_GND` package not found | yes (all above) | wiki IG810; o-gs issue #435 ("C1: m1300 m1400 m1600 m1601 m2000 m2001 m2002" vs "LB2: m0605 m1300 m1301 m1400 m1600 m2003") |
| Matrice 600 / 600 Pro | Lightbridge 2 (V for Pro, secondary source heliguy: "Matrice 600 Pro"); plain M600 I | A3 FC, separate LB2 air unit | LB2 air unit image = m1900 2322 (I, same unit) | MATRICE600_FW 01.00.00.28, 600PRO 01.00.00.80 (no FPGA module) | packages yes, no FPGA | heliguy transmission-systems article; local scan |
| Matrice 200 series, Inspire 2 | Lightbridge 2 (V, heliguy: "Inspire 2, Matrice 200 Series and Matrice 600 Pro"); Cendence ground | WM620 (Inspire 2) etc.; Artosyn-class radio (U) | no FPGA module observed (U) | I2 `dji_system.bin` 01.00.0240.. (public mirror) | no | heliguy; GitHub `kenhuyang/dji_system.bin` bins list |
| Phantom 4 Standard (WM330) | Lightbridge on Artosyn ASIC (V: wiki "Lightbridge ... Phantom 4 Std") | WM330 3-in-1 board (AR8001+AR8003+STM32F103) / GL300C, GL300E | none (ASIC) | P4 `dji_system.bin` 01.02.0503.. (public mirrors) | no | wiki WM330-Receiver-Main-Processor-3-in-1, TP703 page |
| Phantom 4 Advanced / Pro / Pro+ | Lightbridge (V, heliguy: "Phantom 4 Pro and Phantom 4 Advanced"); P4 Pro V2.0 is OcuSync (V) | WM331 3-in-1 | none (ASIC) | P4P 01.01.0203.., P4A 00.00.0118.. (mirror) | no | heliguy; `kenhuyang/dji_system.bin` |
| Mavic Pro | OcuSync 1 (V: heliguy "early iterations on the Mavic Pro") | WM220, RC GL200 | none | Mavic `dji_system.bin` (mirror) | no | heliguy |
| Spark | Wi-Fi (V: heliguy) | - | none | - | no | heliguy |
| HDMI/SDI modules, Cendence, CrystalSky, Ronin, Zenmuse X5 | Cendence = LB2 ground / controller (V, heliguy); others not a Lightbridge FPGA host (U) | - | not examined | - | no | heliguy |

Notes on the table:
- "Phantom 3 Pro/Adv" and "Inspire 1" air images are byte-identical in the 2144 era (V, local).
- Names in the task not confirmed publicly: WM610 is Inspire 1 (V); WM220 is Mavic Pro (V); `TP703` is an RF protocols test board listing Lightbridge/Wi-Fi/OcuSync sectors, not a product (V, wiki TP703-RF-Protocols-board). "IG810 Air" = Lightbridge 2 air unit (V).

## Same design as m2001, or not

- m2001 is the only Cyclone IV GX image in any package; one marking (01.01.2107), identical in 20 packages. No older or newer m2001 exists in the public lists. Nothing to fetch for "another m2001".
- GL658 (Inspire 1 RC) board carries a Cyclone IV GX; m2001 is the likely image for it (I). Test: the Inspire 1 RC package has m2001 but not m2002.
- Likely same family as each other, different from m2001: m2000, m2002, m2003 (Cyclone V die 0x13); m2003 equals m2000 2322 byte for byte; m2000 2321/2322 header matches 2107 (V, awto-dji).
- Different design lines: air m1900 x3 (P3 launch vs P3 later vs LB2); of these 2144 vs 2322 are different images with the same header prefix (V).
- Artosyn-era boards (P3 OFDM v2 P01007.14, GL300 P01298.05, Phantom 4 line) have no FPGA image; wiki: ASIC "behaves in the same way as FPGA with m1900" (V).

## Where firmware is archived (listed only, nothing downloaded)

- DJI CDN: `dl.djicdn.com/downloads/lightbridge2/` (C1_FW 01.00.0004, 01.00.0010, 01.01.0000, 01.01.0030, 01.06.0000); `.../phantom_3*/`, `.../inspire_1/`, `.../dev/Matrice/` (V, awto-dji MANIFEST and PROVENANCE, live 2026-10-28).
- Test bucket paths recorded in awto-dji MANIFEST: `s3-ap-northeast-1.amazonaws.com/dji-firmware-test/LB2/` and `/RC_TEST/` (LBTX_FW, C1_FW 01.01.x, 01.05-01.09); listing not retried.
- Wayback Machine: `download.dji-innovations.com/downloads/phantom_3/en/` (P3 Pro 1.1.8, 1.1.9, 1.2.6 fetched; P3 Advanced 1.1.8/1.1.9/1.2.8/1.3.20/1.4.0010 and P3 Standard 1.1.0030 listed, not fetched).
- GitHub `samd12/dji_system.bin`, `kenhuyang/dji_system.bin` (P4, P4P, P4A, Inspire 2, Spark, Mavic, OcuSync unit; Linux `dji_system.bin` images, no m19xx/m20xx entries seen in names), `njdro/dji_P4_firmware_archive`, `digdat0/P3I1_FWProject` (modified P3/I1 packages; derivative, not stock).
- DankDroneDownloader (`cs2000`): closed Windows/web service listing Inspire 1/Pro, Matrice 200/600/600 Pro, Phantom 3/4 firmware; README only, API not used.
- `o-gs/dji-firmware-tools` wiki: version tables per module (the main index above). Blocked/skipped: firmwareupdatepro.com (spam page, no content); GitHub wiki HTML pages load but chrome-heavy, raw wiki markdown used instead.

## Recommended next fetches (max 5, ordered)

Coverage of public markings is complete, so gain is low and mostly outside firmware packages.
1. **`LB2_GND` standalone package** (m0605/m1300/m1301/m1400/m1600/m2003 per #435): not located; try Wayback of `dl.djicdn.com/downloads/lightbridge2/` and the `dji-firmware-test/LB2/` bucket. Check: m2003 marking and whether bytes equal the held m2003 (C1_FW 01.01.x). If different, a new Cyclone V ground design.
2. **Original `LBTX_FW` siblings** (any LB2 air package outside the six held): check m1900 marking is 2322 and bytes equal; confirms a single LB2 air image.
3. **Inspire 1 stock WM610_FW older packages** (pre-01.11): check m1900 marking (2107 vs 2144) and whether any Inspire-only air image exists (wiki lists only three markings, so expected none).
4. **P3 Advanced early zips from Wayback** (1.1.8 held locally; 1.2.8, 1.4.0010 not): only to close the m2002 2107 vs 2109 boundary for the P3S line; low value.
5. **Not a fetch, a measurement**: GL658C/GL858A or LB2 ground board photo/JTAG to confirm the Cyclone IV marking against m2001 (wiki gives `EF4CGXF27AF`, not the density). Settles the m2001 die and which RC carries it.

## Unknowns

- U: IG800 (Lightbridge 1 retail) air FPGA image and family; not in any published package.
- U: Inspire 2 / M200 air radio chips (ASIC vs FPGA); no FPGA module seen in the mirror names.
- U: whether m2003 differs from m2000 2322 in any shipped LB2_GND package.
- U: density of the GL658 Cyclone IV GX (wiki marking truncated).
- I: m2001 is the GL658 (Inspire 1 RC) image.
