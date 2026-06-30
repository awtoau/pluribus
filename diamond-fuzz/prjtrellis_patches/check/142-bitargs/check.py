from fuzzconfig import FuzzConfig
import sys
import nonrouting
import pytrellis
import os

cfg = FuzzConfig(job="BITARGS", family="MachXO2", device="LCMXO2-1200HC", ncl="empty.ncl",
                 tiles=["PT4:CFG0"])


def get_substs(config):
    os.environ["BITARGS"] = " ".join(["-g {}:{}".format(k, v) for k, v in config.items()])
    return {}

def main():
    all_errors = []
    pytrellis.load_database("../../../database")
    cfg.setup()
    empty_bitfile = cfg.build_design(cfg.ncl, {})
    all_errors += nonrouting.check_enum_setting(cfg, "SYSCONFIG.DONEPHASE", ["T0", "T1", "T2", "T3"],
                                  lambda x: get_substs(dict(DONEPHASE=x)), empty_bitfile)
    all_errors += nonrouting.check_enum_setting(cfg, "SYSCONFIG.GOEPHASE", ["T1", "T2", "T3"],
                                  lambda x: get_substs(dict(GOEPHASE=x)), empty_bitfile)
    all_errors += nonrouting.check_enum_setting(cfg, "SYSCONFIG.GSRPHASE", ["T1", "T2", "T3"],
                                  lambda x: get_substs(dict(GSRPHASE=x)), empty_bitfile)
    all_errors += nonrouting.check_enum_setting(cfg, "SYSCONFIG.GWEPHASE", ["T1", "T2", "T3"],
                                  lambda x: get_substs(dict(GWEPHASE=x)), empty_bitfile)

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
