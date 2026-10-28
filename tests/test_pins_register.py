"""device_pins + scripts/pins_register.py: parsers, per-field provenance merge, conflict flags, DB round trip."""
import os
import sys

from sqlalchemy import select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

FIT = """Fitter report for build
Quartus Prime Version 25.1std.0 Build 1129
; Table of Contents ;
 12. Dual Purpose and Dedicated Pins
 14. All Package Pins

+----------+------------------+--------------------------+---------------------+---------------------------+
; Dual Purpose and Dedicated Pins                                                                          ;
+----------+------------------+--------------------------+---------------------+---------------------------+
; Location ; Pin Name         ; Reserved As              ; User Signal Name    ; Pin Type                  ;
+----------+------------------+--------------------------+---------------------+---------------------------+
; AC8      ; MSEL3            ; -                        ; -                   ; Dedicated Programming Pin ;
; AE7      ; DIFFIO_B1n, NCEO ; Use as programming pin   ; ~ALTERA_NCEO~       ; Dual Purpose Pin          ;
+----------+------------------+--------------------------+---------------------+---------------------------+

+----------+------------+----------+--------------------------------------------------+--------+--------------+---------+------------+-----------------+----------+--------------+
; All Package Pins                                                                                                                                                               ;
+----------+------------+----------+--------------------------------------------------+--------+--------------+---------+------------+-----------------+----------+--------------+
; Location ; Pad Number ; I/O Bank ; Pin Name/Usage                                   ; Dir.   ; I/O Standard ; Voltage ; I/O Type   ; User Assignment ; Bus Hold ; Weak Pull Up ;
+----------+------------+----------+--------------------------------------------------+--------+--------------+---------+------------+-----------------+----------+--------------+
; A2       ;            ;          ; NC                                               ;        ;              ;         ; --         ;                 ; --       ; --           ;
; A3       ; 510        ; 9        ; ~ALTERA_DATA0~ / RESERVED_INPUT_WITH_WEAK_PULLUP ; input  ; 2.5 V        ;         ; Column I/O ; N               ; no       ; On           ;
; A4       ; 505        ; 8        ; RESERVED_INPUT                                   ;        ;              ;         ; Column I/O ;                 ; no       ; Off          ;
; AC8      ; 187        ; 3        ; MSEL3                                            ; input  ;              ;         ; Dedicated  ;                 ; --       ; --           ;
; AE7      ; 120        ; 3        ; ~ALTERA_NCEO~                                    ; output ; 2.5 V        ;         ; Row I/O    ; N               ; no       ; Off          ;
; B9       ; 300        ; 8        ; y                                                ; output ; 2.5 V        ;         ; Column I/O ; Y               ; no       ; Off          ;
+----------+------------+----------+--------------------------------------------------+--------+--------------+---------+------------+-----------------+----------+--------------+
"""

VO = """// y\t=>  Location: PIN_B9,\t I/O Standard: 2.5 V,\t Current Strength: Default
// ~ALTERA_DATA0~\t=>  Location: PIN_A3,\t I/O Standard: 2.5 V,\t Current Strength: Default
hard_block auto_generated_inst();

// Location: IOOBUF_X34_Y91_N23
cycloneiv_io_obuf \\y~output (
\t.i(\\u1~combout ),
\t.o(\\y~output_o ));
"""

IBIS = """<general name="per_pin_rlc_package">
\t<data_type name="EP4CGX150DF31">
[Number of Pins]         6
[Pin Numbers]
|[Pin Name]  Net Number    Net Name   Net's All Pins
A3            | 1          X_B9_X_UDATA00            A3
A4            | 2          X_B8_X_LVDST_10N          A4
AC8           | 3          X_B3_MSEL3_X              AC8
AE7           | 4          D_B3_X_LVDSB_01N          AE7
B9            | 5          X_B7_X_LVDST_34P          B9
AA10          | 6          VCC                       AA10
|AA14
[Model Data]
"""


def test_parsers():
    import pins_register as P
    opn, rows = P.parse_fit_rpt(FIT)
    assert rows["A3"]["pad_number"] == 510 and rows["A3"]["bank"] == "9" and rows["A3"]["func_names"] == ["~ALTERA_DATA0~"]
    assert rows["A2"]["bonded"] is False and rows["A4"]["usage_default"] == "RESERVED_INPUT"
    assert rows["A2"]["bank"] is None and rows["A2"]["io_type"] is None       # '--' and blank = absent, never a value
    assert "DIFFIO_B1n" in rows["AE7"]["func_names"] and rows["AE7"]["pin_type"] == "Dual Purpose Pin"
    vo = P.parse_vo(VO)
    assert vo == {"B9": {"tile_x": 34, "tile_y": 91, "z": 23, "io_site": "IOOBUF_X34_Y91_N23"}}
    dev, n, nets = P.parse_ibis(IBIS)
    assert dev == "EP4CGX150DF31" and n == 6 and nets["AA14"] == "VCC" and nets["A4"] == "X_B8_X_LVDST_10N"
    d = P.decode_ibis_net("X_B8_X_LVDST_10N")
    assert d == {"func": "LVDST_10N", "bank": "8", "side": "top"}
    assert P.decode_ibis_net("X_QL1_RX6N_X")["side"] == "left"
    assert P.special_of(["MSEL3"]) == "config" and P.special_of(["LVDST_34P"]) == "none" and P.special_of(["VCC"]) == "power"
    assert P.split_part("EP4CGX150DF31C7") == ("EP4CGX150", "DF31", "EP4CGX150DF31")


def test_merge_flags_conflicts_and_keeps_sources():
    import pins_register as P
    _opn, fit = P.parse_fit_rpt(FIT)
    _dev, _n, nets = P.parse_ibis(IBIS)
    ibis = {p: {"ibis_net": n, "bank": P.decode_ibis_net(n).get("bank"), "side": P.decode_ibis_net(n).get("side"),
                "func_names": [P.decode_ibis_net(n)["func"]], "bonded": True} for p, n in nets.items()}
    rows = P.build_rows("cycloneiv", "EP4CGX150DF31", "EP4CGX150", "DF31",
                        {"fit.rpt": fit, "vo": P.parse_vo(VO), "ibis": ibis}, {"EP4CGX150DF31C7"}, {"xmax": 117, "ymax": 91})
    by = {r["pin"]: r for r in rows}
    assert by["B9"]["tile_y"] == 91 and by["B9"]["side"] == "top" and by["B9"]["source"]["tile_x"] == ["vo"]
    assert by["B9"]["source"]["bank"] == ["fit.rpt", "ibis"] and by["B9"]["bank"] == "8"
    assert any(c["field"] == "bank" for c in by["B9"]["conflicts"])     # fit.rpt bank 8 vs ibis bank 7: flagged, not resolved
    assert by["AE7"]["conflicts"] is None and by["AE7"]["special"] == "config" and "NCEO" in by["AE7"]["func_names"]
    assert by["A2"]["bonded"] is False and by["AA14"]["special"] == "power" and by["AA14"]["source"]["func_names"] == ["ibis"]


def test_register_round_trip(tmp_path, monkeypatch):
    db_path = str(tmp_path / "pins.db")
    monkeypatch.setenv("PLURIBUS_SQLITE_PATH", db_path)
    import db
    db.BACKEND, db._SQPATH, db._engine = "sqlite", db_path, None
    import pins_register as P
    corpus = tmp_path / "corpus"
    for name in ("d1", "d2"):
        d = corpus / name
        d.mkdir(parents=True)
        (d / "design.toml").write_text('device = "EP4CGX150DF31C7"\n')
        (d / "fit.rpt").write_text(FIT)
        (d / "postfit.vo").write_text(VO)
    ibis = tmp_path / "ibis"
    ibis.mkdir()
    (ibis / "ep4cgx150df31.xml").write_text(IBIS)
    n = P.register("cycloneiv", str(corpus), str(ibis), geom={"xmax": 117, "ymax": 91})
    assert n == 8                                     # 6 fit.rpt pins + 2 IBIS-only power balls
    import schema as S
    with db.engine().connect() as conn:
        rows = {r.pin: r for r in conn.execute(select(S.device_pins))}
        assert rows["B9"].io_site == "IOOBUF_X34_Y91_N23" and rows["B9"].evidence_id is not None
        assert rows["A3"].opns == ["EP4CGX150DF31C7"] and rows["A3"].ibis_net == "X_B9_X_UDATA00"
        ev = conn.execute(select(S.evidence.c.kind)).scalar()
        assert ev == "vendor-decode"
    assert P.register("cycloneiv", str(corpus), str(ibis), geom={"xmax": 117, "ymax": 91}) == 8   # always-rebuild
    db._engine = None
