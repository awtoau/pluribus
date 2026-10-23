#!/usr/bin/env python3.15t
"""Oracle-backed corrections applied on top of the Mistral-seeded block-mux tables (native decoder).

Each item names the evidence; the evidence is re-derived by `cyclonev_native_verify.py probes` (Quartus knob builds,
tmp/cyclonev_blockmux_fuzz/) and `... logic` (236-design postfit oracle). Items are data, applied at decode time; the
bootstrap tables stay untouched (same rule as device-db/ + db_overrides.py).
"""
import copy

ITEMS = [
    dict(id="opt-6.2", target="opt", mux="cvp_conf_done_en", rename="release_clears_before_tristates_dis",
         evidence="rs_opt_relclr_on flips exactly oram 6.2 (RELEASE_CLEARS_BEFORE_TRI_STATES On -> 0); CvP knob does not"),
    dict(id="opt-6.3", target="opt", mux="release_clears_before_tristates_dis", rename="bit_6_3_unverified",
         evidence="oram 6.3 moves in none of the opt knob builds; its bootstrap name is unconfirmed"),
    dict(id="opt-6.4", target="opt", mux="device_wide_reset_en", rename="device_wide_reset_dis",
         evidence="rs_opt_dwr_on (ENABLE_DEVICE_WIDE_RESET On) flips exactly oram 6.4 to 0: bit is *_dis"),
    dict(id="opt-start_up_clock", target="opt", mux="start_up_clock", drop_bits=[(6, 3), (6, 4), (6, 5)], default=0x07,
         evidence="6.3/6.4/6.5 alias other fields (dwr/dwoe move them); START_UP_CLOCK knob moves only 6.4/6.5"),
    dict(id="lab-clk0", target=("lab", "mlab"), swap=("clk0_sel", "clk0_inv"),
         evidence="postfit oracle: FF clk inversion matches the swapped reading for every FF on clk0"),
    dict(id="lab-clk1", target=("lab", "mlab"), swap=("clk1_sel", "clk1_inv"),
         evidence="postfit oracle: swapped reading matches every FF on clk1"),
    dict(id="lab-clk2", target=("lab", "mlab"), swap=("clk2_sel", "clk2_inv"),
         evidence="postfit oracle: swapped reading matches every FF on clk2"),
]


class Overrides:
    items = ITEMS

    def apply(self, model):
        for it in ITEMS:
            targets = it["target"] if isinstance(it["target"], tuple) else (it["target"],)
            for tg in targets:
                rows = model.mux[tg]
                if "add_row" in it:
                    rows.append(dict(it["add_row"]))
                    continue
                if "swap" in it:
                    a, b = it["swap"]
                    ia = next(i for i, r in enumerate(rows) if r["mux"] == a)
                    ib = next(i for i, r in enumerate(rows) if r["mux"] == b)
                    ra, rb = copy.copy(rows[ia]), copy.copy(rows[ib])
                    ra["bits"], rb["bits"] = rows[ib]["bits"], rows[ia]["bits"]
                    rows[ia], rows[ib] = ra, rb
                    continue
                i = next(i for i, r in enumerate(rows) if r["mux"] == it["mux"])
                r = copy.copy(rows[i])
                if "rename" in it:
                    r["mux"] = it["rename"]
                if "drop_bits" in it:
                    keep = [k for k, b in enumerate(r["bits"][0]) if tuple(b) not in set(it["drop_bits"])]
                    r["bits"] = [[r["bits"][0][k] for k in keep]]
                    r["bcount"] = len(keep)
                    r["default_value"] = it["default"]
                rows[i] = r
