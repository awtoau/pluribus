"""Shared clock-spine unification (issue #65).

A single physical MachXO2 clock routed on one BRANCH_HPBX global track is
tapped by many per-region local nets that reachability never unions (the
global spine G_VPTXnnnn is a ghost source with no decoded fabric driver), so
one physical clock surfaces as N distinct clock-domain nets.  Every consumer
of the clock view — the recovered-Verilog emitter (``verilog.py``) and the RE
report (``report.py``) — must present the SAME collapsed set of clocks, so the
collapse logic lives here, called by both.

``hpbx_track`` is populated only for MachXO2 (GOWIN and other families leave it
NULL), so unification is inert for every non-MachXO2 recovery: an all-NULL
``cds_rows`` yields an empty map and every clock net stays itself.
"""


def unify_clock_spines(cds_rows, name_rows):
    """Collapse clock-domain nets that share a BRANCH_HPBX primary-clock track.

    Args:
        cds_rows:  iterable of ``(clk_net, ff_count, hpbx_track)`` rows, one per
                   clock domain (``clock_domain_summary``).
        name_rows: iterable of ``(net, name)`` rows (``net_names``), used only to
                   pick a semantically-named survivor.

    Returns:
        ``clk_unify``: ``{non_canonical_clk_net: canonical_clk_net}``.  Nets not
        present as keys are already canonical (or ride no track).  The canonical
        of a track is the member with the strongest human name, then the most
        FFs, so the collapsed clock keeps its semantic name (``clk_main`` /
        ``clk_<pad>``) rather than a raw net id.  A BRANCH_HPBX track carries
        exactly one clock net, so merging within a track never over-merges
        distinct clocks.
    """
    clk_names = {net: name for net, name in name_rows}

    def _canon_rank(member):
        net, ffc = member
        name = clk_names.get(net, "")
        name_rank = 2 if name == "clk_main" else (1 if name else 0)
        return (name_rank, ffc)

    track_members: dict[str, list] = {}
    for clk_net, ff_count, hpbx_track in cds_rows:
        if hpbx_track:
            track_members.setdefault(hpbx_track, []).append((clk_net, ff_count or 0))

    clk_unify: dict[str, str] = {}
    for members in track_members.values():
        if len(members) < 2:
            continue
        canon = max(members, key=_canon_rank)[0]
        for clk_net, _ in members:
            if clk_net != canon:
                clk_unify[clk_net] = canon
    return clk_unify


def apply(clk_net, clk_unify):
    """Canonical clock net for ``clk_net`` (itself if it rides no collapsed track)."""
    return clk_unify.get(clk_net, clk_net)
