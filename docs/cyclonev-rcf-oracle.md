# Cyclone V RCF routing oracle + directed routing fuzz

Quartus `.rcf` (Routing Constraints File) = every net's complete routing tree, exported by `quartus_cdb` and importable by `quartus_fit`. Issue #108. Quartus 25.1std.0 Lite, device `5CEBA4U19C8`, measured 2026-10-23 on the 14-design corpus.

Tags: [V] verified by a run on this corpus. [A] assumed / inferred.

## Export (in the corpus build)

- `scripts/cyclonev_corpus_build.py` step `quartus_cdb`, run on a scratch copy (`<design>/rcf_work/`, deleted afterwards) because `--write_settings_files=on` rewrites the `.qsf`:
  - `quartus_cdb build -c build --back_annotate=routing --write_settings_files=on` -> `build.rcf` kept in the design folder (gitignored with the other outputs). ~0.7 s/design. [V]
  - Timeout `OVERALL_S["quartus_cdb"] = 4` s = 3x the worst measured 1.2 s (2026-10-23, loadavg 4-60, all 14 designs); expiry kills the step and fails the design build.
- `scripts/cyclonev_rcf_parse.py` -> table `rcf_routes` (always-rebuild per build). 14 designs: 829 nets, 1467 branches, 6269 element rows.
- The rewritten `.qsf` gains `ROUTING_BACK_ANNOTATION_FILE build.rcf` and a `set_location_assignment` per atom (56 for shiftreg16). That pair is what makes import work. [V]

## RCF grammar [V: parser hard-errors on anything else; all 14 designs parse]

```
signal_name = <net> {                 # <net> = atom name; DSP/M10K outputs use their sink atom's name
    TYPE:X<x>Y<y>S<n>I<idx>;          # routing element (wire / mux)
    TYPE:X<x>Y<y>S<n>B:<port path>;   # block-port element: IO_*, HMCPHY_RE, CLKBUF*, GCLK*...  (no idx)
    label = Label_<E>, <E>;           # <E> is itself an element of this branch; names a fan-out point
    branch_point = Label_<E>;         # next branch leaves from that label
    dest = ( <atom>, <port> )[, route_port = <port>];    # ends a branch
}
section global_data { rcf_written_by = ...; device = 5CEBA4U19C8; }
section ram_sublocations { ( <atom>, a, b); ... }        # M10K only; parser skips non-route sections
```

- A branch = elements up to one `dest`. A branch with no `branch_point` leaves from the net driver (root). A branch with `branch_point = L` leaves from the element labelled `L`.
- `label = L, E` is also the place where `E` appears in the sequence (LE_BUFFER/LOCAL_INTERCONNECT often first show up this way). Parser keeps it as `kind='label'`.
- Branches with no own elements (dest directly on a label) get one `kind='dest'` row.
- Import-only section found from the fitter message table (`common/misc/msg_index.xml`, id 188019) and confirmed: `section exclusion_list { TYPE:XxYyS0Ik; ... }` = resources the router must not use. Other section kinds named in the messages (`resource_list`, `weights_list`, `hard`) not tried [A].

## Element names and coordinates (vs `route_hops`) [V]

- `TYPE:XxYySnIk` <-> route_hops `loc_kind=TYPE, x=x, y=y, n=n, idx=k` (RCF `S` = route_hops `N`). Same X/Y frame.
- Block-port form `TYPE:XxYySnB:<path>`: route_hops carries the same `x,y,n`; its `idx` is an internal port id, not the RCF `[k]`. Match on (type,x,y,n).
- `LOCAL_INTERCONNECT:X..I<k>` index = Mistral `TD.<x>.<y>.<k>`; `C2` <-> `V2`. Seen in the `.bt` diffs below (e.g. LI `I64` -> `TD.050.045.0064`, `C2:X50Y45I11` -> `V2.050.045.0011`). [V on the 15 fuzz variants; other types unchecked]
- Cell sites listed as RE rows in route_hops are not RCF elements: `CLKCTRL DSP FF IOIBUF IOPAD LABCELL MLABCELL M10K`.

## Coverage vs `route_hops` (`scripts/cyclonev_rcf_crosscheck.py`, log `tmp/logs/cyclonev_rcf_crosscheck.log`) [V]

| quantity | value |
|---|---|
| distinct route_hops routing hops (after dropping the cell sites above) | 5043 |
| of those present in the RCF (names + x,y,n,idx) | 5043 (100%), 0 misses |
| ...matched only by key, not by net name (pad hops with no driver; DSP/M10K-driven nets named differently) | 1280 |
| RCF nets | 829 |
| RCF nets with at least one timing-path hop | 548 (66%) |
| RCF-only nets (no timing path touches them) | 281 (34%) |
| RCF elements on timing-covered nets that no timing path used | 33 of 4005 (0.8%) |

- The gap is whole nets (34%), not parts of covered nets (0.8%).
- RCF-only nets are, e.g., input pads (`a[0]`), `*~output` pad nets of non-critical outputs, `clk` pad->buffer nets.
- DSP/M10K-driven nets: route_hops `driver` is `Mult0~8|resulta[k]`, the RCF net is the downstream atom (`p[0]~reg0`); no mapping built [A: needs the `.vo` block-port bit -> sink table].
- All 14 original designs rebuild with unchanged verdict counts (conn.data* MATCH 453 / MISMATCH 27, lut_mask 134/0/14/1, ff.present 80/0/52, pin 321/0/38) - same as `cyclonev-postfit-oracle.md`. [V]
- Only the 14 original designs were present in this worktree; construct designs from the parallel branch were not built.

## Import test [V]

Result: **import works.** `quartus_fit` reads `ROUTING_BACK_ANNOTATION_FILE` from the `.qsf` (no extra option) and treats it as soft routing constraints.

Commands (scratch copy of a design's `quartus/` dir, `$Q` = the Quartus `bin/`):

```
quartus_cdb build -c build --back_annotate=routing --write_settings_files=on   # writes build.rcf + locations into build.qsf
# edit build.rcf
quartus_fit build -c build ; quartus_asm build ; quartus_cpf -c build.sof build.rbf
quartus_cdb build -c build --back_annotate=routing --write_settings_files=on   # re-export: what the fitter actually used
```

- Fit log lines: `Using constrained routing from file build.rcf` (170118), `Router is attempting to preserve 100.00 percent of routes from ... a user specified Routing Constraints File` (170239).
- Control: unedited RCF through the whole flow -> `.rbf` identical to the original corpus `bitstream.rbf` (0 bits differ; shiftreg16 and adder12). [V]
- Accepted/rejected:
  - A constraint the router cannot satisfy is not an error: log shows `Cannot route signal "A" to atom "B"` / `Routing for this connection is constrained` / `Error on line number N in Routing Constraints File` / `will remove the routing constraints for this fan-out and ... another attempt` (170085, 170097, 170098, 170119). Fit rc 0; that one fan-out is rerouted, every other net keeps its imported route (re-exported RCF differs in exactly the edited net, 88 of 89 branches identical). [V]
  - Index beyond the tile's range (R6 idx >= 40, R3 idx >= 24 on adder12): only 170098 (no 170097). [V]
  - A legal route is honoured bit-exactly (replay below).
  - Not tested: the `hard` keyword (msg `FITAPI_VPR_RCF_HARD_ROUTING_CONSTRAINTS_WERE_VIOLATED`), `resource_list`, `weights_list`.
- Single-element edits (`--mode edit`, replace one idx in a net's RCF text) were never accepted: about 250 probes over 11 targets (LOCAL_LINE, LOCAL_INTERCONNECT, C2, R3, R6, R14_C12_INTERCONNECT_DRIVER; exhaustive idx ranges on several, plus candidates mined from edges seen in the corpus). Every one fell to reroute. Reason [A]: a mux/wire index is only legal together with its predecessor and successor; one-index swaps break adjacency, and several chains are forced (LE_BUFFER->LOCAL_LINE is 1:1; LOCAL_INTERCONNECT->BLOCK_INPUT_MUX_PASSTHROUGH is fixed per pin). 6 shiftreg16 probes were killed by the host-load guard and not retried (loadavg 65-79 at the time).
- What does work (`--mode exclude`): `section exclusion_list` appended to the RCF forbids chosen resources; the router detours only the affected fan-out, and the detour is a legal route. Fit log: `Router found N routing resources listed in an exclusion list section` (188019).
- Replay (the hand-edit proof): the detour's exported RCF is imported alone into a fresh project; re-export identical and `.rbf` byte-identical to the detour build. 15 of 15 accepted. A spliced RCF is therefore accepted when it is a legal route different from the fitter default.

## Directed fuzz (`scripts/cyclonev_rcf_fuzz.py`, table `rcf_fuzz_bits`) [V]

- adder12, tile type LAB, element `LOCAL_INTERCONNECT` of the first branch of nets `s[0..4]~reg0 -> s[k]~output`; depth 1-3 (k-th alternative: the previous detour's LOCAL_INTERCONNECT is excluded too). 15 variants, 15 rerouted, 15 replay accepted.
- Bits are measured against the control build two ways:
  - raw `.rbf` bit XOR: 124-568 bits per variant, clustered in the CRAM region (byte ~2.38 M) plus a few in the header (bytes 184-295). Far more than the muxes changed; the surplus is not explained [A: per-frame ECC/CRC].
  - `mistral-cv decomp` text diff: 2-7 `r` lines removed/added per variant (the changed muxes) plus one `o JTAG_ID` line that changes with every config (checksum-like). This is the usable signal.

| net | orig LI idx | depth | raw rbf bits | decoded `r` lines (ctl/new) | new route (changed hops) |
|---|---|---|---|---|---|
| s[4] | 64 | 1 | 124 | 2/2 | LI 56 (rest unchanged) |
| s[4] | 64 | 2 | 142 | 3/3 | C2 11->18, LI 58 |
| s[4] | 64 | 3 | 148 | 3/3 | C2 18, LI 52 |
| s[2] | 77 | 1 | 162 | 2/2 | LI 49 (C4 unchanged) |
| s[0] | 30 | 1 | 474 | 6/6 | R3,R3,R3 chain, C2 11 (X36), LI 56 |
| s[1] | 3 | 1 | 538 | 7/7 | R3 chain, C2 18, LI 18 |

(all 15 rows: `select * from rcf_fuzz_bits where mode='exclude'` in `corpus/cyclonev/corpus.db`.)

- Example decoded diff, s[4] depth 1: `r V2.050.045.0011 TD.050.045.0064` -> `... TD.050.045.0056` and `r TD.050.045.0064 HMC.011.045:IOINTDQDOUT.88 ; E17` -> `TD.050.045.0056 ...`. I.e. Quartus `LOCAL_INTERCONNECT:X50Y45 I64 -> I56` = Mistral `TD.050.045.0064 -> 0056`: the segmatch-style correlation (feature = this mux used <-> bit change) is available.
- Not done: the full campaign; mapping non-LI element types to Mistral node names; explaining the raw-bit surplus.

## Limits

- Soft constraints only: a wrong guess silently reroutes; accept = re-export identical.
- Exclusion lists steer, they do not choose: the detour is the router's pick (deterministic: the same exclusion gave the same route in repeated runs).
- Single device (`5CEBA4U19C8`), single Quartus build. `--back_annotate=routing` warns the routing for this family "may not port to the next release" (143007).
- A fit under host load > ~30 can trip `OVERALL_S` limits written for a quiet box (killed steps are retried once, serially).

## Hand checks (RCF text vs `rcf_routes` vs `route_hops`) [V]

- counter_en_aclr `q[1]~reg0` (data, 4 branches): RCF lines 42-56+ -> rows branch 0 `LOCAL_LINE X1Y19 I5, BLOCK_INPUT_MUX I3` (dest `WideAnd0.DATAB`), branch 1 starts with `label LE_BUFFER I11`, `R6 I12`, `label LOCAL_INTERCONNECT I20`, `BLOCK_INPUT_MUX I57` (dest `q[2]~2.DATAB`, route_port DATAF), branch 2 `parent_label Label_LOCAL_INTERCONNECT:X1Y19S0I20`, `BIM I73`, branch 3 (from `Label_LE_BUFFER`) `R3, C4, R3, C2, LI X0Y18 I35, BIM_PASSTHROUGH I19`, IO path `IO_RE ... n=94`, `IO_OUTPUT_BUFFER_INPUT n=96`. `route_hops` RE hops with driver `q[1]~reg0|q`: all 19 routing hops equal (e.g. `C4 0,15,0,7`, `LOCAL_INTERCONNECT 1,19,0,20`, `IO_RE 0,18,94`); the 20th, `FF 1,19,17`, is a cell site.
- counter_en_aclr clock net `clk~inputCLKENA0` (RCF line 223): 13 own elements in branch 0 (`CLKBUFBLOCK_OUTPUT n=10` ... `GLOBAL_CLOCK X0Y22 I10`, `SPINE_CLOCK X12Y0 I16`, `SCLK_TO_ROWCLK_BUF I97, I100`, `LAB_CLK`, `BLK_CLK_BUF`, `ROWCLKSEL_PREBUF`, `ROWCLKSEL`, `GLOBAL_LOCAL_SEL`, label `LAB_INPUT I0`); other sinks are `kind='dest'` rows with that `parent_label`. route_hops (clock path, driver `clk~inputCLKENA0|outclk`) has all 13 distinct hops with identical x,y,n,idx.
- adder12 `s[0]~reg0`: RCF `LE_BUFFER X43Y44 I0; R6 X38Y44 I33; R14_C12_INTERCONNECT_DRIVER X43Y44 I1; R14 X30Y44 I1; C2 X35Y45 I11; LOCAL_INTERCONNECT X36Y45 I30; BLOCK_INPUT_MUX_PASSTHROUGH X36Y45 I44; HMCPHY_RE X11Y45 ...; IO_*` -> `rcf_routes` same order (`S0` -> `n=0`); each hop is in `route_hops` for driver `s[0]~reg0|q` (cross-check: 0 misses).
