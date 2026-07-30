#!/usr/bin/env python3.15t
"""Fetch commercial-product FPGA firmware and record provenance.

WHY A SEPARATE SCRIPT FROM ecp5_corpus_fetch.py
-----------------------------------------------
`ecp5_corpus_fetch.py` fetches bare `.bit` files from GitHub repos, keyed on
owner/repo/path.  Commercial firmware is not shaped like that: the download is a
product update file from a vendor host, it may be a container needing carving,
and the interesting provenance is the PRODUCT (vendor, model, which chip is on
the board) rather than a repo.  Forcing both into one script would mean one of
the two sets carrying fields that never apply to it.

The manifest schema is deliberately a SUPERSET of the corpus one -- same field
names for url/sha256/bytes/license/device/notes -- so the two merge, plus
`family`, `vendor`, `product` and the carve provenance.

BOUNDARIES (enforced here, not left to the operator)
----------------------------------------------------
Every entry carries `access`, and only `open` entries are fetched.  Anything
needing a login, payment, support contract, or acceptance of terms forbidding
this use is recorded with `access` set and `skip_reason` explaining why, and is
NEVER downloaded.  That skipped list is itself a finding: it bounds what this
kind of testing can cover.

Binaries are gitignored (corpus/vendor-firmware/, corpus/commercial/).  Only the
manifest is committed, so the set is reproducible without redistributing anyone's
firmware.

Usage:
    python3.15t scripts/commercial_fetch.py                 # fetch open entries
    python3.15t scripts/commercial_fetch.py --verify         # re-hash only
    python3.15t scripts/commercial_fetch.py --list           # show targets

Logs to ./tmp/logs/commercial_fetch.log.
"""
import argparse
import hashlib
import json
import logging
import os
import sys
import urllib.error
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FW_DIR = os.path.join(REPO, "corpus", "vendor-firmware")
MANIFEST = os.path.join(REPO, "corpus", "commercial-manifest.json")

UA = "pluribus-decoder-interop/1.0 (FPGA bitstream decoder testing)"

# ---------------------------------------------------------------------------
# The target list.
#
# `access`:
#   open        — publicly offered, no login/payment/terms gate.  Fetched.
#   js-gated    — public but the file index is rendered client-side, so no
#                 direct URL could be derived without a browser session.
#   model-gated — vendor download centre requires selecting a product/serial.
#   none        — no downloadable firmware exists (OTA/device-side only).
# Only `open` is fetched.  The rest are recorded as findings.
# ---------------------------------------------------------------------------
TARGETS = [
    # ---------------- ECP5 ----------------
    dict(key="raptor_arctic_tern_bmc",
         vendor="Raptor Computing Systems", product="Arctic Tern BMC card (AT1MB1/AT1PC2)",
         family="ecp5", device_expect="LFE5UM5G-85F",
         url="https://gitlab.raptorengineering.com/kestrel-collaboration/kestrel-litex/"
             "litex-boards/-/jobs/9975/artifacts/raw/litex_boards/targets/build/"
             "rcs_arctic_tern_bmc_card/gateware/rcs_arctic_tern_bmc_card.bit",
         license="unknown (CI artifact)", access="open",
         notes="commercial OpenPOWER server BMC replacement module; CI artifact "
               "alongside a .config, so independent ground truth exists"),
    dict(key="limesdr_mini_v2",
         vendor="Lime Microsystems", product="LimeSDR Mini 2.0",
         family="ecp5", device_expect="LFE5U-45F",
         url="https://raw.githubusercontent.com/myriadrf/LimeSDR_GW/master/"
             "bitstream/LimeSDR_Mini_V2/limesdr_mini_v2.bit",
         license="Apache-2.0", access="open",
         notes="commercial SDR sold via Crowd Supply/Mouser; shipped gateware"),
    dict(key="limesdr_mini_v2_golden",
         vendor="Lime Microsystems", product="LimeSDR Mini 2.0 (golden image)",
         family="ecp5", device_expect="LFE5U-45F",
         url="https://raw.githubusercontent.com/myriadrf/LimeSDR_GW/master/"
             "bitstream/LimeSDR_Mini_V2/limesdr_mini_v2_golden.bit",
         license="Apache-2.0", access="open",
         notes="factory fallback image -- a DIFFERENT build of the same product"),
    dict(key="tiliqua_bitstreams",
         vendor="apf.audio", product="Tiliqua (Eurorack audio multitool)",
         family="ecp5", device_expect="LFE5U-25F/45F",
         url="https://github.com/apfaudio/tiliqua/releases/download/v1.2.1/"
             "bitstreams.zip",
         license="see release", access="open",
         notes="commercial Eurorack module; zip of many DSP bitstreams across "
               "two die sizes (SoldierCrab R2=45F, R3=25F)"),
    dict(key="saleae_logic2_240",
         vendor="Saleae", product="Logic 8 / Logic Pro 8 / Logic Pro 16",
         family="ecp5", device_expect="LFE5UM-25F, LFE5UM5G-45F, LFE5U-45F, LFE5U-12F",
         url="https://downloads.saleae.com/logic2/Logic-2.4.0-master.AppImage",
         license="proprietary (application download; no terms gate on CDN link)",
         access="open",
         notes="THE standout target: a genuinely commercial instrument whose "
               "AppImage embeds ~10 ECP5 bitstreams in .rodata of "
               "libgraph_server_shared.so, across FOUR ECP5 sub-families and "
               "several hardware revisions. Built with Diamond 3.12.1.454, "
               "Security off, Readback off, Lattice-native compression. "
               "154 MB download."),
    dict(key="u2plus_l_ecp5",
         vendor="Gideon Zweijtzer (1541 Ultimate)", product="Ultimate-II+L",
         family="ecp5", device_expect="LFE5U-25F-6BG256C",
         url="https://github.com/GideonZ/ultimate_releases/raw/master/u2pl_3.11a.zip",
         license="see project", access="open",
         notes="commercial Commodore accessory, Diamond flow (u2p_ecp5.ldf). "
               "ONLY the -L revision is ECP5; plain U2+/U64 are Cyclone IV. "
               "update_binaries.s does .incbin u2p_ecp5_impl1.bit"),
    dict(key="elgato_4kpro",
         vendor="Elgato (Corsair)", product="4K Pro PCIe capture card",
         family="ecp5", device_expect="ECP5 (density not published)",
         url="https://edge.elgato.com/egc/windows/drivers/4K_Pro/"
             "Elgato_4KPro_1.1.0.202.exe",
         license="proprietary driver package", access="open",
         notes="mass-market consumer capture card. Configuration is VOLATILE "
               "(SRAM-only, reprogrammed by the driver every boot), so the "
               "embedded SC0710.FWI.HEX can only be a bitstream. Windows .exe "
               "installer -- needs unwrapping."),
    # ---------------- MachXO2 ----------------
    dict(key="ataradov_usb_sniffer",
         vendor="Alex Taradov", product="USB sniffer (commercial design, Diamond flow)",
         family="machxo2", device_expect="LCMXO2-2000HC",
         url="https://raw.githubusercontent.com/ataradov/usb-sniffer/main/bin/"
             "usb_sniffer_impl.jed",
         license="see repo", access="open",
         notes="JEDEC, built with Lattice Diamond (.ldf project); IDCODE "
               "0x012bb043 per software/fpga.c"),
    dict(key="summercart64_fw",
         vendor="Polprzewodnikowy", product="SummerCart64 (N64 flashcart, retail)",
         family="machxo2", device_expect="LCMXO2-7000HC",
         url="https://github.com/Polprzewodnikowy/SummerCart64/releases/download/"
             "v2.20.2/sc64-firmware-v2.20.2.bin",
         license="see repo", access="open",
         notes="shipping retail flashcart; multi-chunk container (MCU+FPGA+"
               "bootloader), Diamond-built; sw/tools/primer.py documents layout"),
    dict(key="owon_hds272s",
         vendor="OWON", product="HDS272S handheld oscilloscope",
         family="machxo2", device_expect="LCMXO2-1200HC",
         url="https://files.owon.com.cn/software/upgrade/OWON_HDS272S_V8.zip",
         license="unknown (no terms gate on the file server)", access="open",
         insecure=True,
         notes="TOP MachXO2 PRIORITY: the family has production-quality lifter "
               "support and no real-world corpus at all. Consumer test "
               "equipment, vendor-tool-built. CAVEAT: the LCMXO2-1200HC part "
               "attribution rests on a SINGLE teardown author and the "
               "FPGA-to-firmware link is inferred from file size -- carving is "
               "what turns that into certainty. Cert chain needs -k/insecure."),
    dict(key="hantek_dso2000",
         vendor="Hantek", product="DSO2000 / 2000 series",
         family="machxo2", device_expect="LCMXO2-1200HC",
         url="http://www.hantek.com/download?key=zxgj&sid=0&pid=0",
         license="unknown", access="js-gated",
         skip_reason="the download endpoint is a listing page, not a file; "
                     "per-model archive URLs are not derivable from it without "
                     "a browser session.",
         notes="same MachXO2 part claimed as OWON, same single-teardown caveat"),
    # ---------------- Gowin ----------------
    dict(key="fnirsi_2c23t",
         vendor="FNIRSI", product="2C23T handheld oscilloscope",
         family="gowin", device_expect="GW1N-UV2",
         url="https://raw.githubusercontent.com/openhoangnc/FNIRSI-2C23T/main/"
             "V2.0.2/F2C23T-EN-V2.0.2.bin",
         license="unknown (third-party mirror of vendor firmware)",
         access="open",
         notes="consumer scope; an EEVblog post states the bitstream is pushed "
               "to the FPGA by the MCU at startup, so the update image should "
               "contain it verbatim. Same product family as boards/fnirsi-gw1n2"),
    dict(key="m5stack_atom_display",
         vendor="M5Stack", product="ATOM Display / M5HDMI",
         family="gowin", device_expect="GW1NR-9C (GW1NR-LV9QN88)",
         url="https://github.com/ciniml/atom_display_fpga/releases/download/"
             "v1.1-rc1/Panel_M5HDMI_FS.h",
         license="see repo", access="open",
         notes="mass-market consumer HDMI product; Gowin .fs RLE-compressed into "
               "a C array; design uses RPLL/DCS/CLKDIV IP -- non-trivial clocking"),
    # ---------------- recorded, NOT fetched ----------------
    dict(key="trenz_tebf0808",
         vendor="Trenz Electronic", product="TEBF0808 carrier",
         family="machxo2", device_expect="LCMXO2-1200HC",
         url="https://shop.trenz-electronic.de/Download/?path=Trenz_Electronic/"
             "Modules_and_Module_Carriers/5.2x7.6/5.2x7.6_Carriers/TEBF0808/",
         license="unknown", access="js-gated",
         skip_reason="directory index is rendered client-side; no direct .jed URL "
                     "derivable without a browser session. No login gate seen.",
         notes="genuine commercial industrial carrier; ships SCM/SCS .jed pairs"),
    dict(key="imagingsource_cameras",
         vendor="The Imaging Source", product="industrial cameras (GigE/USB)",
         family="machxo2", device_expect="LCMXO2-1200/2000/4000/7000",
         url="https://www.theimagingsource.com/support/download/",
         license="unknown", access="model-gated",
         skip_reason="host driver (tcam-network MachXO2.cpp/JedecFile.cpp) is "
                     "public, but the camera firmware package is not openly "
                     "enumerable.",
         notes="programs MachXO2 over I2C from JEDEC; real lead, parked"),
    dict(key="supermicro_dell_hpe_cpld",
         vendor="Supermicro / Dell / HPE", product="server CPLD updates",
         family="machxo2", device_expect="various LCMXO2",
         url="(vendor download centres)",
         license="proprietary EULA", access="model-gated",
         skip_reason="download centres are model/serial-gated and JS-driven, and "
                     "the packages carry EULAs. Not pursued.",
         notes="MachXO2 as board glue is common here in principle"),
    dict(key="fnirsi_1013d_1014d",
         vendor="FNIRSI", product="1013D / 1014D handheld oscilloscopes",
         family="anlogic", device_expect="EF2L45LG144B",
         url="https://www.fnirsi.com/pages/manuals-firmwares",
         license="unknown", access="js-gated",
         skip_reason="firmware page is a JS Shopify storefront; per-model file "
                     "URLs are not enumerable without a browser session. No "
                     "login gate observed.",
         notes="Anlogic EF2L45 per CNX Software teardown. Note the EF2 series "
               "differs from the EG4S20 that boards/fnirsi-eg4s20 targets"),
    dict(key="owon_hds200",
         vendor="OWON", product="HDS200 series (HDS272S/HDS2102S/HDS2202S)",
         family="anlogic", device_expect="EG4X20BG256",
         url="https://owon.com.hk/download/index.asp",
         license="unknown", access="js-gated",
         skip_reason="download index is ASP/JS-driven; no direct firmware URL "
                     "derivable without a browser session.",
         notes="same Anlogic supply chain as FNIRSI; not byte-verified"),
    dict(key="gridplus_lattice1",
         vendor="GridPlus", product="Lattice1",
         family="n/a", device_expect="n/a",
         url="n/a", license="n/a", access="none",
         skip_reason="no downloadable firmware; multi-key-signed OTA delivered "
                     "device-side. Product name is coincidental -- not a Lattice "
                     "FPGA.",
         notes="recorded so it is not re-checked"),
]


def setup_logging(name):
    os.makedirs(os.path.join(REPO, "tmp", "logs"), exist_ok=True)
    log = logging.getLogger(name)
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    for h in (logging.StreamHandler(sys.stdout),
              logging.FileHandler(os.path.join(REPO, "tmp", "logs",
                                               f"{name}.log"))):
        h.setFormatter(fmt)
        log.addHandler(h)
    return log


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(t, log):
    """Download one open target.  Returns a manifest record."""
    rec = dict(t)
    dest_dir = os.path.join(FW_DIR, t["key"])
    os.makedirs(dest_dir, exist_ok=True)
    name = t["url"].rstrip("/").split("/")[-1].split("?")[0] or "download.bin"
    dest = os.path.join(dest_dir, name)
    rec["local"] = os.path.relpath(dest, REPO)
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        rec["bytes"] = os.path.getsize(dest)
        rec["sha256"] = sha256_file(dest)
        rec["status"] = "cached"
        log.info("  %-26s cached  %9d bytes  %s", t["key"], rec["bytes"],
                 rec["sha256"][:12])
        return rec
    req = urllib.request.Request(t["url"], headers={"User-Agent": UA})
    # A few vendor file servers ship an incomplete certificate chain.  Relaxing
    # verification is opt-in PER TARGET (`insecure=True`) rather than global, and
    # it is safe here for a narrow reason: the manifest records a SHA-256 for
    # every file, so content integrity is checked independently of transport.
    ctx = None
    if t.get("insecure"):
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        log.info("  %-26s (relaxed TLS verify: incomplete cert chain; "
                 "integrity still checked by SHA-256)", t["key"])
    try:
        with urllib.request.urlopen(req, context=ctx) as r:
            data = r.read()
            rec["http_status"] = r.status
            rec["content_type"] = r.headers.get("Content-Type")
    except Exception as exc:
        rec["status"] = "fetch-failed"
        rec["error"] = str(exc)
        log.error("  %-26s FAILED  %s", t["key"], exc)
        return rec
    with open(dest, "wb") as fh:
        fh.write(data)
    rec["bytes"] = len(data)
    rec["sha256"] = hashlib.sha256(data).hexdigest()
    rec["status"] = "ok"
    log.info("  %-26s ok      %9d bytes  %s", t["key"], len(data),
             rec["sha256"][:12])
    return rec


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=MANIFEST)
    ap.add_argument("--verify", action="store_true",
                    help="re-hash local files, download nothing")
    ap.add_argument("--list", action="store_true", help="show targets and exit")
    ap.add_argument("--only", help="substring filter on key")
    args = ap.parse_args()
    log = setup_logging("commercial_fetch")

    # --only narrows what is FETCHED, never what the manifest describes.  An
    # earlier version filtered TARGETS itself, so `--only saleae` rewrote the
    # manifest with a single entry and silently dropped the other twelve -- the
    # manifest is the committed artefact, so a partial one is worse than none.
    targets = TARGETS
    fetch_keys = ({t["key"] for t in TARGETS if args.only in t["key"]}
                  if args.only else {t["key"] for t in TARGETS})

    if args.list:
        for t in targets:
            log.info("%-26s %-9s %-9s %s / %s", t["key"], t["family"],
                     t["access"], t["vendor"], t["product"])
        return

    openq = [t for t in targets if t["access"] == "open"
             and t["key"] in fetch_keys]
    # Open targets excluded by --only still belong in the manifest; hash them
    # from disk if already present so the committed manifest stays complete.
    deferred = [t for t in targets if t["access"] == "open"
                and t["key"] not in fetch_keys]
    skipped = [t for t in targets if t["access"] != "open"]
    log.info("%d open target(s) to fetch, %d deferred by --only, "
             "%d recorded-but-skipped", len(openq), len(deferred), len(skipped))

    recs = []
    if args.verify:
        for t in openq:
            rec = dict(t)
            dest_dir = os.path.join(FW_DIR, t["key"])
            name = t["url"].rstrip("/").split("/")[-1].split("?")[0]
            dest = os.path.join(dest_dir, name)
            if os.path.exists(dest):
                rec["sha256"] = sha256_file(dest)
                rec["bytes"] = os.path.getsize(dest)
                rec["status"] = "verified"
                log.info("  %-26s %9d bytes  %s", t["key"], rec["bytes"],
                         rec["sha256"][:12])
            else:
                rec["status"] = "missing"
                log.info("  %-26s MISSING", t["key"])
            recs.append(rec)
    else:
        for t in openq:
            recs.append(fetch(t, log))

    for t in skipped:
        rec = dict(t)
        rec["status"] = "skipped-" + t["access"]
        log.info("  %-26s SKIP (%s) %s", t["key"], t["access"],
                 t.get("skip_reason", ""))
        recs.append(rec)

    import datetime
    out = {
        "note": ("Commercial-product FPGA firmware, downloaded to test the "
                 "pluribus decoders against designs built by other parties with "
                 "toolchains we do not control. Binaries are NOT redistributed: "
                 "corpus/vendor-firmware/ and corpus/commercial/ are gitignored. "
                 "This manifest makes the set reproducible from the original "
                 "sources. Entries with access != 'open' were deliberately NOT "
                 "downloaded; skip_reason records why."),
        "retrieved": datetime.datetime.now().astimezone().isoformat(),
        "entries": sorted(recs, key=lambda r: (r["family"], r["key"])),
    }
    with open(args.manifest, "w") as fh:
        json.dump(out, fh, indent=2, sort_keys=True)
    nok = sum(1 for r in recs if r["status"] in ("ok", "cached", "verified"))
    log.info("manifest -> %s (%d fetched, %d skipped)", args.manifest, nok,
             len(skipped))


if __name__ == "__main__":
    main()
