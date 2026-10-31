# Cross-family adapter scoping for functrace.py (awtoau/pluribus#180)

Scoping only, no implementation, per #180. `functrace.py` (`lifters/cycloneiv_clean/functrace.py`,
#165/#177/#179) is built and shipped scoped to Cyclone IV's `cycloneiv_clean.emit.Netlist` shape —
see `docs/altera/cycloneIV/cycloneiv-clean-mac-trace.md`. This doc answers #180's four questions for a
FUTURE generalisation, inspecting `ecp5_lift.py`/`machxo2_lift.py`/`gowin_lift.py`/`cyclonev_lift.py`
(plus, found during the inspection, `cycloneiv_lift.py` and `anlogic_lift.py`) briefly — enough to see
each one's actual internal cell/net representation, not a deep dive.

## 0. Confirmed: no shared netlist schema across families today

`grep -n "class Design" lifters/*.py` finds **6 independent `Design` classes** (ecp5 reuses machxo2's,
confirmed by `from lifters.machxo2_lift import ...` in `ecp5_lift.py`, so 5 distinct definitions cover
6 families): `cycloneiv_lift.py`, `machxo2_lift.py` (shared by ecp5), `gowin_lift.py`, `anlogic_lift.py`,
`cyclonev_lift.py`. `cycloneiv_clean/emit.py`'s `Netlist`/`Builder` pair is a SEVENTH, separate thing —
the newer, actively-developed Cyclone IV pipeline (#141 on), not the same class as `cycloneiv_lift.py`'s
older `Design`. There is no base class, no shared protocol, no common import among any of these six.

## 1. What's genuinely the same vs family-specific

**The same, by convergent independent design (not a shared base class):**
- `luts`: a list of dicts, one per LUT4-equivalent cell, every family (ecp5/machxo2/gowin/anlogic/
  cyclonev/cycloneiv_lift) uses the SAME four field names for operand pins: `a`, `b`, `c`, `d` (scalar
  net-name strings), plus `name`, `init`, `z` (output). `cyclonev_lift.py`'s docstring states this
  outright: "`luts`/`ffs`/`nets`/`net_fanout` match every other lifter's shape exactly" — this is a
  real, already-noticed convention, not something this doc is discovering.
- `ffs`: a list of dicts, one per FF, every family has `name`, `d`, `clk`, and some enable/clear fields
  (names vary slightly: `ena`/`ce`, `aclr`/`clrn`/`lsr`, `sclr`, `sload`/`asdata`) — same SHAPE
  (scalar net-name-or-None per control pin), different field names per family.
- Net naming: every family resolves a net to one canonical signal-name string per DSU-root (or, for
  `cycloneiv_clean`, per routing-forest root) — the functrace walk core's actual requirement (a signal
  name resolves to exactly one producer) holds across all of them.

**Family-specific, and NOT reconcilable by a naming dict alone:**
- **Hard-block representation is structurally different, not just differently named.**
  `cycloneiv_clean.emit.Netlist` has typed lists (`nl.mac`, `nl.m9k`, `nl.pll`) with per-type dict
  shapes functrace.py's `TypeSpec` already models (list-valued operand pins like MAC `a`/`b`, scalar
  control pins). `gowin_lift.Design` has FOUR separate hard-block-ish lists with no common shape
  (`alus`, `muxes`, `ebrs`, `pads`) — `ebrs` (block RAM) carries `{block, row, col, ports: [...]}`,
  a nested-ports shape `functrace.TypeSpec.operand_signals` does not handle (it expects flat
  scalar/list pins, not a ports array). `cyclonev_lift.Design.hard` is a single flat list covering
  FOUR distinct hard-block kinds (M10K, MLAB RAM, DSP, PLL) tagged by a type field inside each dict —
  `functrace.TypeSpec` assumes one list per type, not one mixed list needing an extra filter step.
  `anlogic_lift.py` and base `cycloneiv_lift.py` have **no hard-block list at all** in what was
  inspected (LUT/FF only) — a MAC/M9K/PLL trace on those families has nothing to point `TypeSpec` at
  yet, regardless of adapter work.
- **Pin-name vocabulary differs per family even for the parts that ARE structurally alike**: ecp5/
  machxo2 LUTs use `a,b,c,d` (4-input); cycloneiv_clean's `pins` is a 4-element LIST (positional, not
  named) with a separate `prod` tuple carrying producer-type metadata functrace's `_leaf_kind` currently
  derives from the SIGNAL NAME's prefix instead (`lc_`/`ff_`/`pad_`/`m9k_`/`mac_`) — the other families'
  net names are plain `n<k>` (DSU-assigned), carrying no type-prefix convention at all. functrace's
  `_leaf_kind` is Cyclone-IV-specific for exactly this reason (its docstring already says so): it reads
  the family's signal-naming convention, which is not shared.
- **Addressing convention differs**: cycloneiv_clean hard-block instances key by `(x, y)` tile
  coordinate (`spec.id_fn`); gowin's `ebrs` key by `{block, row, col}` (three fields, not two); whether
  cyclonev's `hard` list entries key the same way was not checked in this pass (would need a second,
  deeper read, out of scope for "scoping only").

## 2. Does each lifter need a new export method, or a bigger restructure?

Not uniform — three tiers, from the inspection done (not exhaustive per-family, enough to characterise
the gap honestly):

| family | luts/ffs shape | hard-block shape | adapter effort (estimate) |
|---|---|---|---|
| ecp5 / machxo2 | `a,b,c,d` dict list, matches cycloneiv_clean's leaf-kind needs once net names get a type-prefix convention (or functrace's `_leaf_kind` is told to use a different test) | CCU2 (carry) modelled as its own list (`d.ccu2`), no M9K/DSP/PLL hard-block list seen in the part of machxo2_lift.py read this pass (CLAUDE.md says machxo2_lift.py exists and ecp5 adds routing/pads over it — hard-block lists for M9K/PLL may exist further in the file than this pass read; NOT confirmed absent, just not found in this pass) | **small-to-medium**: likely a thin adapter function (map `a/b/c/d` -> positional `pins`, assign a net-name type prefix OR extend `_leaf_kind` to take a per-family net-kind classifier) PROVIDED the hard-block lists this pass didn't find turn out to exist and have a flat scalar/list pin shape; otherwise medium (needs a hard-block TypeSpec written against whatever shape they do have) |
| gowin | same `a,b,c,d` convention | `ebrs`/`alus`/`muxes` are each a distinct shape, `ebrs` has nested `ports`; no single flat hard-block list | **medium**: the LUT/FF adapter is small (same tier as ecp5/machxo2), but each gowin hard-block type (EBR, ALU, mux) needs its own small TypeSpec-shaped adapter or an export method that flattens `ports` into functrace's expected scalar/list pins — real but bounded, not a rewrite of gowin_lift.py itself |
| cyclonev | explicitly "matches every other lifter's shape exactly" per its own docstring (luts/ffs) | single mixed `hard` list (M10K/MLAB/DSP/PLL together, type-tagged) | **small-to-medium**: luts/ffs need no change; the hard-block adapter is one filter-by-type-tag function per hard-block kind wanted (DSP first, to mirror this task), not a restructure of `cyclonev_lift.py` |
| anlogic / base cycloneiv_lift | `luts`/`ffs` present, LUT fields differ (`cycloneiv_lift.py`'s `luts` uses `a,b,c,d,cin,z,cout` — closer to ecp5/machxo2 than to `cycloneiv_clean`'s positional `pins` list) | none found in this pass | **blocked, not small**: no hard-block list exists to adapt FROM; functrace's chain-detection/operand-trace over a hard-block TYPE has nothing to target until a hard-block list is added to the lifter itself — this is lifter work, not adapter work, and wasn't scoped further (out of #180's "don't touch the lifters" instruction) |

**Honesty check on the original framing**: #180's own framing ("a small mapping/adapter per family, not
a new graph-walk implementation per family") holds for the LUT/FF walk core (genuinely a small per-family
net-name/pin-name mapping, confirmed by the real convergence found above) but did NOT hold uniformly for
hard-block tracing specifically — gowin's nested `ebrs.ports` and cyclonev's mixed-type `hard` list each
need real per-type adapter logic (not just a dict), and anlogic/base-cycloneiv_lift have no hard-block
list to adapt at all. "Just write one mapping dict" was too optimistic for the hard-block half of the
problem; it is a reasonable description of the LUT/FF half only.

## 3. Proposed shared interface (draft, for a future contributor to implement against)

Two-layer split, matching where the real commonality was found:

```python
# layer 1: generic leaf/cone walk (functrace.py's existing core, unchanged) needs only:
design.comb(sig)      # -> (leaf_mask_or_signal_list, const, uniq_pins, tt) | None for a non-LUT leaf
design.support(sig, hops=0)   # -> set of leaf signal names, optionally through `hops` FF stages
design.ff              # {name: {"d": sig_or_None, "clk": sig, "ena": sig, "aclr": sig, ...}}
design.lut             # {name: {"pins": [sig,...]}}  (patterns.Design already provides exactly this
                       #  for cycloneiv_clean; an ecp5/machxo2/gowin/cyclonev adapter's job is to
                       #  build an equivalent object from a/b/c/d fields -- this is the "small mapping")

# layer 2: hard-block TypeSpec (functrace.py's existing TypeSpec, unchanged shape) needs, per family,
# per hard-block kind wanted:
TypeSpec(name, list_attr, pins={"a": "list", ...}, out_prefix="...", id_fn=lambda inst: (...))
# `list_attr` must point at nl.<attr> holding a FLAT list of flat dicts with scalar/list string pins --
# this is where gowin's ebrs.ports and cyclonev's mixed `hard` list each need a real adapter FUNCTION
# (not a dict) that produces that flat shape, e.g.:
def gowin_ebr_typespec(nl):
    flat = [{"addr": p["addr"], "data": p["data"], ...} for e in nl.ebrs for p in e["ports"]]
    # (illustrative only -- real field names need the deeper per-family read #180 scoped OUT of this doc)
```

- **`_leaf_kind`'s signal-name-prefix classification is the one piece that is NOT just a mapping dict**
  — it currently hardcodes Cyclone-IV-specific prefixes (`lc_`/`ff_`/`pad_`/`m9k_`/`mac_`/`co_`/`u_`).
  A generic version would need either (a) every family's net-naming pass changed to emit the same
  prefix convention (touches each lifter's naming code, bigger than an adapter), or (b) `_leaf_kind`
  parameterised by a per-family `(prefix -> kind)` dict PLUS a way to recognise a hard-block output
  signal that isn't prefix-encoded (ecp5/machxo2/gowin/cyclonev net names are plain `n<k>`, carrying no
  type information at all — recognising "this net IS an EBR output" would need a reverse lookup from
  the hard-block list's own output-net field, not a prefix test). Option (b) is themedium-sized, real
  piece of generalisation work; it is not in `functrace.py` today (documented as a known gap in that
  file's own docstring) and is not solved by this scoping doc.

## 4. Summary for Dan's decision

- LUT/FF-level walk core: genuinely close to "one small mapping per family" — the four families
  inspected already converged on compatible shapes independently.
- Hard-block tracing (the actual point of this whole effort): **not uniform**. ecp5/machxo2 likely
  small-to-medium (unconfirmed hard-block list shape), gowin medium (real per-type adapter needed),
  cyclonev small-to-medium (one filter step per type), anlogic/base-cycloneiv_lift blocked (no
  hard-block list exists yet — lifter work, not adapter work).
- The `_leaf_kind` signal-naming-convention gap is real and not small; it is the piece most likely to
  need either a naming-convention change in each lifter or a non-trivial reverse-lookup addition to
  functrace.py itself, not a dict.
- No lifter file was modified to produce this assessment, per #180's scope.
