from fuzzconfig import FuzzConfig
import sys
import nonrouting
import pytrellis

cfg = FuzzConfig(job="SYSCONFIG", family="MachXO2", device="LCMXO2-1200HC", ncl="empty.ncl",
                 tiles=["PT4:CFG0", "PT5:CFG1", "PT6:CFG2", "PT7:CFG3"])


def get_substs(config):
    return dict(sysconfig=("SYSCONFIG " + " ".join(["{}={}".format(k, v) for k, v in config.items()]) + " ;\n"))


def main():
    all_errors = []
    pytrellis.load_database("../../../database")
    cfg.setup()
    empty_bitfile = cfg.build_design(cfg.ncl, {})
    all_errors += nonrouting.check_enum_setting(cfg, "SYSCONFIG.SDM_PORT",
                                  ["PROGRAMN", "PROGRAMN_DONE", "PROGRAMN_DONE_INITN", "DONE", "INITN", "DISABLE"],
                                  lambda x: get_substs(dict(SDM_PORT=x)), empty_bitfile)
    all_errors += nonrouting.check_enum_setting(cfg, "SYSCONFIG.SLAVE_SPI_PORT", ["DISABLE", "ENABLE"],
                                  lambda x: get_substs(dict(SLAVE_SPI_PORT=x)), empty_bitfile)
    all_errors += nonrouting.check_enum_setting(cfg, "SYSCONFIG.MASTER_SPI_PORT", ["DISABLE", "ENABLE", "EFB_USER"],
                                  lambda x: get_substs(dict(MASTER_SPI_PORT=x)), empty_bitfile)
    all_errors += nonrouting.check_enum_setting(cfg, "SYSCONFIG.I2C_PORT", ["DISABLE", "ENABLE"],
                                  lambda x: get_substs(dict(I2C_PORT=x)), empty_bitfile)
    all_errors += nonrouting.check_enum_setting(cfg, "SYSCONFIG.ENABLE_TRANSFR", ["DISABLE", "ENABLE"],
                                  lambda x: get_substs(dict(ENABLE_TRANSFR=x)), empty_bitfile)
    all_errors += nonrouting.check_enum_setting(cfg, "SYSCONFIG.BACKGROUND_RECONFIG", ["OFF", "ON"],
                                  lambda x: get_substs(dict(BACKGROUND_RECONFIG=x)), empty_bitfile)

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
