from fuzzconfig import FuzzConfig
import sys
import nonrouting
import pytrellis

cfg = FuzzConfig(job="PCNTR", family="MachXO2", device="LCMXO2-1200HC", ncl="empty.ncl",
                  tiles=["PT4:CFG0", "PT5:CFG1", "PT6:CFG2", "PT7:CFG3", "PT8:PIC_T_DUMMY_OSC"])

def get_substs(mode="PCNTR", program={}):
    if mode == "NONE":
        comment = "//"
    else:
        comment = ""
    program = ",".join(["{}={}".format(k, v) for k, v in program.items()])
    return dict(comment=comment, program=program)

def main():
    all_errors = []
    pytrellis.load_database("../../../database")

    cfg.setup()
    empty_bitfile = cfg.build_design(cfg.ncl, {})
    cfg.ncl = "pcntr.ncl"

    all_errors += nonrouting.check_enum_setting(cfg, "PCNTR.STDBYOPT", ["USER_CFG", "USER", "CFG"],
                                  lambda x: get_substs(program=dict(STDBYOPT=x)), empty_bitfile)
    all_errors += nonrouting.check_enum_setting(cfg, "PCNTR.WAKEUP", ["USER", "CFG"],
                                  lambda x: get_substs(program=dict(WAKEUP=x)), empty_bitfile)
    all_errors += nonrouting.check_enum_setting(cfg, "PCNTR.TIMEOUT", ["BYPASS", "USER", "COUNTER"],
                                  lambda x: get_substs(program=dict(TIMEOUT=x)), empty_bitfile)
    all_errors += nonrouting.check_enum_setting(cfg, "PCNTR.POROFF", ["FALSE", "TRUE"],
                                  lambda x: get_substs(program=dict(POROFF=x)), empty_bitfile)
    all_errors += nonrouting.check_enum_setting(cfg, "PCNTR.BGOFF", ["FALSE", "TRUE"],
                                  lambda x: get_substs(program=dict(BGOFF=x)), empty_bitfile)

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
