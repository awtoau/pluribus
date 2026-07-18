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
    Integer, JSON, MetaData, SmallInteger, String, Table, Text,
    UniqueConstraint,
)

metadata = MetaData()

# ── 1. Netlist layer ──────────────────────────────────────────────────────────

bitstreams = Table("bitstreams", metadata,
    Column("id",        Integer,  primary_key=True, autoincrement=True),
    Column("label",     Text,     nullable=False, unique=True),
    Column("filename",  Text,     nullable=False),
    Column("device",    Text,     nullable=False),
    Column("package",   Text,     nullable=False),
    Column("loaded_at", DateTime(timezone=True)),
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
    UniqueConstraint("bitstream", "cell"),
)

luts = Table("luts", metadata,
    Column("id",        Integer, primary_key=True, autoincrement=True),
    Column("bitstream", Integer, ForeignKey("bitstreams.id", ondelete="CASCADE"), nullable=False),
    Column("cell",  Text,      nullable=False),
    Column("init",  String(16), nullable=False),
    Column("a",     Text), Column("b", Text), Column("c", Text), Column("d", Text),
    Column("z",     Text),
    Column("deps",  JSON),   # TEXT[] → JSON list
    Column("fn",    Text),
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

# ── Schema management ─────────────────────────────────────────────────────────

def init(eng=None):
    """Create all tables (IF NOT EXISTS).  Safe to call on every startup."""
    import db as _db
    metadata.create_all(eng or _db.engine())


def drop_all(eng=None):
    """Drop all tables.  Used for full DB reset (SQLite: prefer os.unlink)."""
    import db as _db
    metadata.drop_all(eng or _db.engine())
