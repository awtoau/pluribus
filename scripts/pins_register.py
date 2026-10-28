#!/usr/bin/env python3.15t
"""Fill device_pins (package ball -> bank / die site / vendor function names) from vendor data on disk.

  python3.15t scripts/pins_register.py --family cycloneiv [--corpus corpus/cycloneiv] [--ibis-dir <quartus>/eda/ibis]
                                       [--all-reports] [--devices EP4CGX150DF31,...]

Sources (each field remembers which source gave it; disagreements are flagged in `conflicts`, never resolved
by precedence):
  fit.rpt   "All Package Pins" (pin, pad number, bank, usage, dir, I/O type, weak pull-up) and
            "Dual Purpose and Dedicated Pins" (vendor function names, pin type)         -> source "fit.rpt"
  build.pin Quartus pin-out file (pin, usage, dir, bank)                                 -> source "pin"
  postfit.vo "// <port> => Location: PIN_x" + "// Location: IOxBUF_X_Y_N" (die site)   -> source "vo"
  IBIS xml  <quartus>/eda/ibis/<part><pkg>.xml "[Pin Numbers]" net per ball (every package) -> source "ibis"
Identical report files are parsed once (sha256). One per device unless --all-reports (conflict sweep).
Always-rebuild per family; one evidence(vendor-decode) row per run links every pin row.
Log: tmp/logs/pins_register.log
"""
import argparse
import datetime
import hashlib
import json
import logging
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from sqlalchemy import delete, insert

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
import db                                   # noqa: E402
import schema as S                          # noqa: E402
from provenance import evidence_io as E     # noqa: E402

log = logging.getLogger("pins_register")

PART_RE = re.compile(r"^(EP4C(?:GX|E)\d+)([A-Z]{1,2}\d+)([A-Z]\d+[A-Z]?)?$")   # EP4CGX150 DF31 C7
VO_PIN_RE = re.compile(r"^// (\S+)\s+=>\s+Location: PIN_([A-Z]+\d+)", re.M)
VO_LOC_RE = re.compile(r"^// Location: (IO[IO]BUF)_X(\d+)_Y(\d+)_N(\d+)\n\s*cycloneiv_io_[io]buf \\?(\S+?)\s*\(", re.M)
IBIS_ROW_RE = re.compile(r"^([A-Z]+\d+)\s*\|\s*(\d+)\s+(\S+)\s+", re.M)
IBIS_CONT_RE = re.compile(r"^\|([A-Z]+\d+)\s*$", re.M)
SPECIAL_RULES = (("jtag", re.compile(r"^(TCK|TMS|TDI|TDO)$|^X_B\d_T(CK|MS|DI|DO)_X$")),
                 ("config", re.compile(r"MSEL|CONF_?DONE|NSTATUS|NCONFIG|^DATA\d|DCLK|^NCE|NCEO|ASDO|NCSO|UDATA|CONDONE|FLASH_NCE|DEV_OE|DEV_CLRN|INIT_DONE|CRC_ERROR|CLKUSR")),
                 ("clock", re.compile(r"^CLK\d|PLLCLKOUT|LVDSCLK|^DIFFCLK|REFCLK|CLKIN")),
                 ("transceiver", re.compile(r"^X_QL\d|GXB|^RX\d|^TX\d|REFCLK")),
                 ("reference", re.compile(r"VREF|RUP|RDN|RREF")),
                 ("ground", re.compile(r"^GND|GXB_GND")),
                 ("power", re.compile(r"^VCC|^VCCN\d|^VCCA|^VCCD|^VCCE|^VCCH|^VCCL|^VCCIO")))
SIDE_FROM_IBIS = {"LVDST": "top", "LVDSB": "bottom", "LVDSL": "left", "LVDSR": "right"}


def split_part(opn):
    m = PART_RE.match(opn.strip())
    if not m:
        return None
    return m.group(1), m.group(2), (m.group(1) + m.group(2))


# ── parsers ─────────────────────────────────────────────────────────────────────────────────

def _table(text, title):
    """Rows of the '; <title>' fitter table as dicts keyed by the header cells."""
    i = text.find(f"; {title}")
    if i < 0:
        return []
    i = text.find(f"; {title}", i + 1) if text.count(f"; {title}") > 1 else i   # skip the TOC entry
    lines = text[i:].splitlines()
    hdr = None
    rows = []
    for ln in lines[1:]:
        if ln.startswith("+"):
            if hdr is not None and rows:
                break
            continue
        if not ln.startswith(";"):
            if hdr is not None:
                break
            continue
        cells = [c.strip() for c in ln.strip().strip(";").split(";")]
        if hdr is None:
            hdr = cells
            continue
        if len(cells) == len(hdr):
            rows.append(dict(zip(hdr, cells)))
    return rows


def parse_fit_rpt(text):
    """-> {pin: {fields}} from 'All Package Pins' + 'Dual Purpose and Dedicated Pins'; plus the OPN."""
    m = re.search(r"ASSIGNED TO AN:\s*(\S+)|Device\s*;\s*(EP\S+)", text)
    opn = (m.group(1) or m.group(2)) if m else None
    out = {}
    for r in _table(text, "All Package Pins"):
        pin = r.get("Location")
        if not pin:
            continue
        usage = r.get("Pin Name/Usage", "").lstrip("^")      # '^' marks a pin whose role is set by a device option
        nz = lambda v: None if v in ("", "--") else v        # noqa: E731  ('--' = not applicable in fitter tables)
        rec = {"pad_number": int(r["Pad Number"]) if r.get("Pad Number", "").isdigit() else None,
               "bank": nz(r.get("I/O Bank")), "io_type": nz(r.get("I/O Type")),
               "usage_default": usage if not r.get("User Assignment") else None,
               "bonded": usage not in ("NC", "DNU"),
               "dir": nz(r.get("Dir.")), "weak_pull_up": nz(r.get("Weak Pull Up"))}
        names = [n.strip() for n in usage.replace(" / ", "/").split("/") if n.strip() and not n.startswith("RESERVED")]
        rec["func_names"] = names
        out[pin] = rec
    for r in _table(text, "Dual Purpose and Dedicated Pins"):
        pin = r.get("Location")
        if not pin:
            continue
        rec = out.setdefault(pin, {"func_names": []})
        names = [n.strip() for n in r.get("Pin Name", "").split(",") if n.strip()]
        rec["func_names"] = sorted(set(rec.get("func_names", [])) | set(names))
        rec["pin_type"] = r.get("Pin Type")
        rec["reserved_as"] = r.get("Reserved As")
    return opn, out


def parse_pin_file(text):
    m = re.search(r"ASSIGNED TO AN:\s*(\S+)", text)
    opn = m.group(1) if m else None
    out = {}
    for ln in text.splitlines():
        if " : " not in ln or ln.startswith(" --") or ln.startswith("CHIP"):
            continue
        cells = [c.strip() for c in ln.split(":")]
        if len(cells) < 6 or not re.match(r"^[A-Z]+\d+$", cells[1]):
            continue
        usage, pin, d, _iostd, _volt, bank = cells[:6]
        usage = usage.lstrip("^")
        names = [n.strip() for n in usage.replace(" / ", "/").split("/") if n.strip() and not n.startswith("RESERVED")]
        out[pin] = {"bank": bank or None, "dir": d or None, "usage_default": usage if len(cells) < 7 or not cells[6] else None,
                    "func_names": names, "bonded": usage not in ("NC", "DNU")}
    return opn, out


def parse_vo(text):
    """-> {pin: {tile_x, tile_y, z, io_site}} for every port placed on a pin with an IO buffer location."""
    port_pin = {}
    for port, pin in VO_PIN_RE.findall(text):
        port_pin[port] = pin
    out = {}
    for kind, x, y, n, inst in VO_LOC_RE.findall(text):
        inst = inst.rstrip()
        port = inst.split("~")[0]
        pin = port_pin.get(port)
        if pin:
            out[pin] = {"tile_x": int(x), "tile_y": int(y), "z": int(n), "io_site": f"{kind}_X{x}_Y{y}_N{n}"}
    return out


def parse_ibis(text):
    """-> (device e.g. EP4CGX150DF31, n_pins, {pin: net_name})."""
    m = re.search(r'<data_type name="([A-Z0-9]+)"', text)
    dev = m.group(1) if m else None
    n = re.search(r"\[Number of Pins\]\s+(\d+)", text)
    sec = text.find("[Pin Numbers]")
    body = text[sec:text.find("[Model Data]", sec) if "[Model Data]" in text[sec:] else None] if sec >= 0 else ""
    out = {}
    cur = None
    for ln in body.splitlines():
        r = IBIS_ROW_RE.match(ln)
        if r:
            cur = r.group(3)
            out[r.group(1)] = cur
            continue
        c = IBIS_CONT_RE.match(ln)
        if c and cur:
            out[c.group(1)] = cur
    return dev, int(n.group(1)) if n else None, out


def decode_ibis_net(net):
    """X_B8_X_LVDST_10N -> {bank: '8', side: 'top', func: 'LVDST_10N'}; VCC/GND stay as is."""
    rec = {"func": net}
    m = re.match(r"^([DX])_(B(\d+)|QL(\d))_(.*)$", net)
    if not m:
        return rec
    rec["bank"] = m.group(3)
    if m.group(4) is not None:
        rec["side"] = "left"          # transceiver quads sit on the left edge of the GX die
        rec["bank"] = f"QL{m.group(4)}"
    rest = m.group(5)
    rest = rest[2:] if rest.startswith("X_") else rest
    rest = rest[:-2] if rest.endswith("_X") else rest
    rec["func"] = rest
    for k, v in SIDE_FROM_IBIS.items():
        if rest.startswith(k):
            rec["side"] = v
    return rec


def special_of(names):
    for n in names:
        for kind, rx in SPECIAL_RULES:
            if rx.search(n):
                return kind
    return "none"


# ── merge ───────────────────────────────────────────────────────────────────────────────────

MERGE_FIELDS = ("pad_number", "bank", "side", "tile_x", "tile_y", "z", "io_site", "io_type", "usage_default", "bonded")


def merge(per_source):
    """per_source: {source_id: {pin: {field: value}}} -> {pin: row dict with source/conflicts}."""
    pins = defaultdict(dict)
    for src, table in per_source.items():
        for pin, rec in table.items():
            pins[pin][src] = rec
    out = {}
    for pin, by_src in pins.items():
        row = {"pin": pin, "source": {}, "conflicts": [], "func_names": set(), "opns": set()}
        for f in MERGE_FIELDS:
            vals = {s: r[f] for s, r in by_src.items() if r.get(f) is not None}
            if not vals:
                continue
            distinct = {json.dumps(v, sort_keys=True) for v in vals.values()}
            row[f] = next(iter(vals.values()))
            row["source"][f] = sorted(vals)
            if len(distinct) > 1:
                row["conflicts"].append({"field": f, "values": {s: v for s, v in vals.items()}})
        for s, r in by_src.items():
            row["func_names"].update(r.get("func_names", []))
            if r.get("ibis_net"):
                row["ibis_net"] = r["ibis_net"]
                row["source"]["ibis_net"] = [s]
            if r.get("pin_type"):
                row["pin_type"] = r["pin_type"]
        row["func_names"] = sorted(row["func_names"])
        row["source"]["func_names"] = sorted(s for s, r in by_src.items() if r.get("func_names"))
        names = list(row["func_names"]) + ([row["ibis_net"]] if row.get("ibis_net") else [])
        row["special"] = special_of(names)
        if row["special"] == "none" and row.get("pin_type"):
            row["special"] = "config" if "Programming" in row["pin_type"] else row["special"]
        out[pin] = row
    return out


# ── register ────────────────────────────────────────────────────────────────────────────────

def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def collect_corpus(corpus, all_reports=False):
    """-> {device: {"fit.rpt": {...}, "pin": {...}, "vo": {...}, "opns": set, "files": n}} parsed from the corpus builds."""
    per_dev = {}
    seen_hash = set()
    n_vo = 0
    for d in sorted(Path(corpus).iterdir()):
        if not d.is_dir():
            continue
        toml = d / "design.toml"
        opn = None
        if toml.exists():
            m = re.search(r'^device\s*=\s*"([^"]+)"', toml.read_text(), re.M)
            opn = m.group(1) if m else None
        sp = split_part(opn or "")
        if not sp:
            continue
        part, pkg, dev = sp
        slot = per_dev.setdefault(dev, {"part": part, "package": pkg, "opns": set(), "fit.rpt": {}, "pin": {}, "vo": {},
                                        "files": {"fit.rpt": 0, "pin": 0, "vo": 0}, "vo_conflicts": 0})
        slot["opns"].add(opn)
        for name, parser, key in (("fit.rpt", parse_fit_rpt, "fit.rpt"), ("build.pin", parse_pin_file, "pin")):
            p = d / name
            if not p.exists():
                continue
            if slot[key] and not all_reports:
                continue
            h = _sha(p)
            if h in seen_hash:
                continue
            seen_hash.add(h)
            _opn, rows = parser(p.read_text(errors="replace"))
            for pin, rec in rows.items():
                old = slot[key].get(pin)
                if old is None:
                    slot[key][pin] = rec
                else:   # across builds only the user-assignment-dependent fields may differ: keep the vendor ones, note disagreement
                    for f in ("pad_number", "bank", "io_type"):
                        if old.get(f) is not None and rec.get(f) is not None and old[f] != rec[f]:
                            old.setdefault("_disagree", []).append((f, rec[f]))
            slot["files"][key] += 1
        vo = d / "postfit.vo"
        if vo.exists():
            n_vo += 1
            for pin, rec in parse_vo(vo.read_text(errors="replace")).items():
                old = slot["vo"].get(pin)
                if old is None:
                    slot["vo"][pin] = rec
                elif (old["tile_x"], old["tile_y"], old["z"]) != (rec["tile_x"], rec["tile_y"], rec["z"]):
                    slot["vo_conflicts"] += 1
                    old.setdefault("_disagree", []).append(rec["io_site"])
            slot["files"]["vo"] += 1
    log.info("corpus %s: %d devices, %d postfit.vo scanned", corpus, len(per_dev), n_vo)
    return per_dev


def collect_ibis(ibis_dir, devices=None):
    out = {}
    for p in sorted(Path(ibis_dir).glob("ep4c*.xml")):
        dev, n, rows = parse_ibis(p.read_text(errors="replace"))
        if not dev or len(rows) < 5:
            log.info("ibis %s: %s (%d rows) skipped (unparsed format)", p.name, dev, len(rows))
            continue
        if devices and dev not in devices:
            continue
        sp = split_part(dev)
        if not sp:
            continue
        part, pkg, _ = sp
        table = {}
        for pin, net in rows.items():
            dec = decode_ibis_net(net)
            table[pin] = {"ibis_net": net, "bank": dec.get("bank"), "side": dec.get("side"), "func_names": [dec["func"]],
                          "bonded": True}
        out[dev] = {"part": part, "package": pkg, "n_pins": n, "rows": table, "file": str(p)}
    log.info("ibis %s: %d packages", ibis_dir, len(out))
    return out


def side_from_site(rec, xmax, ymax):
    x, y = rec.get("tile_x"), rec.get("tile_y")
    if x is None or y is None:
        return None
    if y == ymax:
        return "top"
    if y == 0:
        return "bottom"
    if x == 0:
        return "left"
    if xmax is not None and x >= xmax:
        return "right"
    return None


def build_rows(family, dev, part, pkg, per_source, opns, geom=None):
    xmax = ymax = None
    if geom:
        xmax, ymax = geom.get("xmax"), geom.get("ymax")
    for rec in per_source.get("vo", {}).values():
        s = side_from_site(rec, xmax, ymax)
        if s:
            rec["side"] = s
    merged = merge({k: v for k, v in per_source.items() if v})
    rows = []
    for pin, r in sorted(merged.items()):
        rows.append(dict(family=family, device=dev, part=part, package=pkg, opns=sorted(opns), pin=pin,
                         pad_number=r.get("pad_number"), bank=r.get("bank"), side=r.get("side"), tile_x=r.get("tile_x"),
                         tile_y=r.get("tile_y"), z=r.get("z"), io_site=r.get("io_site"), io_type=r.get("io_type"),
                         func_names=r["func_names"], ibis_net=r.get("ibis_net"), special=r["special"],
                         bonded=r.get("bonded"), usage_default=r.get("usage_default"), source=r["source"],
                         conflicts=r["conflicts"] or None, updated_at=datetime.datetime.now().astimezone()))
    return rows


def register(family, corpus, ibis_dir, all_reports=False, devices=None, geom=None):
    S.init()
    corp = collect_corpus(corpus, all_reports) if corpus and Path(corpus).is_dir() else {}
    ibis = collect_ibis(ibis_dir, devices) if ibis_dir and Path(ibis_dir).is_dir() else {}
    devs = sorted(set(corp) | set(ibis))
    if devices:
        devs = [d for d in devs if d in devices]
    commit = E.git_head(REPO)
    total = 0
    with db.engine().begin() as conn:
        E.ensure_family(conn, family)
        conn.execute(delete(S.device_pins).where(S.device_pins.c.family == family))
        ev = E.record_decode(conn, family, "*", f"device_pins from vendor data ({len(devs)} packages)",
                             {"corpus": corpus, "ibis_dir": ibis_dir, "devices": devs,
                              "files": {d: corp[d]["files"] for d in corp}}, commit, "scripts/pins_register.py",
                             generator="scripts/pins_register.py", kind="vendor-decode")
        for dev in devs:
            c = corp.get(dev, {})
            i = ibis.get(dev, {})
            part = (c or i)["part"]
            pkg = (c or i)["package"]
            per_source = {"fit.rpt": c.get("fit.rpt", {}), "pin": c.get("pin", {}), "vo": c.get("vo", {}), "ibis": i.get("rows", {})}
            rows = build_rows(family, dev, part, pkg, per_source, c.get("opns", set()), geom)
            for r in rows:
                r["evidence_id"] = ev
            if rows:
                conn.execute(insert(S.device_pins), rows)
            n_conf = sum(1 for r in rows if r["conflicts"])
            n_site = sum(1 for r in rows if r["tile_x"] is not None)
            log.info("%-16s pins %4d  with die site %4d  bonded %4d  conflicts %3d  sources %s", dev, len(rows), n_site,
                     sum(1 for r in rows if r["bonded"]), n_conf, {k: len(v) for k, v in per_source.items() if v})
            total += len(rows)
    log.info("%s: %d device_pins rows over %d packages", family, total, len(devs))
    return total


def main():
    (REPO / "tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler(REPO / "tmp/logs/pins_register.log")])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--family", default="cycloneiv")
    ap.add_argument("--corpus", default=str(REPO / "corpus" / "cycloneiv"))
    ap.add_argument("--ibis-dir", default=None, help="default: <quartus>/eda/ibis from toolchain.quartus_bin()")
    ap.add_argument("--all-reports", action="store_true", help="parse every distinct fit.rpt/.pin (conflict sweep), not one per device")
    ap.add_argument("--devices", default=None, help="comma list, e.g. EP4CGX150DF31,EP4CE6E22")
    a = ap.parse_args()
    ibis = a.ibis_dir
    if ibis is None:
        import toolchain
        qb = toolchain.quartus_bin(required=False)
        ibis = str(Path(qb).parent / "eda" / "ibis") if qb else None
    geom = None
    gp = REPO / "lifters/data/cycloneiv_ep4cgx150_geom.json"
    if a.family == "cycloneiv" and gp.exists():
        geom = json.loads(gp.read_text())
    devs = set(a.devices.split(",")) if a.devices else None
    register(a.family, a.corpus, ibis, a.all_reports, devs, geom)
    return 0


if __name__ == "__main__":
    sys.exit(main())
