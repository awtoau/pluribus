from fuzzconfig import FuzzConfig
import sys
import nonrouting
import pytrellis

jobs = [(FuzzConfig(job="DQSDLL_R", family="MachXO2", device="LCMXO2-1200HC", ncl="empty.ncl",
                    tiles=["PT21:DQSDLL_R"]), "TDQSDLL"),
        (FuzzConfig(job="DQSDLL_L", family="MachXO2", device="LCMXO2-1200HC", ncl="empty.ncl",
                    tiles=["PB2:DQSDLL_L"]), "BDQSDLL"),
        ]


def todecstr(x):
    res = 0
    for i in range(len(x)):
        if x[i]:
            res |= 1 << i
    return str(res)


def main():
    all_errors = []
    pytrellis.load_database("../../../database")

    for job in jobs:
        cfg, loc = job
        cfg.setup()

        def get_muxval(sig, val):
            if val == sig:
                return None
            elif val in ("0", "1"):
                return {sig: val}
            elif val == "INV":
                return {sig: "#INV"}
            else:
                assert False

        def get_substs(mode="DQSDLLC", program={}, muxes=None):
            if mode == "NONE":
                comment = "//"
            else:
                comment = ""
            program = ",".join(["{}={}".format(k, v) for k, v in program.items()])
            if muxes is not None:
                program += ":" + ",".join(["{}={}".format(k, v) for k, v in muxes.items()])
            return dict(site=loc, comment=comment, program=program)

        empty_bitfile = cfg.build_design(cfg.ncl, {})
        cfg.ncl = "dqsdll.ncl"

        all_errors += nonrouting.check_enum_setting(cfg, "{}.MODE".format(loc), ["NONE", "DQSDLLC"],
                                      lambda x: get_substs(mode=x, program=dict(DEL_ADJ="PLUS")), empty_bitfile)
        all_errors += nonrouting.check_enum_setting(cfg, "{}.RST".format(loc), ["0", "1", "RST", "INV"],
                                      lambda x: get_substs(muxes=get_muxval("RST", x)), empty_bitfile)
        all_errors += nonrouting.check_enum_setting(cfg, "{}.DEL_ADJ".format(loc), ["PLUS", "MINUS"],
                                      lambda x: get_substs(
                                          program=dict(DEL_ADJ=x, DEL_VAL=(1 if x == "PLUS" else 127))),
                                      empty_bitfile)
        all_errors += nonrouting.check_word_setting(cfg, "{}.DEL_VAL".format(loc), 7,
                                      lambda x: get_substs(program=dict(DEL_VAL=todecstr(x))), empty_bitfile)
        all_errors += nonrouting.check_enum_setting(cfg, "{}.FORCE_MAX_DELAY".format(loc), ["NO", "YES"],
                                      lambda x: get_substs(program=dict(FORCE_MAX_DELAY=x)), empty_bitfile)
        all_errors += nonrouting.check_enum_setting(cfg, "{}.GSR".format(loc), ["ENABLED", "DISABLED"],
                                      lambda x: get_substs(program=dict(GSR=x)), empty_bitfile)
        all_errors += nonrouting.check_enum_setting(cfg, "{}.LOCK_SENSITIVITY".format(loc), ["LOW", "HIGH"],
                                      lambda x: get_substs(program=dict(LOCK_SENSITIVITY=x)), empty_bitfile)


    if all_errors:
        print()
        print("=" * 70)
        print("!!! DATABASE MISMATCH — {} total discrepancy(s) !!!".format(len(all_errors)))
        for e in all_errors:
            print("  " + e)
        print("=" * 70)
        sys.exit(1)
    else:
        print("ALL OK — Diamond 3.14 matches prjtrellis database for this fuzzer")

if __name__ == "__main__":
    main()
