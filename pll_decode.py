"""MachXO2 EHXPLLJ config -> divider plan (from a native-decoded `.config`).

Word = DIV - 1 (Diamond oracle: diamond-fuzz/targets/ehxpllj_4out, CLKOS_DIV 4 -> 0000011,
CLKOS2_DIV 2 -> 0000001, CLKOS3_DIV 16 -> 0001111).  A word of 0 is absent from the
`.config` (decoder omits all-zero words), so a missing word means DIV = 1.
Only FEEDBK_PATH == INT_DIVD is handled: Fvco = Fin * CLKFB_DIV / CLKI_DIV.
Any other feedback path is returned with `fvco_ratio = None` rather than guessed.
"""
import re

OUTPUTS = ("CLKOP", "CLKOS", "CLKOS2", "CLKOS3")


def parse_pll(config_text):
    """Return {tile, enums, words, i_div, fb_div, out_div{}, enabled{}, fvco_ratio} or None."""
    m = re.search(r"^\.tile (\S+):(?:GPLL_\w+|PLL_\w+)\n(.*?)(?=^\.tile |\Z)",
                  config_text, re.M | re.S)
    if not m:
        return None
    words, enums = {}, {}
    for ln in m.group(2).splitlines():
        if ln.startswith("word: "):
            _, name, bits = ln.split()
            words[name] = int(bits, 2)
        elif ln.startswith("enum: "):
            _, name, val = ln.split(None, 2)
            enums[name] = val
    div = lambda w: words.get(w, 0) + 1           # noqa: E731
    out_div = {o: div(f"{o}_DIV") for o in OUTPUTS}
    enabled = {o: enums.get(f"{o}_ENABLE") == "ENABLED" for o in OUTPUTS}
    ratio = None
    if enums.get("FEEDBK_PATH") == "INT_DIVD":
        ratio = div("CLKFB_DIV") / div("CLKI_DIV")
    return {"tile": m.group(1), "words": words, "enums": enums,
            "i_div": div("CLKI_DIV"), "fb_div": div("CLKFB_DIV"),
            "out_div": out_div, "enabled": enabled, "fvco_ratio": ratio}


def output_freqs(pll, fin_mhz):
    """{output: MHz} for enabled outputs; empty if the feedback path is not INT_DIVD."""
    if pll["fvco_ratio"] is None:
        return {}
    fvco = fin_mhz * pll["fvco_ratio"]
    return {o: fvco / pll["out_div"][o] for o in OUTPUTS if pll["enabled"][o]}


def solve_fin(pll, observed):
    """Input frequency (MHz) making the PLL output set cover every observed rate.

    observed: iterable of MHz values (e.g. the spine track rates).  Tries each
    (observed rate, output) pairing; returns the unique Fin or None.
    """
    if pll["fvco_ratio"] is None:
        return None
    obs = sorted(set(observed))
    cands = set()
    for o, d in pll["out_div"].items():
        if pll["enabled"][o]:
            for f in obs:
                cands.add(round(f * d / pll["fvco_ratio"], 6))
    good = [fin for fin in sorted(cands)
            if all(any(abs(fo - f) < 1e-6 for fo in output_freqs(pll, fin).values())
                   for f in obs)]
    return good[0] if len(good) == 1 else None
