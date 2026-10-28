"""Pluribus — SQLAlchemy Core schema (all backends).

TEXT[] PostgreSQL arrays are stored as JSON lists (JSON type).
JSONB  PostgreSQL columns are stored as JSON (JSON type).
SERIAL / BIGSERIAL become Integer / BigInteger with autoincrement.

Usage
-----
  import schema
  schema.init()          # create all tables (IF NOT EXISTS)
  schema.drop_all()      # drop all tables (for full rebuild)
"""

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Index,
    Integer, JSON, LargeBinary, MetaData, SmallInteger, String, Table, Text,
    UniqueConstraint,
)

metadata = MetaData()

# ── 1. Netlist layer ──────────────────────────────────────────────────────────

bitstreams = Table("bitstreams", metadata,
    Column("id",               Integer,  primary_key=True, autoincrement=True),
    Column("label",            Text,     nullable=False, unique=True),
    Column("filename",         Text,     nullable=False),
    Column("device",           Text,     nullable=False),
    Column("package",          Text,     nullable=False),
    Column("diamond_version",  Text),    # e.g. "3.14.0.201", NULL if unknown
    Column("loaded_at",        DateTime(timezone=True)),
)

nets = Table("nets", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("name",      Text,    nullable=False),
    UniqueConstraint("bitstream", "name"),
)

ffs = Table("ffs", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("cell", Text, nullable=False),
    Column("clk",  Text),
    Column("ce",   Text),
    Column("d",    Text),
    Column("q",    Text),
    Column("lsr",  Text),
    # Family-specific storage-element kind (NULL for MachXO2).  GOWIN records the
    # apycula dff/latch kind (DFF/DFFR/DL/DLC/…) so the Verilog emitter can tell a
    # level-sensitive latch (DL*) from an edge-triggered flop.
    Column("dtype", Text),
    # NULL = D resolved.  Else why D fell back to a constant (a missing connection,
    # counted as a fault): 'F-unconnected' | 'M-unconnected' | 'const-0' (MachXO2).
    Column("d_fault", Text),
    UniqueConstraint("bitstream", "cell"),
)

# init is a binary truth-table string, MSB-first (#63): 16 chars (2**4) for
# every LUT4 family (MachXO2/ECP5/Gowin/Anlogic), 64 chars (2**6) for Cyclone
# V's ALM-half LUT (a-f). String(64) bounds the widest case; SQLite ignores the
# VARCHAR(N) length, Postgres enforces it, so the bound is load-bearing there.
luts = Table("luts", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("cell",  Text,      nullable=False),
    Column("init",  String(64), nullable=False),
    Column("a",     Text), Column("b", Text), Column("c", Text), Column("d", Text),
    # 5th/6th input: Cyclone V ALM-half only (e, f). NULL for every 4-input
    # family, exactly like a/b/c/d when a pin is unused.
    Column("e",     Text),
    Column("f",     Text),
    Column("z",     Text),
    Column("deps",  JSON),   # TEXT[] → JSON list
    Column("fn",    Text),
    UniqueConstraint("bitstream", "cell"),
)

# GOWIN ALU (carry/arithmetic) cells.  Empty for MachXO2 (CCU2 carry is folded
# into the LUT/FF recovery there).  Each row is one ALU bit with the apycula
# vendor-model ports (ALU_MODE + I0/I1/I3/CIN and the SUM/COUT output nets) so the
# Verilog emitter can instantiate the exact vendor ALU behaviour and drive F.
alu_cells = Table("alu_cells", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("cell",   Text, nullable=False),
    Column("mode",   Text),      # numeric ALU_MODE (0=ADD 3=NE 9=MULT …)
    Column("sum_net", Text),     # F output net when the cell exposes SUM (else NULL)
    Column("cout_net", Text),    # carry-out net (chains to the next cell's cin)
    Column("cin",    Text),
    Column("i0",     Text), Column("i1", Text), Column("i3", Text),
    UniqueConstraint("bitstream", "cell"),
)

mux_cells = Table("mux_cells", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("cell",   Text, nullable=False),
    Column("i0",     Text),      # first input net (O = S ? I1 : I0)
    Column("i1",     Text),      # second input net
    Column("sel",    Text),      # select signal
    Column("o",      Text),      # output net
    UniqueConstraint("bitstream", "cell"),
)

net_fanout = Table("net_fanout", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("net",       Text, nullable=False),
    Column("cell_type", Text, nullable=False),
    Column("cell",      Text, nullable=False),
    Column("pin",       Text, nullable=False),
    Column("out_net",   Text),
)
Index("idx_fanout_net", net_fanout.c.bitstream, net_fanout.c.net)
Index("idx_fanout_out", net_fanout.c.bitstream, net_fanout.c.out_net)

pad_map = Table("pad_map", metadata,
    Column("id",          Integer, primary_key=True, autoincrement=True),
    Column("bitstream",   Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("pin",         Integer, nullable=False),
    Column("label",       Text,    nullable=False),
    Column("row",         Integer), Column("col", Integer), Column("pio", Text),
    Column("direction",   Text, nullable=False),
    Column("net_in",      Text),
    Column("net_out",     Text),
    Column("iostd",       Text),
    Column("drive",       Text),
    Column("pull",        Text),
    Column("si_function", Text),
    Column("conn_class",  Text),
    Column("chip_ref",    Text),
    Column("chip_pin",    Text),
    Column("chip_signal", Text),
    UniqueConstraint("bitstream", "pin"),
)

efb_ports = Table("efb_ports", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("port_name", Text, nullable=False),
    Column("net",       Text, nullable=False),
    # Direction AS OBSERVED IN THE ROUTING, not as the datasheet defines the
    # primitive: "out" means the EFB wire is the SOURCE of the arc, i.e. the block
    # drives this net into the fabric.  Recording what the bitstream shows keeps
    # this a measurement; inferring a port's datasheet direction would be a guess.
    #
    # Needed by #49: an EFB instantiation cannot be emitted without knowing which
    # ports are driven and which are driving, and the emitter must not invent it.
    Column("direction", Text),
    UniqueConstraint("bitstream", "port_name"),
)

ebr_ports = Table("ebr_ports", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("block", Text, nullable=False),
    Column("port",  Text, nullable=False),
    Column("role",  Text, nullable=False),
    Column("net",   Text),
    UniqueConstraint("bitstream", "block", "port"),
)

# EBR block-RAM initial contents recovered from the bitstream 0x72 sections
# (native decoder).  `block` is the physical EBR9K block name (R{row}C{col},
# same convention as ebr_ports); `wid` is the bitstream EBR write index that
# the block's EBR.WID config word decodes to (the RE key linking .bram_init
# <index> to a tile).  `word9` is the raw 9-bit physical word at `addr`
# (0..1023).  Logical word width / mode live in ebr_init_blocks.
ebr_init = Table("ebr_init", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("block", Text,    nullable=False),
    Column("wid",   Integer, nullable=False),
    Column("addr",  Integer, nullable=False),
    Column("word9", Integer, nullable=False),
    UniqueConstraint("bitstream", "block", "addr"),
)
Index("idx_ebr_init_block", ebr_init.c.bitstream, ebr_init.c.block)

# One row per initialised EBR block: the logical geometry (mode + data width +
# output-register mode) needed to regroup the raw 9-bit words into logical
# words, plus the write index and a non-zero-word count for quick triage.
ebr_init_blocks = Table("ebr_init_blocks", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("block",      Text,    nullable=False),
    Column("wid",        Integer, nullable=False),
    Column("mode",       Text),
    Column("data_width", Integer),
    Column("regmode_a",  Text),
    Column("regmode_b",  Text),
    Column("n_words",    Integer, nullable=False),
    Column("n_nonzero",  Integer, nullable=False),
    UniqueConstraint("bitstream", "block"),
)

# EFB (Embedded Function Block) config-register preloads from bitstream
# command 0x72 (docs/cmd-0x72.md).  `sel` is the peripheral selector
# (0x54=SPI, 0x5e=TC); `kind` is the decoded name; `payload` is the raw
# config-register bytes as a JSON list of ints.
efb_config = Table("efb_config", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("sel",     Integer, nullable=False),
    Column("kind",    Text),
    Column("length",  Integer, nullable=False),
    Column("payload", JSON,    nullable=False),  # list of byte ints
    UniqueConstraint("bitstream", "sel"),
)

clock_domains = Table("clock_domains", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("clk_net",  Text, nullable=False),
    Column("ff_cell",  Text, nullable=False),
    UniqueConstraint("bitstream", "clk_net", "ff_cell"),
)

# Anlogic EG4 (eagle_s20) tile-grid + per-tile CRAM occupancy (issue #67).
# One row per placed tile from the Tang-Dynasty fuse DB (scripts/anlogic_dbdecode.py):
# where it sits in the grid, where its bits live in the CRAM, and how many of
# those bits the bitstream sets (utilisation).  This is the structural floorplan
# recovered from an Anlogic bitstream; the LUT-init layer lands in `luts`, while
# the routing/mux layer (binary-encoded, needs the per-bit boolean expr) is not
# yet decoded (arcs stay empty for the anlogic family).
anlogic_tiles = Table("anlogic_tiles", metadata,
    Column("id",          Integer, primary_key=True, autoincrement=True),
    Column("bitstream",   Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("name",        Text,    nullable=False),
    Column("tile_type",   Text,    nullable=False),
    Column("x",           Integer, nullable=False),
    Column("y",           Integer, nullable=False),
    Column("start_frame", Integer, nullable=False),
    Column("start_bit",   Integer, nullable=False),
    Column("rows",        Integer, nullable=False),
    Column("cols",        Integer, nullable=False),
    Column("occupancy",   Integer, nullable=False, server_default="0"),
    UniqueConstraint("bitstream", "name"),
)
Index("idx_anlogic_tiles_type", anlogic_tiles.c.bitstream, anlogic_tiles.c.tile_type)

# ── 2. Analysis layer ─────────────────────────────────────────────────────────

reachability = Table("reachability", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("src",      Text,        nullable=False),
    Column("dst",      Text,        nullable=False),
    Column("min_hops", SmallInteger, nullable=False),
    UniqueConstraint("bitstream", "src", "dst"),
)
Index("idx_reach_src", reachability.c.bitstream, reachability.c.src)
Index("idx_reach_dst", reachability.c.bitstream, reachability.c.dst)

pad_ff_influence = Table("pad_ff_influence", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("pad_label", Text,        nullable=False),
    Column("ff_cell",   Text,        nullable=False),
    Column("min_hops",  SmallInteger, nullable=False),
    UniqueConstraint("bitstream", "pad_label", "ff_cell"),
)

patterns = Table("patterns", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("pattern_type", Text, nullable=False),
    Column("label",     Text),
    Column("detail",    JSON, nullable=False, server_default="{}"),
)

shift_reg_bits = Table("shift_reg_bits", metadata,
    Column("id",          Integer, primary_key=True, autoincrement=True),
    Column("pattern_id",  Integer, ForeignKey("patterns.id", ondelete="CASCADE"), nullable=False),
    Column("bit_index",   Integer, nullable=False),
    Column("ff_cell",     Text,    nullable=False),
    Column("q_net",       Text,    nullable=False),
    Column("clk_net",     Text),
    Column("load_en_net", Text),
)

ff_d_functions = Table("ff_d_functions", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    # ff_cell is unique PER bitstream, not globally — a bare unique=True here
    # collided cell names across bitstreams in a shared DB, so INSERT-OR-IGNORE
    # silently dropped every later bitstream's rows (data loss, caught by #60).
    Column("ff_cell",   Text,    nullable=False),
    Column("fn_expr",   Text),
    Column("depth",     Integer),
    Column("pad_inputs", JSON),  # TEXT[] → JSON list
    UniqueConstraint("bitstream", "ff_cell"),
)

# ── 3. Knowledge layer ────────────────────────────────────────────────────────

net_names = Table("net_names", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("net",         Text, nullable=False),
    Column("name",        Text, nullable=False),
    Column("description", Text),
    Column("confidence",  Text, nullable=False, server_default="speculative"),
    Column("source",      Text),
    Column("freq_mhz",    Float),   # clock frequency (from the net-annotation TSV)
    Column("updated_at",  DateTime(timezone=True)),
    UniqueConstraint("bitstream", "net"),
)

cell_names = Table("cell_names", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("cell",        Text, nullable=False),
    Column("name",        Text, nullable=False),
    Column("description", Text),
    Column("confidence",  Text, nullable=False, server_default="speculative"),
    UniqueConstraint("bitstream", "cell"),
)

spi_registers = Table("spi_registers", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("bank",      Text, nullable=False),
    Column("address",   Integer, nullable=False),
    Column("name",      Text, nullable=False),
    Column("description", Text),
    Column("bit_fields",  JSON, nullable=False, server_default="[]"),
    UniqueConstraint("bitstream", "bank", "address"),
)

open_questions = Table("open_questions", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("issue_num",    Integer),
    Column("title",        Text, nullable=False),
    Column("description",  Text),
    Column("status",       Text, nullable=False, server_default="open"),
    Column("related_nets",  JSON),  # TEXT[] → JSON list
    Column("related_cells", JSON),  # TEXT[] → JSON list
    Column("blocker",      Text),
    Column("updated_at",   DateTime(timezone=True)),
)

# ── 4. Extended analysis (reach2) ─────────────────────────────────────────────

reachability_rev = Table("reachability_rev", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("dst",      Text,        nullable=False),
    Column("src",      Text,        nullable=False),
    Column("min_hops", SmallInteger, nullable=False),
    UniqueConstraint("bitstream", "dst", "src"),
)
Index("idx_reach_rev_dst", reachability_rev.c.bitstream, reachability_rev.c.dst)
Index("idx_reach_rev_src", reachability_rev.c.bitstream, reachability_rev.c.src)

ff_cones = Table("ff_cones", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("ff_cell",   Text,        nullable=False),
    Column("cone_type", Text,        nullable=False),
    Column("net",       Text,        nullable=False),
    Column("min_hops",  SmallInteger, nullable=False),
    UniqueConstraint("bitstream", "ff_cell", "cone_type", "net"),
)
Index("idx_ff_cones_ff",  ff_cones.c.bitstream, ff_cones.c.ff_cell, ff_cones.c.cone_type)
Index("idx_ff_cones_net", ff_cones.c.bitstream, ff_cones.c.net, ff_cones.c.cone_type)

critical_paths = Table("critical_paths", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("src_ff",    Text, nullable=False),
    Column("dst_ff",    Text, nullable=False),
    Column("hops",      SmallInteger, nullable=False),
    Column("path_nets", JSON),  # TEXT[] → JSON list
    UniqueConstraint("bitstream", "src_ff", "dst_ff"),
)
Index("idx_crit_hops", critical_paths.c.bitstream, critical_paths.c.hops)

dominators = Table("dominators", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("ff_cell",  Text, nullable=False),
    Column("net",      Text, nullable=False),
    Column("n_paths",  Integer, nullable=False),
    UniqueConstraint("bitstream", "ff_cell", "net"),
)
Index("idx_dom_ff",  dominators.c.bitstream, dominators.c.ff_cell)
Index("idx_dom_net", dominators.c.bitstream, dominators.c.net)

# ── 5. Symbolic / reach3 layer ────────────────────────────────────────────────

lut_symbolic = Table("lut_symbolic", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("lut_cell",  Text,    nullable=False),
    Column("expr",      Text,    nullable=False),
    Column("depth",     Integer, nullable=False, server_default="0"),
    UniqueConstraint("bitstream", "lut_cell"),
)

clock_crossings = Table("clock_crossings", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("dst_ff",  Text,    nullable=False),
    Column("dst_clk", Text,    nullable=False),
    Column("src_ff",  Text,    nullable=False),
    Column("src_clk", Text,    nullable=False),
    Column("hops",    Integer, nullable=False),
    UniqueConstraint("bitstream", "dst_ff", "src_ff"),
)
Index("idx_cc_dst", clock_crossings.c.bitstream, clock_crossings.c.dst_ff)
Index("idx_cc_src", clock_crossings.c.bitstream, clock_crossings.c.src_ff)

ebr_buses = Table("ebr_buses", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("block",     Text,    nullable=False),
    Column("bus_role",  Text,    nullable=False),
    Column("bit_index", Integer, nullable=False),
    Column("port",      Text,    nullable=False),
    Column("net",       Text),
    UniqueConstraint("bitstream", "block", "bus_role", "bit_index"),
)

net_stats = Table("net_stats", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("net",         Text,    nullable=False),
    Column("fanout",      Integer, nullable=False, server_default="0"),
    Column("fanin",       Integer, nullable=False, server_default="0"),
    Column("is_clock",    Boolean, nullable=False, server_default="0"),
    Column("is_const",    Boolean, nullable=False, server_default="0"),
    Column("is_boundary", Boolean, nullable=False, server_default="0"),
    UniqueConstraint("bitstream", "net"),
)

cone_hashes = Table("cone_hashes", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("ff_cell",   Text, nullable=False),
    Column("cone_hash", Text, nullable=False),
    Column("cone_size", Integer, nullable=False),
    UniqueConstraint("bitstream", "ff_cell"),
)
Index("idx_cone_hash", cone_hashes.c.bitstream, cone_hashes.c.cone_hash)

const_nets = Table("const_nets", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("net",         Text, nullable=False),
    Column("const_value", Text, nullable=False),
    UniqueConstraint("bitstream", "net"),
)

# ── 6. Routing layer ─────────────────────────────────────────────────────────

arcs = Table("arcs", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("tile_row",    Integer, nullable=False),
    Column("tile_col",    Integer, nullable=False),
    Column("sink_wire",   Text, nullable=False),
    Column("source_wire", Text, nullable=False),
    Column("sink_net",    Text),
    Column("source_net",  Text),
    Column("sink_gx",   Integer), Column("sink_gy",   Integer), Column("sink_gid",   Integer),
    Column("source_gx", Integer), Column("source_gy", Integer), Column("source_gid", Integer),
)
Index("idx_arcs_bs",     arcs.c.bitstream)
Index("idx_arcs_sink",   arcs.c.bitstream, arcs.c.sink_net)
Index("idx_arcs_source", arcs.c.bitstream, arcs.c.source_net)
Index("idx_arcs_tile",   arcs.c.bitstream, arcs.c.tile_row, arcs.c.tile_col)

hpbx_branches = Table("hpbx_branches", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("tile_row",  Integer, nullable=False),
    Column("tile_col",  Integer, nullable=False),
    Column("track",     Text, nullable=False),
    Column("local_net", Text, nullable=False),
    UniqueConstraint("bitstream", "tile_row", "tile_col", "track"),
)
Index("idx_hpbx_net", hpbx_branches.c.bitstream, hpbx_branches.c.local_net)

clock_domain_summary = Table("clock_domain_summary", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("clk_net",    Text,    nullable=False),
    Column("ff_count",   Integer, nullable=False, server_default="0"),
    Column("hpbx_track", Text),
    Column("pll_output", Text),
    Column("freq_mhz",   Float),
    UniqueConstraint("bitstream", "clk_net"),
)
Index("idx_cds_track", clock_domain_summary.c.bitstream, clock_domain_summary.c.hpbx_track)


# ── CDC synchroniser table (reach4) ──────────────────────────────────────────

cdc_synchronisers = Table("cdc_synchronisers", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("src_ff",    Text, nullable=False),
    Column("src_clk",   Text, nullable=False),
    Column("stage1_ff", Text, nullable=False),
    Column("stage2_ff", Text, nullable=False),
    Column("dst_clk",   Text, nullable=False),
    UniqueConstraint("bitstream", "stage1_ff"),
)

# ── Device identification fingerprints (not tied to a lifted bitstream) ──────
# Structural signatures for identifying an unknown bitstream's device family by
# comparison, independent of the Lattice lifter pipeline above. First use:
# Altera Cyclone V (no IDCODE in the raw bitstream and no IDCODE in Quartus's
# Tcl API, so die family is narrowed by header framing and
# near-empty-design .rbf size instead). Rows are ground truth generated by
# compiling a trivial design per part in the vendor toolchain, not derived from
# an unknown image -- vendor-sourced data, same status as device-db/.
#
# rbf_size is real signal: cross-checked against the Cyclone V datasheet's
# (683801) published uncompressed .rbf size table, matches byte-for-byte --
# but only resolves to die-size-class granularity (several part numbers share
# one die's fabric size, same limit Mistral's 7-die set already has).
#
# leading_ff_len is NOT a die signature: it is a quartus_cpf generation-option
# artifact (default options give the same value for every die). Kept as a raw
# observation per rbf_mode, not for cross-die identification.

device_fingerprints = Table("device_fingerprints", metadata,
    Column("id",              Integer, primary_key=True, autoincrement=True),
    Column("vendor",          Text,    nullable=False),  # e.g. "altera"
    Column("family",          Text,    nullable=False),  # e.g. "Cyclone V"
    Column("die",             Text,    nullable=False),  # e.g. "e50f"
    Column("part",            Text,    nullable=False),  # e.g. "5CEBA4U19C8"
    Column("toolchain",       Text,    nullable=False),  # e.g. "quartus-25.1std.0.1129"
    Column("probe_design",    Text,    nullable=False),  # name/hash of the source design compiled
    Column("rbf_mode",        Text,    nullable=False),  # "uncompressed" | "compressed"
    Column("rbf_size",        Integer, nullable=False),
    Column("leading_ff_len",  Integer, nullable=False),
    Column("header_entropy",  Float),
    Column("first_payload_byte", Text),
    Column("generated_at",    DateTime(timezone=True)),
    UniqueConstraint("vendor", "part", "toolchain", "probe_design", "rbf_mode"),
)

# ── Cyclone V device data (vendored, Mistral-derived) ────────────────────────
# Altera/Intel Cyclone V tile/routing database, same role for this family as
# device-db/ is for Lattice: engine data, not board data, PRISTINE once
# imported. Source is Project Mistral's (Ravenslofty/mistral) plain-text
# generator inputs under mistral/data/*.txt(.xz) -- NOT the compiled cvd-*.cc
# C++ structs, which are mistral's own codegen output from that same text.
# Imported by scripts/cyclonev_db_import.py. Never hand-edit these tables --
# corrections go in a cyclonev db_overrides equivalent if one is ever needed,
# following the same pattern as device-db/'s scripts/db_overrides.py.
#
# Scope (2026-10-23 session): die-level geometry + the per-die scalar/array
# fields die_info carries in cyclonev.h (cram size, frame size, pram sizes,
# noedcrc zones, postambles, column types, x_to_bx) -- everything
# cv-files.cc's rbf_load/rbf_save (the compression codec) needs. The larger
# per-node/per-mux tables (cv-bmux.cc/cv-rmux.cc scope, e50f-r.txt.xz /
# e50f-l.txt.xz / e50f-p2r.txt etc.) are out of scope this session -- see
# docs/bluebird.md.

cv_dies = Table("cv_dies", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("name",          Text,    nullable=False, unique=True),  # e.g. "e50f"
    Column("cram_sx",       Integer, nullable=False),
    Column("cram_sy",       Integer, nullable=False),
    Column("tile_sx",       Integer, nullable=False),
    Column("tile_sy",       Integer, nullable=False),
    Column("hps_x",         Integer, nullable=False),
    Column("hps_y",         Integer, nullable=False),
    Column("ctrl_x",        Integer, nullable=False),
    Column("ctrl_y",        Integer, nullable=False),
    Column("frame_size",    Integer, nullable=False),
    Column("postamble_1",   Integer, nullable=False),
    Column("postamble_2",   Integer, nullable=False),
    Column("default_oram",    JSON, nullable=False),  # 12 x uint64, as decimal strings (exceed JS/JSON safe int)
    Column("pram_sizes",      JSON, nullable=False),  # 32 x uint16
    Column("noedcrc_zones",   JSON, nullable=False),  # 12 x uint16 (die's own count may be < 12; padded with trailing cram_sx)
    Column("x_to_bx",         JSON, nullable=False),  # tile_sx x uint16, column -> bit-x
    Column("column_types",    JSON, nullable=False),  # tile_sx x tile_type_t name (text, e.g. "T_LAB")
    Column("source_file",   Text,    nullable=False),  # mistral path this was imported from, e.g. "libmistral/cvd-e50f.cc"
    Column("imported_at",   DateTime(timezone=True)),
)

# PRAM (peripheral RAM / fixed-block-position) strips: parsed directly from
# data/<die>-pram.txt, the generator/pram.cc input -- not from cvd-*.cc.
# One row per "strip.start-end block x.y [instance [var]]" line.
cv_pram_strips = Table("cv_pram_strips", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("die",        Integer, ForeignKey("cv_dies.id", ondelete="CASCADE"), nullable=False),
    Column("strip",      Integer, nullable=False),
    Column("start",      Integer, nullable=False),
    Column("end",        Integer, nullable=False),
    Column("block",      Text,    nullable=False),  # e.g. "fpll", "cmuxc", "dqs16"
    Column("pos_x",      Integer, nullable=False),
    Column("pos_y",      Integer, nullable=False),
    Column("instance",   Integer, nullable=False, server_default="0"),
    Column("var",        Integer, nullable=False, server_default="0"),
)
Index("idx_cv_pram_die_block", cv_pram_strips.c.die, cv_pram_strips.c.block)

# ── Cyclone V routing-node tables (2026-10-23, 2nd session) ──────────────────
# Imported by scripts/cyclonev_db_import_routes.py from Mistral's plain-text
# generator inputs: data/<die>-r.txt.xz (routes), -l.txt.xz (lines), -d.txt.xz
# (rdriver), -p2r.txt (port-to-rnode), -p2p.txt (port-to-port).
#
# BOOTSTRAP/VERIFICATION SOURCE, NOT A PERMANENT DEPENDENCY. These 5 files are
# Mistral's own curated routing ground truth, borrowed the same way
# cv_pram_strips borrows -pram.txt. The longer-term, independent source for
# this same ground truth is pluribus's own Quartus-based fuzzing campaign
# (compile known test designs that exercise specific routing patterns,
# decompile, cross-check against the known design -- same method as
# scripts/cyclonev_dsp_fuzz.py already used for DSP operational modes, and
# scripts/run_prjtrellis_fuzz.py for the Lattice side), not an indefinite read
# of another project's data/ tree. That campaign is explicitly NOT attempted
# this session -- the routing-pattern space is far larger than DSP modes, and
# it is real future work, not a bug in this import.
#
# Rnode/block/port TYPE NAMES are stored as the literal text tokens parsed
# from the files (e.g. "SCLK", "GCLK", "LAB"), not as integer codes against
# Mistral's cv-rnodetypes.ipp/cv-blocktypes.ipp enums -- cv-porttypes.ipp in
# particular is not even a checked-in file: it is generated at Mistral BUILD
# time by tools/porttypes_to_source.py scanning every die's -p2r.txt/-p2p.txt
# for port-name tokens, so depending on it would mean building Mistral just to
# get a name list pluribus can already read out of the same source text.
#
# Per-row repeating arrays (route mux sources, line fanout targets) are JSON
# lists on the parent row, not child tables -- same "TEXT[] -> JSON"
# convention cv_dies already uses for pram_sizes/x_to_bx. e50f alone has
# ~695k route rows (avg 17 sources) and ~626k line rows (avg 19 targets); a
# fully normalised child-table design would add ~24M rows for one die's
# routing layer with no query this project currently needs that a JSON array
# on the parent row doesn't already serve.

# One row per data/<die>-r.txt.xz line: the routing mux occupying a
# destination rnode. `pattern` indexes Mistral's rmux_patterns[74] table
# (generator/routes.cc) -- 0..69 are the base patterns, 70..73 are pattern 6's
# four fixed-default sub-variants ("6.0".."6.3" in the text, encoded there as
# `pat = 70 + patopt`). NULL pattern = a '-' line: a terminal rnode with no
# mux (82,932/695,446 e50f rows -- e.g. SCLK sector-clock leaves with no
# further fan-in). `sources` is a JSON list of up to 44 {"slot", "type", "x",
# "y", "z"} objects -- the mux's selectable inputs, slot-indexed per
# rmux_patterns[pattern].bits.
cv_route_muxes = Table("cv_route_muxes", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("die",        Integer, ForeignKey("cv_dies.id", ondelete="CASCADE"), nullable=False),
    Column("rn_type",     Text,    nullable=False),  # e.g. "SCLK", "DCMUX"
    Column("rn_x",        Integer, nullable=False),
    Column("rn_y",        Integer, nullable=False),
    Column("rn_z",        Integer, nullable=False),
    Column("pattern",     Integer),                  # NULL = no mux ('-' line)
    Column("fw_pos",      Integer, nullable=False, server_default="0"),  # cram frame-word position, 0 if no pattern
    Column("sources",     JSON,    nullable=False, server_default="[]"),
)
Index("idx_cv_route_muxes_rn", cv_route_muxes.c.die, cv_route_muxes.c.rn_type, cv_route_muxes.c.rn_x, cv_route_muxes.c.rn_y, cv_route_muxes.c.rn_z)

# One row per data/<die>-l.txt.xz line: a source rnode's electrical line model
# (tc1/tc2/r85 timing-corner resistances, c_farads already scaled by
# generator/lines.cc's *1e-15, length in tiles) plus its fan-out. `targets` is
# a JSON list of up to 64 {"pos", "type", "x", "y", "z", "subslot", "cap"}
# objects -- a target is EITHER a downstream rnode (type/x/y/z set, cap null)
# OR a bare capacitance tap (type/x/y/z null, cap set), per lines.cc's
# "pos:number" vs "pos:TYPE.x.y.z:subslot" grammar branch.
cv_route_lines = Table("cv_route_lines", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("die",        Integer, ForeignKey("cv_dies.id", ondelete="CASCADE"), nullable=False),
    Column("rn_type",     Text,    nullable=False),
    Column("rn_x",        Integer, nullable=False),
    Column("rn_y",        Integer, nullable=False),
    Column("rn_z",        Integer, nullable=False),
    Column("tc1",         Float,   nullable=False),
    Column("tc2",         Float,   nullable=False),
    Column("r85",         Float,   nullable=False),
    Column("c_farads",    Float,   nullable=False),
    Column("driver_position", Integer, nullable=False, server_default="0"),
    Column("length",      Integer, nullable=False, server_default="0"),
    Column("targets",     JSON,    nullable=False, server_default="[]"),
)
Index("idx_cv_route_lines_rn", cv_route_lines.c.die, cv_route_lines.c.rn_type, cv_route_lines.c.rn_x, cv_route_lines.c.rn_y, cv_route_lines.c.rn_z)

# One row per data/<die>-d.txt.xz line: the pair of named driver electrical
# models (generator/drivers.cc driver_type_names, e.g. "gout_labcell_a",
# "h14_a") assigned to an rnode's left/right half -- same name in both columns
# when the line gives only one. Electrical driver MODELS themselves
# (speed/temp/shape tables) live in Mistral's separate driver-models.txt.xz
# and are out of scope here -- this records only which named driver an rnode
# uses, not that driver's analog characteristics.
cv_route_drivers = Table("cv_route_drivers", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("die",        Integer, ForeignKey("cv_dies.id", ondelete="CASCADE"), nullable=False),
    Column("rn_type",     Text,    nullable=False),
    Column("rn_x",        Integer, nullable=False),
    Column("rn_y",        Integer, nullable=False),
    Column("rn_z",        Integer, nullable=False),
    Column("driver_left",  Text,   nullable=False),
    Column("driver_right", Text,   nullable=False),
)
Index("idx_cv_route_drivers_rn", cv_route_drivers.c.die, cv_route_drivers.c.rn_type, cv_route_drivers.c.rn_x, cv_route_drivers.c.rn_y, cv_route_drivers.c.rn_z)

# One row per data/<die>-p2r.txt port-instance-bit entry: binds a block port
# (pnode: block type + x/y + optional instance + port type + optional bit
# index) to the routing node it connects to. rn_* columns are NULL for a '-'
# entry (generator/p2r.cc: unconnected bit in an instance/bit range).
cv_p2r = Table("cv_p2r", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("die",        Integer, ForeignKey("cv_dies.id", ondelete="CASCADE"), nullable=False),
    Column("block_type",  Text,    nullable=False),  # e.g. "CMUXCR", "LAB"
    Column("block_x",     Integer, nullable=False),
    Column("block_y",     Integer, nullable=False),
    Column("block_instance", Integer),  # NULL if the port has no per-instance range
    Column("port_type",   Text,    nullable=False),  # e.g. "clkin", "aclr"
    Column("port_bit",    Integer),     # NULL if the port has no per-bit range
    Column("rn_type",     Text),
    Column("rn_x",        Integer),
    Column("rn_y",        Integer),
    Column("rn_z",        Integer),
)
Index("idx_cv_p2r_block", cv_p2r.c.die, cv_p2r.c.block_type, cv_p2r.c.block_x, cv_p2r.c.block_y)
Index("idx_cv_p2r_rn",    cv_p2r.c.die, cv_p2r.c.rn_type, cv_p2r.c.rn_x, cv_p2r.c.rn_y, cv_p2r.c.rn_z)

# One row per data/<die>-p2p.txt line: a direct port-to-port connection that
# bypasses the routing fabric entirely (generator/p2p.cc) -- e.g. a fixed
# CTRL block output wired straight to a GPIO buffer input.
# src/dst_port_type is NULL for a bare block+instance reference with no port
# at all (nodes.cc lookup_p: the ':porttype' suffix is optional -- 272/1755
# e50f lines are e.g. "DQS16.000.016.0" with no port, PNONE in Mistral's enum).
cv_p2p = Table("cv_p2p", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("die",        Integer, ForeignKey("cv_dies.id", ondelete="CASCADE"), nullable=False),
    Column("src_block_type", Text, nullable=False),
    Column("src_block_x",    Integer, nullable=False),
    Column("src_block_y",    Integer, nullable=False),
    Column("src_block_instance", Integer),
    Column("src_port_type",  Text),
    Column("src_port_bit",   Integer),
    Column("dst_block_type", Text, nullable=False),
    Column("dst_block_x",    Integer, nullable=False),
    Column("dst_block_y",    Integer, nullable=False),
    Column("dst_block_instance", Integer),
    Column("dst_port_type",  Text),
    Column("dst_port_bit",   Integer),
)
Index("idx_cv_p2p_src", cv_p2p.c.die, cv_p2p.c.src_block_type, cv_p2p.c.src_block_x, cv_p2p.c.src_block_y)
Index("idx_cv_p2p_dst", cv_p2p.c.die, cv_p2p.c.dst_block_type, cv_p2p.c.dst_block_x, cv_p2p.c.dst_block_y)

# ── Cyclone V block-mux tables (2026-10-23, 3rd session) ─────────────────────
# Imported by scripts/cyclonev_db_import_blockmux.py from Mistral's 21
# data/<x>-mux.txt generator inputs (generator/*.cc's own loader is the
# compiled consumer; tools/mux_to_source.py is the one-step-removed reference
# PRODUCER-side grammar spec this import follows -- same "read the producer,
# not the compiled consumer" discipline as cv_route_muxes et al.).
#
# NOT PER-DIE, unlike cv_route_muxes/cv_route_lines/cv_route_drivers/cv_p2r/
# cv_p2p. Verified against the loader call sites (mux_to_source.py lines
# 219-240): load_mux_data() takes no chip/die argument, mux_to_source.py's own
# CLI takes only a data-dir, and libmistral/cv-bmux-data.cc (the compiled
# output) is built ONCE and linked into mistral as plain file-scope arrays --
# no per-die selection anywhere in the consumer either. These are block-mux
# DEFINITIONS: fixed bit positions/encodings for a mux that exists identically
# in every Cyclone V die (the die only supplies how many of each block exist,
# via cv_dies/the tile grid -- not what bits a given mux decodes to).
#
# BOOTSTRAP/VERIFICATION SOURCE, NOT A PERMANENT DEPENDENCY -- same status as
# cv_route_muxes (see that table's comment): useful today, not meant to be
# pluribus's permanent source of Cyclone V block-mux truth long-term. A
# Quartus-fuzzing campaign covering LAB/M10K/DSP/GPIO/PLL/HSSI muxes is real
# future work (docs/cyclonev-blockmux-status.md), not attempted this session.
#
# TABLE SHAPE: one row per mux_to_source.py `nm` dict (one dict per non-
# indented line in a *-mux.txt file, AFTER lab_expand() for lab/mlab's 'i'
# subtype). Follows cv_route_muxes's convention: value->name/number mappings
# (stype m/n) and the per-span bit-position rows are JSON arrays on the
# PARENT row, not child tables -- 4,650 source lines total across all 21
# files (the largest, hip-mux.txt, is 900 lines) is nowhere near route-table
# scale, but normalising bits/values into child tables would still add
# thousands of rows for zero query this project currently needs that the
# JSON arrays don't already serve, so the same convention applies unchanged.
#
# `dump_target` is the compiled bm_<dump_target>[] array name a row would
# land in (e.g. "cmuxvr", "cmuxvg", "lab"), NOT always the source file's base
# name: cmuxv-mux.txt and cmuxh-mux.txt each feed TWO dump_muxes() calls
# filtered by subtype ('r'/'R' -> cmuxvr, 'g'/'G' -> cmuxvg) producing two
# distinct compiled arrays from one file -- dump_target disambiguates that;
# source_file + subtype still records true provenance.
#
# ram_space: "oram" (opt-mux.txt only, device-wide 1D positions),
# "pram" (17 files, peripheral-instance 1D positions), or "cram" (lab, mlab,
# m10k, dsp, hps_clocks -- 2D x.y configuration-RAM coordinates, is_2d=True in
# the loader). bits is a JSON list of `span` rows, each itself a list of
# `bcount` positions -- a position is an int for oram/pram, a [x,y] pair for
# cram, matching load_mux_data()'s `w` closure exactly.
#
# stype: 'b' (bool), 'm' (mux, named values), 'n' (mux, numeric values),
# 'r' (RAM -- raw bits, no value table). variant defaults to -1 and is
# overridden per-subtype only for gpio ({'x':1,'X':0,'s':1}) and pma3
# ({'t':1,'b':0}) -- see mux_to_source.py's load_mux_data() call arguments,
# reproduced verbatim in scripts/cyclonev_db_import_blockmux.py, not
# re-derived.
#
# values is a JSON list of [hex_value, name_or_number] pairs (stype m: name
# is text; stype n: name is itself numeric) for stype m/n rows, else NULL.
# default_value_idx mirrors the loader's 'def' field: for stype b/r it is the
# literal default bit value (0, -1 for all-ones "+", or the parsed hex
# suffix); for stype m/n it is the INDEX into `values` of the row marked with
# a trailing '!' (NULL if the mux declares no default at all, which is the
# bcount-underlying "no explicit default" case the loader itself represents
# as -2 in dump_muxes() -- stored here as NULL rather than copying that sentinel).
#
# (dump_target, mux) is NOT unique, confirmed against the real files, not
# assumed: hssi-mux.txt's "i pcs8g_digi_tx_plane_bonding_consumption" and
# m10k-mux.txt's "g b_dmy_delay" each appear TWICE under the identical
# subtype+name with different bit positions (distinct PMA/EMIF-channel
# instances the source files don't disambiguate by name) -- so even
# (dump_target, subtype, mux) is not a safe unique key. No UniqueConstraint
# here; `id` plus the indexes below is the only identity, same as
# cv_route_muxes/cv_route_lines/etc. already settled for the same reason.
cv_block_muxes = Table("cv_block_muxes", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("source_file",   Text,    nullable=False),  # e.g. "gpio-mux.txt"
    Column("dump_target",   Text,    nullable=False),  # e.g. "cmuxvr", "lab"
    Column("ram_space",     Text,    nullable=False),  # "oram" | "pram" | "cram"
    Column("subtype",       Text,    nullable=False),  # single-char token, e.g. "i", "g", "r"
    Column("mux",           Text,    nullable=False),  # mux name, e.g. "tdff0"
    Column("stype",         Text,    nullable=False),  # "b" | "m" | "n" | "r"
    Column("bcount",        Integer, nullable=False),
    Column("span",          Integer, nullable=False),
    Column("variant",       Integer, nullable=False, server_default="-1"),
    Column("is_2d",         Boolean, nullable=False, server_default="0"),
    Column("bits",          JSON,    nullable=False),  # span x bcount positions
    Column("values",        JSON),                     # [[hex_value, name|num], ...], stype m/n only
    Column("default_value", Integer),                  # stype b/r literal default; NULL = none declared
    Column("default_value_idx", Integer),               # stype m/n: index into `values`; NULL = none declared
)
Index("idx_cv_block_muxes_file", cv_block_muxes.c.source_file)
Index("idx_cv_block_muxes_target", cv_block_muxes.c.dump_target)
Index("idx_cv_block_muxes_mux", cv_block_muxes.c.dump_target, cv_block_muxes.c.mux)

# Cyclone V hard-block instances (M10K / MLAB RAM, DSP, PLL): one row per vendor atom.
# `data` = JSON {kind, params, pins, outs, init, unmodelled}; verilog.py instantiates the
# vendor primitive from it.  Records: lifters/cyclonev_hard.py.
cv_hard_cells = Table("cv_hard_cells", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("cell",      Text, nullable=False),
    Column("kind",      Text, nullable=False),
    Column("data",      JSON, nullable=False),
    UniqueConstraint("bitstream", "cell"),
)

# ── Post-fit oracle corpus (vendor post-fit netlist vs our lift) ─────────────
# One row per corpus design build; atoms/conns/compare cascade from it.
# Always-rebuild: scripts/cyclonev_corpus_build.py deletes the build row and
# reinserts.  Layout + example SQL: corpus/README.md.

postfit_builds = Table("postfit_builds", metadata,
    Column("id",          Integer, primary_key=True, autoincrement=True),
    Column("design",      Text,    nullable=False, unique=True),  # corpus dir name
    Column("family",      Text,    nullable=False),               # e.g. "cyclonev"
    Column("device",      Text,    nullable=False),
    Column("top",         Text,    nullable=False),
    Column("toolchain",   Text),                                  # vendor tool version string
    Column("src_sha256",  JSON,    nullable=False),               # {file: sha256}
    Column("qsf",         JSON,    nullable=False),               # extra QSF lines from design.toml
    Column("purpose",     Text),
    Column("exercises",   JSON),                                  # feature tags from design.toml
    Column("built_at",    DateTime(timezone=True)),
    Column("out_dir",     Text,    nullable=False),               # repo-relative
    Column("lift_label",  Text),                                  # bitstreams.label of our lift
    Column("status",      Text,    nullable=False),               # "ok" | "fail:<step>"
)

# Placed atoms from the post-fit netlist.  Top-level ports are type "pin"
# (location = PIN_xx, params = io standard etc.).
postfit_atoms = Table("postfit_atoms", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("build",     Integer, ForeignKey("postfit_builds.id", ondelete="CASCADE"), nullable=False),
    Column("name",      Text,    nullable=False),   # instance name, escapes removed
    Column("type",      Text,    nullable=False),   # e.g. cyclonev_lcell_comb, dffeas, pin
    Column("location",  Text),                      # raw, e.g. LABCELL_X1_Y19_N3
    Column("loc_kind",  Text),                      # e.g. LABCELL, FF, IOOBUF, PIN
    Column("x",         Integer),
    Column("y",         Integer),
    Column("n",         Integer),
    Column("params",    JSON,    nullable=False),   # {defparam: value}, values as written
    UniqueConstraint("build", "name"),
)
Index("idx_postfit_atoms_type", postfit_atoms.c.build, postfit_atoms.c.type)

# One row per port bit of an atom.  net is the canonical net name (assign
# aliases resolved); const is "0"/"1" for gnd/vcc/literals, else NULL.
postfit_conns = Table("postfit_conns", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("build",     Integer, ForeignKey("postfit_builds.id", ondelete="CASCADE"), nullable=False),
    Column("atom",      Integer, ForeignKey("postfit_atoms.id", ondelete="CASCADE"), nullable=False),
    Column("port",      Text,    nullable=False),
    Column("bit",       Integer, nullable=False),   # 0 for scalar ports, LSB = 0
    Column("direction", Text,    nullable=False),   # "in" | "out"
    Column("net",       Text),
    Column("inverted",  Boolean, nullable=False, server_default="0"),
    Column("const",     Text),
)
Index("idx_postfit_conns_atom", postfit_conns.c.atom)
Index("idx_postfit_conns_net", postfit_conns.c.build, postfit_conns.c.net)

# Per-atom, per-field comparison: vendor value vs our lifted value.
postfit_compare = Table("postfit_compare", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("build",         Integer, ForeignKey("postfit_builds.id", ondelete="CASCADE"), nullable=False),
    Column("atom",          Text),                  # postfit_atoms.name, NULL for lift-only rows
    Column("location",      Text),
    Column("field",         Text,    nullable=False),  # e.g. lut_mask, ff.clk, conn.dataa, pin
    Column("quartus_value", Text),
    Column("lifted_value",  Text),
    Column("verdict",       Text,    nullable=False),  # MATCH|MISMATCH|LIFT_MISSING|QUARTUS_ONLY
)
Index("idx_postfit_compare_build", postfit_compare.c.build, postfit_compare.c.field)

# Vendor timing-report routes, one row per hop, every reported path kept (no dedupe).
# Source: quartus_sta report_timing -show_routing (route_report.txt per build).
route_hops = Table("route_hops", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("build",     Integer, ForeignKey("postfit_builds.id", ondelete="CASCADE"), nullable=False),
    Column("analysis",  Text,    nullable=False),   # "setup" | "recovery"
    Column("path",      Integer, nullable=False),   # Path #N within that analysis
    Column("from_node", Text),
    Column("to_node",   Text),
    Column("part",      Text,    nullable=False),   # "arrival" | "required"
    Column("hop",       Integer, nullable=False),   # row index within part
    Column("depth",     Integer, nullable=False),   # 0 = section row, 1 = hop inside it
    Column("total",     Float),
    Column("incr",      Float),
    Column("rf",        Text),                      # RR/RF/FR/FF or NULL
    Column("type",      Text),                      # RE | IC | CELL | uTco | NULL
    Column("fanout",    Integer),
    Column("location",  Text),                      # raw, e.g. LOCAL_LINE_X1_Y19_N0_I1
    Column("loc_kind",  Text),                      # e.g. LOCAL_LINE, LABCELL, PIN
    Column("x",         Integer),
    Column("y",         Integer),
    Column("n",         Integer),
    Column("idx",       Integer),                   # the _I<k> routing-element index
    Column("element",   Text),                      # RE type, or atom|port for IC/CELL
    Column("section",   Text),                      # enclosing depth-0 row, e.g. "clock path", "data path"
    Column("driver",    Text),                      # last CELL row before this hop (atom|port): the net being routed
)
Index("idx_route_hops_build", route_hops.c.build, route_hops.c.analysis, route_hops.c.path)
Index("idx_route_hops_loc", route_hops.c.build, route_hops.c.location)

# Full per-net routing trees from `quartus_cdb --back_annotate=routing` (build.rcf).
# One row per element; a branch = one path segment ending at one sink (`dest`).
# kind: elem | label (implicit element named by `label =`, a fan-out point).
rcf_routes = Table("rcf_routes", metadata,
    Column("id",       Integer, primary_key=True, autoincrement=True),
    Column("build",    Integer, ForeignKey("postfit_builds.id", ondelete="CASCADE"), nullable=False),
    Column("net",      Text,    nullable=False),    # signal_name
    Column("branch",   Integer, nullable=False),    # 0-based within net, file order
    Column("parent_branch", Integer),               # NULL for branch 0
    Column("parent_label",  Text),                  # branch_point label this branch leaves from
    Column("hop",      Integer, nullable=False),    # index within branch
    Column("kind",     Text,    nullable=False),
    Column("element",  Text,    nullable=False),    # TYPE e.g. R6, C2, LOCAL_INTERCONNECT
    Column("x",        Integer),
    Column("y",        Integer),
    Column("n",        Integer),                    # RCF S<n> (route_hops N<n>)
    Column("idx",      Integer),                    # I<k>; NULL for the B-form elements
    Column("port_path", Text),                      # B-form tail, e.g. IOC~INPUT~NIOD0OUT[0]
    Column("raw",      Text,    nullable=False),
    Column("dest_atom", Text),                      # sink of this branch (same on all its rows)
    Column("dest_port", Text),
    Column("route_port", Text),
)
Index("idx_rcf_routes_net", rcf_routes.c.build, rcf_routes.c.net, rcf_routes.c.branch)
Index("idx_rcf_routes_loc", rcf_routes.c.build, rcf_routes.c.element, rcf_routes.c.x, rcf_routes.c.y)

# Directed routing fuzz: one RCF element swapped, bits changed vs the unedited build.
rcf_fuzz_bits = Table("rcf_fuzz_bits", metadata,
    Column("id",       Integer, primary_key=True, autoincrement=True),
    Column("build",    Integer, ForeignKey("postfit_builds.id", ondelete="CASCADE"), nullable=False),
    Column("net",      Text,    nullable=False),
    Column("branch",   Integer, nullable=False),
    Column("hop",      Integer, nullable=False),
    Column("element",  Text,    nullable=False),    # element type at the mux
    Column("x",        Integer),
    Column("y",        Integer),
    Column("orig_idx", Integer),
    Column("alt_idx",  Integer),                    # edit mode: idx tried; exclude mode: depth (1..); NULL = control
    Column("mode",     Text),                       # edit | exclude
    Column("status",   Text,    nullable=False),    # control | accepted | rerouted | fail:<step> | no_alternative
    Column("excluded", JSON),                       # exclude mode: ["TYPE:XxYyS0Ik", ...] listed in the exclusion section
    Column("new_route", JSON),                      # exported route of the target branch after the fit
    Column("replay",   Text),                       # exported RCF re-imported alone: accepted | rejected | fail:<step>
    Column("n_changed", Integer),
    Column("changed_bits", JSON),                   # [[rbf byte offset, bit 0-7], ...] vs the control variant
    Column("bt_diff", JSON),                        # mistral-cv decomp lines added/removed vs the control
    Column("note",     Text),
)
Index("idx_rcf_fuzz_build", rcf_fuzz_bits.c.build, rcf_fuzz_bits.c.net)

# ── Provenance framework (docs/provenance-schema.md, #141) ───────────────────
# Generic for every family: subjects keyed (family, device, space, subject_key); sets of
# subjects compressed as scope rows (expanded in numpy, never stored per bit); tier fixed
# at creation, status moves; claim_events append-only; conflicts first-class.
# Vocabulary (tiers, statuses, kinds) is closed: provenance/tiers.py dies on anything else.

families = Table("families", metadata,
    Column("id",            Text, primary_key=True),   # machxo2 | ecp5 | gowin | anlogic | cycloneiv | cyclonev
    Column("vendor",        Text, nullable=False),
    Column("name",          Text, nullable=False),
    Column("lut_inputs",    Integer, nullable=False),
    Column("bit_model",     Text, nullable=False),     # how a bit is addressed: "frame,v" | "tile,frame,bit" | "cram x,y"
    Column("device_db",     Text),                     # where the vendored/open device data lives
)

devices = Table("devices", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("family",        Text, ForeignKey("families.id"), nullable=False),
    Column("name",          Text, nullable=False),     # e.g. EP4CGX150, LCMXO2-1200, LFE5U-25F, GW1N-2
    Column("die",           Text),
    Column("packages",      JSON),                     # list
    Column("die_bits",      Integer),                  # coverage denominator (NULL = not established)
    Column("geometry",      JSON),                     # frames, bits_per_frame, FX/VY tables, tile grid, ...
    Column("source_ref",    Text),                     # geometry source (file / doc)
    UniqueConstraint("family", "name"),
)

address_spaces = Table("address_spaces", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("family",        Text, ForeignKey("families.id"), nullable=False),
    Column("space",         Text, nullable=False),     # bit | tile-bit | pip | mux-input | cell-param | net-attr | stream-option | coord-map | port-map
    Column("key_grammar",   Text, nullable=False),     # how subject_key is spelled in this space (as data)
    Column("n_objects",     Integer),                  # size of the space when enumerable (bit: die_bits; pip: ddb fan-out)
    UniqueConstraint("family", "space"),
)

scopes = Table("scopes", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("family",        Text, ForeignKey("families.id"), nullable=False),
    Column("device",        Text, nullable=False),
    Column("space",         Text, nullable=False),
    Column("kind",          Text, nullable=False),     # cells | range | tile | tile-class | keys | formula | all
    Column("definition",    JSON, nullable=False),     # expanded by provenance/scopes.py
    Column("scope_key",     Text, nullable=False),     # canonical string of (space, kind, definition)
    Column("n_objects",     Integer, nullable=False, server_default="0"),  # written by the register from the expansion
    Column("parent",        Integer, ForeignKey("scopes.id")),             # the wider scope this narrows
    Column("label",         Text),
    UniqueConstraint("family", "device", "scope_key"),
)
Index("idx_scopes_space", scopes.c.family, scopes.c.device, scopes.c.space, scopes.c.kind)

evidence = Table("evidence", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("kind",          Text, nullable=False),     # specimen-pair | vendor-decode | oracle-compare | audit | elimination | absence | image-hit | roundtrip
    Column("family",        Text, ForeignKey("families.id"), nullable=False),
    Column("device",        Text, nullable=False),
    Column("name",          Text, nullable=False),     # pair / design / image / decoder name
    Column("source_ref",    Text, nullable=False),     # repo-relative file the row was read from
    Column("sha256",        Text),                     # of source_ref (provenance rot check)
    Column("generator",     Text),                     # script that produced the artefact
    Column("build_base",    Integer, ForeignKey("postfit_builds.id")),
    Column("build_spec",    Integer, ForeignKey("postfit_builds.id")),
    Column("tool_version",  Text),
    Column("stable",        Boolean),                  # rebuild gave identical bits (NULL = not rebuilt)
    Column("result",        JSON, nullable=False),     # per-pair metadata (src/snk/hop/rcf...), digest, absence record, compare summary
    # Changed-bit sets, packed: sorted flat indices (frame * bits_per_frame + v), delta-encoded
    # LEB128 varints (provenance/evidence_io.py). ~1 byte/bit dense, 4-5 sparse; JSON is 8-14.
    Column("bits_spec",     LargeBinary),              # set in the specimen, clear in the base
    Column("bits_base",     LargeBinary),              # set in the base, clear in the specimen
    Column("bit_encoding",  Text),                     # "dvarint:flat:<bits_per_frame>"
    Column("n_objects",     Integer, nullable=False, server_default="0"),
    Column("commit",        Text, nullable=False),
    Column("created_at",    DateTime(timezone=True)),
    UniqueConstraint("family", "device", "kind", "name", "source_ref"),
)
Index("idx_evidence_kind", evidence.c.family, evidence.c.device, evidence.c.kind)

evidence_scopes = Table("evidence_scopes", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("evidence_id",   Integer, ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False),
    Column("scope_id",      Integer, ForeignKey("scopes.id"), nullable=False),
    UniqueConstraint("evidence_id", "scope_id"),
)
Index("idx_evidence_scopes_scope", evidence_scopes.c.scope_id)

matchers = Table("matchers", metadata,
    Column("id",            Text, primary_key=True),   # slug incl. version: affine-v1, llm-proposer-v1
    Column("kind",          Text, nullable=False),     # deterministic | statistical | llm-proposed
    Column("name",          Text, nullable=False),
    Column("version",       Integer, nullable=False),
    Column("code_ref",      Text, nullable=False),     # module:class
    Column("parameters",    JSON),
    Column("training_evidence", JSON),                 # evidence ids a statistical matcher was fitted on
    Column("created_commit", Text, nullable=False),
)

claim_patterns = Table("claim_patterns", metadata,
    Column("id",            Text, primary_key=True),   # slug: ll-translate-v1; a changed law is a NEW id
    Column("family",        Text, ForeignKey("families.id"), nullable=False),
    Column("device",        Text),                     # NULL = family-wide
    Column("matcher_id",    Text, ForeignKey("matchers.id")),
    Column("space",         Text, nullable=False),
    Column("description",   Text, nullable=False),
    Column("law",           JSON, nullable=False),     # parameters as data; law.dims drives the sampling N rule
    Column("scope_id",      Integer, ForeignKey("scopes.id")),   # where it is applied
    Column("status",        Text, nullable=False, server_default="open"),
    Column("confirmations", Integer, nullable=False, server_default="0"),
    Column("refutations",   Integer, nullable=False, server_default="0"),
    Column("verified_scope", JSON),                    # hull of confirmed scopes
    Column("created_commit", Text, nullable=False),
    Column("updated_at",    DateTime(timezone=True)),
)
Index("idx_claim_patterns_family", claim_patterns.c.family, claim_patterns.c.status)

pattern_evidence = Table("pattern_evidence", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("pattern_id",    Text, ForeignKey("claim_patterns.id", ondelete="CASCADE"), nullable=False),
    Column("evidence_id",   Integer, ForeignKey("evidence.id"), nullable=False),
    Column("role",          Text, nullable=False),     # parent | confirm | refute
    UniqueConstraint("pattern_id", "evidence_id", "role"),
)
Index("idx_pattern_evidence_ev", pattern_evidence.c.evidence_id)

claims = Table("claims", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("family",        Text, ForeignKey("families.id"), nullable=False),
    Column("device",        Text, nullable=False),
    Column("space",         Text, nullable=False),
    Column("subject_key",   Text, nullable=False),     # grammar per address_spaces
    Column("scope_id",      Integer, ForeignKey("scopes.id"), nullable=False),
    Column("meaning",       JSON, nullable=False),     # the answer
    Column("tier",          Text, nullable=False),     # fixed at creation (provenance.tiers.TIERS)
    Column("status",        Text, nullable=False, server_default="open"),
    Column("pattern_id",    Text, ForeignKey("claim_patterns.id")),   # NULL unless pattern-predicted
    Column("n_objects",     Integer, nullable=False, server_default="0"),
    Column("inventory_class", Text),                   # 1a..6 (ties to the ledger)
    Column("confidence_basis", Text),
    Column("confirmations", Integer, nullable=False, server_default="0"),
    Column("refutations",   Integer, nullable=False, server_default="0"),
    Column("superseded_by", Integer, ForeignKey("claims.id")),
    Column("created_commit", Text, nullable=False),
    Column("updated_at",    DateTime(timezone=True)),
    UniqueConstraint("family", "device", "space", "subject_key", "scope_id"),
)
Index("idx_claims_pattern", claims.c.pattern_id)
Index("idx_claims_tier", claims.c.family, claims.c.device, claims.c.tier, claims.c.status)
Index("idx_claims_subject", claims.c.family, claims.c.device, claims.c.space, claims.c.subject_key)
Index("idx_claims_scope", claims.c.scope_id)

claim_evidence = Table("claim_evidence", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("claim_id",      Integer, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False),
    Column("evidence_id",   Integer, ForeignKey("evidence.id"), nullable=False),
    Column("role",          Text, nullable=False),     # direct | parent | confirm | refute
    UniqueConstraint("claim_id", "evidence_id", "role"),
)
Index("idx_claim_evidence_ev", claim_evidence.c.evidence_id)

claim_events = Table("claim_events", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("claim_id",      Integer, ForeignKey("claims.id", ondelete="CASCADE")),
    Column("pattern_id",    Text, ForeignKey("claim_patterns.id")),
    Column("expectation_id", Integer),                 # FK omitted: expectations defined below; append-only log
    Column("unknown_id",    Integer),
    Column("event",         Text, nullable=False),     # created | confirmed | refuted | suspect | cleared | superseded | audited | stale | conflict | parked | reopened | hit
    Column("evidence_id",   Integer, ForeignKey("evidence.id")),
    Column("commit",        Text, nullable=False),
    Column("ts",            DateTime(timezone=True), nullable=False),
    Column("detail",        JSON),
)
Index("idx_claim_events_pattern", claim_events.c.pattern_id, claim_events.c.ts)
Index("idx_claim_events_claim", claim_events.c.claim_id, claim_events.c.ts)

claim_conflicts = Table("claim_conflicts", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("claim_a",       Integer, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False),
    Column("claim_b",       Integer, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False),
    Column("status",        Text, nullable=False, server_default="open"),   # open | adjudicated
    Column("resolution",    Text),
    Column("winner",        Integer, ForeignKey("claims.id")),
    Column("opened_commit", Text, nullable=False),
    Column("detail",        JSON),
    UniqueConstraint("claim_a", "claim_b"),
)

expectations = Table("expectations", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("family",        Text, ForeignKey("families.id"), nullable=False),
    Column("device",        Text, nullable=False),
    Column("space",         Text, nullable=False),
    Column("subject_key",   Text, nullable=False),
    Column("scope_id",      Integer, ForeignKey("scopes.id"), nullable=False),
    Column("matcher_id",    Text, ForeignKey("matchers.id"), nullable=False),
    Column("pattern_id",    Text, ForeignKey("claim_patterns.id")),
    Column("expected",      JSON, nullable=False),
    Column("confidence",    Float),
    Column("confidence_basis", Text),
    Column("supporting_evidence", JSON),               # evidence ids the prediction was derived from
    Column("status",        Text, nullable=False, server_default="open"),  # open | confirmed | refuted | parked
    Column("resolved_evidence", Integer, ForeignKey("evidence.id")),
    Column("claim_id",      Integer, ForeignKey("claims.id")),              # the measured claim that confirmed it
    Column("n_objects",     Integer, nullable=False, server_default="0"),
    Column("created_commit", Text, nullable=False),
    Column("updated_at",    DateTime(timezone=True)),
    UniqueConstraint("family", "device", "space", "subject_key", "scope_id", "matcher_id"),
)
Index("idx_expectations_status", expectations.c.family, expectations.c.device, expectations.c.status)
Index("idx_expectations_pattern", expectations.c.pattern_id)
Index("idx_expectations_scope", expectations.c.scope_id)

unknowns = Table("unknowns", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("family",        Text, ForeignKey("families.id"), nullable=False),
    Column("device",        Text, nullable=False),
    Column("space",         Text, nullable=False),
    Column("subject_key",   Text),                     # NULL = the whole scope
    Column("scope_id",      Integer, ForeignKey("scopes.id"), nullable=False),
    Column("reason",        Text, nullable=False),     # unasked | unforceable | seen-in-image | orphan | conflict | not-required-by-corpus
    Column("status",        Text, nullable=False, server_default="open"),   # open | parked | promoted
    Column("absence_evidence", Integer, ForeignKey("evidence.id")),        # set => never-exercised
    Column("inventory_class", Text),
    Column("n_objects",     Integer, nullable=False, server_default="0"),
    Column("note",          Text),
    Column("created_commit", Text, nullable=False),
    Column("updated_at",    DateTime(timezone=True)),
    UniqueConstraint("family", "device", "space", "subject_key", "scope_id"),
)
Index("idx_unknowns_status", unknowns.c.family, unknowns.c.device, unknowns.c.status)
Index("idx_unknowns_scope", unknowns.c.scope_id)

audits = Table("audits", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("family",        Text, ForeignKey("families.id"), nullable=False),
    Column("device",        Text, nullable=False),
    Column("pattern_id",    Text, ForeignKey("claim_patterns.id")),
    Column("claim_id",      Integer, ForeignKey("claims.id")),
    Column("expectation_id", Integer, ForeignKey("expectations.id")),
    Column("scope_id",      Integer, ForeignKey("scopes.id"), nullable=False),
    Column("priority",      Integer, nullable=False, server_default="0"),  # n_objects at stake
    Column("reason",        Text, nullable=False),     # suspect | sampling | new-pattern | corpus-fail
    Column("status",        Text, nullable=False, server_default="queued"),  # queued | built | confirmed | refuted | cancelled
    Column("evidence_id",   Integer, ForeignKey("evidence.id")),
    Column("queued_commit", Text, nullable=False),
    Column("updated_at",    DateTime(timezone=True)),
)
Index("idx_audits_queue", audits.c.family, audits.c.status, audits.c.priority)

lift_provenance = Table("lift_provenance", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("bitstream",     Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("object_kind",   Text, nullable=False),     # lut | ff | arc | net | hard-cell | pad
    Column("object_key",    Text, nullable=False),
    Column("min_tier",      Text, nullable=False),
    Column("min_status",    Text, nullable=False),
    Column("claim_ids",     JSON, nullable=False),
    UniqueConstraint("bitstream", "object_kind", "object_key"),
)
Index("idx_lift_provenance_tier", lift_provenance.c.bitstream, lift_provenance.c.min_tier)

corpus_members = Table("corpus_members", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("family",        Text, ForeignKey("families.id"), nullable=False),
    Column("name",          Text, nullable=False),
    Column("kind",          Text, nullable=False),     # oracle-build | third-party-image | roundtrip | lec
    Column("device",        Text),
    Column("build_id",      Integer, ForeignKey("postfit_builds.id")),
    Column("source_ref",    Text),                     # dir / manifest entry
    Column("sha256",        Text),
    Column("gate_script",   Text),                     # scripts/<family>_gate.py or equivalent
    Column("required",      Boolean, nullable=False, server_default="1"),
    Column("expected",      JSON),                     # {headline: 100, wrong: 0} by default
    Column("added_commit",  Text, nullable=False),
    UniqueConstraint("family", "name"),
)

gate_runs = Table("gate_runs", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("family",        Text, ForeignKey("families.id"), nullable=False),
    Column("script",        Text, nullable=False),
    Column("commit",        Text, nullable=False),
    Column("code_stamp",    Text),
    Column("params",        JSON),
    Column("ts",            DateTime(timezone=True), nullable=False),
    Column("passed",        Boolean),                  # every required member passed
    Column("summary",       JSON),                     # totals per category, fusion/split counts
)
Index("idx_gate_runs_family", gate_runs.c.family, gate_runs.c.ts)

gate_results = Table("gate_results", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("run_id",        Integer, ForeignKey("gate_runs.id", ondelete="CASCADE"), nullable=False),
    Column("member_id",     Integer, ForeignKey("corpus_members.id"), nullable=False),
    Column("category",      Text, nullable=False),     # pips | nets | connections | register clocks | sites | lut_init | ...
    Column("matched",       Integer, nullable=False, server_default="0"),
    Column("missing",       Integer, nullable=False, server_default="0"),
    Column("extra",         Integer, nullable=False, server_default="0"),
    Column("wrong",         Integer, nullable=False, server_default="0"),
    Column("headline",      Float),                    # matched / (matched + missing + extra + wrong), %
    Column("passed",        Boolean, nullable=False, server_default="0"),
    Column("failing_claims", JSON),                    # claim ids under the failing cone (lift_provenance)
    UniqueConstraint("run_id", "member_id", "category"),
)
Index("idx_gate_results_member", gate_results.c.member_id)

done_criteria = Table("done_criteria", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("family",        Text, ForeignKey("families.id"), nullable=False, unique=True),
    Column("criterion",     JSON, nullable=False),     # {headline: 100, wrong: 0, required_members: n}
    Column("state",         Text, nullable=False, server_default="open"),   # open | met
    Column("met_run",       Integer, ForeignKey("gate_runs.id")),
    Column("met_commit",    Text),
    Column("updated_at",    DateTime(timezone=True)),
)

coverage_ledger = Table("coverage_ledger", metadata,
    Column("id",            Integer, primary_key=True, autoincrement=True),
    Column("family",        Text, ForeignKey("families.id"), nullable=False),
    Column("device",        Text, nullable=False),
    Column("commit",        Text, nullable=False),
    Column("ts",            DateTime(timezone=True), nullable=False),
    Column("inventory_class", Text, nullable=False),
    Column("tier",          Text, nullable=False),
    Column("status",        Text, nullable=False),
    Column("n_objects",     Integer, nullable=False),
    Column("denominator",   Text, nullable=False, server_default="die_bits"),  # die_bits | shown_reachable
    Column("source",        Text, nullable=False),     # claims | inventory-live
)
Index("idx_coverage_ledger", coverage_ledger.c.family, coverage_ledger.c.device, coverage_ledger.c.commit)


# ── Schema management ─────────────────────────────────────────────────────────

def init(eng=None):
    """Create all tables (IF NOT EXISTS), then FAIL FAST on schema drift.

    `create_all` is create-only: it never adds a column to a table that already
    exists.  So a database written before a column was added keeps its old shape
    silently, and the first INSERT dies hundreds of lines into a pipeline stage
    with `table ffs has no column named dtype` -- which reads as a code bug, not as
    "your database is out of date".  That happened, and it cost real time.

    Derived artefacts have no legacy in this project: the fix for an outdated
    database is to delete it and rebuild, never to migrate.  This check exists to
    say so at startup instead of letting a stale file look usable.
    """
    import db as _db
    eng = eng or _db.engine()
    metadata.create_all(eng)
    _assert_no_drift(eng)


def _assert_no_drift(eng):
    """Compare declared columns against what the database actually has."""
    from sqlalchemy import inspect as _inspect
    insp = _inspect(eng)
    have_tables = set(insp.get_table_names())
    missing: list[str] = []
    for table in metadata.sorted_tables:
        if table.name not in have_tables:
            continue  # create_all just made it, or it is genuinely new
        actual = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in actual:
                missing.append(f"{table.name}.{col.name}")
    if not missing:
        return
    shown = ", ".join(missing[:8]) + (" ..." if len(missing) > 8 else "")
    import db as _db
    _db.die(
        f"database schema is OUT OF DATE: {len(missing)} declared column(s) are "
        f"absent from the existing tables ({shown}).\n"
        f"CREATE TABLE IF NOT EXISTS cannot add columns, so this database predates "
        f"the current schema.py and writes to it will fail mid-pipeline.\n"
        f"Derived data has no legacy here -- delete the database and rebuild "
        f"rather than migrating it. For SQLite that is simply removing the file "
        f"named by $PLURIBUS_SQLITE_PATH (default ./pluribus.db).")


def drop_all(eng=None):
    """Drop all tables.  Used for full DB reset (SQLite: prefer os.unlink)."""
    import db as _db
    metadata.drop_all(eng or _db.engine())
