from fuzzconfig import FuzzConfig
import sys
import nonrouting
import pytrellis

job = (FuzzConfig(job="START", family="MachXO2", device="LCMXO2-1200HC", ncl="empty.ncl",
                  tiles=["CIB_R1C4:CIB_CFG0"]), "R1C4")

def get_substs(val):
    comment = ""
    if val == "0":
        start = ":::STARTCLK=0"
    if val == "1":
        start = ":::STARTCLK=1"
    elif val == "INV":
        start = ":::STARTCLK=#INV"
    else:
        start = "#ON"
    return dict(comment=comment, start=start)


def main():
    all_errors = []
    pytrellis.load_database("../../../database")
    cfg, rc = job
    cfg.setup()
    empty_bitfile = cfg.build_design(cfg.ncl, {})
    cfg.ncl = "start.ncl"

    all_errors += nonrouting.check_enum_setting(cfg, "START.STARTCLK", ["0", "1", "STARTCLK", "INV"],
                                  lambda x: get_substs(val=x), empty_bitfile)


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
