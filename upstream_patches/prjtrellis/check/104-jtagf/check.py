from fuzzconfig import FuzzConfig
import sys
import nonrouting
import pytrellis

cfg = FuzzConfig(job="JTAGF", family="MachXO2", device="LCMXO2-2000HC", ncl="empty.ncl", tiles=["PT4:CFG0"])

def get_substs(mode="JTAGF", er1="DISABLED", er2="DISABLED"):
    if mode == "NONE":
        comment = "//"
    else:
        comment = ""
    return dict(comment=comment, er1=er1, er2=er2)

def main():
    all_errors = []
    pytrellis.load_database("../../../database")
    cfg.setup()
    empty_bitfile = cfg.build_design(cfg.ncl, {})
    cfg.ncl = "jtag.ncl"

    all_errors += nonrouting.check_enum_setting(cfg, "JTAG.MODE", ["NONE", "JTAGF"],
                                  lambda x: get_substs(mode=x), empty_bitfile)
    all_errors += nonrouting.check_enum_setting(cfg, "JTAG.ER1", ["DISABLED", "ENABLED"],
                                  lambda x: get_substs(er1=x), empty_bitfile)
    all_errors += nonrouting.check_enum_setting(cfg, "JTAG.ER2", ["DISABLED", "ENABLED"],
                                  lambda x: get_substs(er2=x), empty_bitfile)

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
