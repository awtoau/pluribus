from fuzzconfig import FuzzConfig
import sys
import nonrouting
import pytrellis

job = (FuzzConfig(job="GSR", family="MachXO2", device="LCMXO2-1200HC", ncl="empty.ncl",
                  tiles=["PT4:CFG0"]), "R1C4")

def get_substs(gsrmode="ACTIVE_LOW", syncmode="NONE"):
    if gsrmode == "NONE":
        comment = "//"
    else:
        comment = ""
    if syncmode == "NONE":
        syncmode = "#OFF"
    return dict(comment=comment, gsrmode=gsrmode, syncmode=syncmode)


def main():
    all_errors = []
    pytrellis.load_database("../../../database")
    cfg, rc = job
    cfg.setup()
    empty_bitfile = cfg.build_design(cfg.ncl, {})
    cfg.ncl = "gsr.ncl"

    all_errors += nonrouting.check_enum_setting(cfg, "GSR.GSRMODE", ["NONE", "ACTIVE_LOW", "ACTIVE_HIGH"],
                                  lambda x: get_substs(gsrmode=x), empty_bitfile)
    all_errors += nonrouting.check_enum_setting(cfg, "GSR.SYNCMODE", ["NONE", "ASYNC", "SYNC"],
                                  lambda x: get_substs(syncmode=x), empty_bitfile)


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
