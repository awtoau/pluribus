#!/usr/bin/env python3
"""One place that finds external toolchains.  No machine-specific paths (#90).

THE PROBLEM
-----------
Roughly a dozen scripts each carried their own copy of a default of the shape

    os.environ.get("TRELLIS_DBROOT", "<an absolute path under someone's $HOME>")
    ECPUNPACK = "<the same, plus /bin/ecpunpack>"
    ECP5_TEST = "<an absolute path to an unrelated checkout>"

The `os.environ.get()` half is right; the defaults embedded one developer's
filesystem layout in a public repository, which is what blocked pushing the ECP5
branches (#90).  Copy-per-script also means the copies drift: two scripts can
disagree about where the database is and produce results that cannot be
compared.

THE RESOLUTION ORDER
--------------------
1. The explicit environment variable.  Always wins, always documented.
2. `PATH`, for executables.  A normal activated oss-cad-suite then needs no
   configuration at all -- which is the case this repository should make easy.
3. Conventional install locations, expressed RELATIVE TO THE USER (`~/opt/...`)
   or to system prefixes (`/opt/...`).  `~` is not machine-specific: it resolves
   per user on any machine, so it removes the absolute-home literal while leaving
   an existing developer's layout working with zero configuration.  That is
   the whole point -- a fix that forced everyone to export three variables before
   anything ran would be traded one problem for another.
4. `die()` naming the variable to set.  Never a silent fallback: a wrong
   database path decodes to a plausible, wrong fabric rather than an error, the
   same silent-wrongness class as #86 (MachXO2 geometry applied to ECP5 frames).

Paths belonging to OTHER repositories -- the ECP5 test designs, the known-good
RTL -- get no conventional-location search, because there is no convention for
where someone checked out an unrelated project.  Those are environment-or-die.

Usage:
    from toolchain import tool, trellis_dbroot, oss_cad_bin, external_dir

    ECPUNPACK = tool("ecpunpack", "ECPUNPACK")          # resolved, may be None
    DBROOT    = trellis_dbroot()                        # dies if not found
    TESTS     = external_dir("ECP5_TEST", "ECP5 test designs")
"""
import glob
import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Conventional oss-cad-suite roots, in the order a developer is likeliest to have
# one.  `~` first because a per-user unpack is how the suite is normally
# installed (it ships as a tarball, not a package).
_SUITE_ROOTS = (
    "~/opt/oss-cad-suite",
    "~/oss-cad-suite",
    "/opt/oss-cad-suite",
    "/usr/local/oss-cad-suite",
)


def _expand(p):
    return os.path.abspath(os.path.expanduser(p))


def _is_suite_root(p):
    """True only for a real oss-cad-suite unpack.

    Checks for the suite's own marker files rather than merely a `share/`
    directory.  Without this, a wrapper shim on PATH -- `~/.local/bin/ecppack`
    here is a 286-byte script -- makes `~/.local` look like a suite root, which
    then hides the actual database two directories away and reports it missing.
    """
    return (os.path.isfile(os.path.join(p, "environment"))
            or os.path.isdir(os.path.join(p, "share", "trellis")))


def suite_root():
    """The oss-cad-suite install root, or None.

    `$OSS_CAD_SUITE` first, then the location implied by whichever suite binary
    is on PATH -- deriving the root from a found tool is better than guessing,
    because it cannot disagree with the tool actually being run.
    """
    env = os.environ.get("OSS_CAD_SUITE")
    if env:
        return _expand(env)
    for probe in ("ecppack", "ecpunpack", "yosys", "nextpnr-ecp5"):
        found = shutil.which(probe)
        if found:
            # <root>/bin/<tool>, and the suite also symlinks into <root>/libexec.
            root = os.path.dirname(os.path.dirname(os.path.realpath(found)))
            if _is_suite_root(root):
                return root
    for cand in _SUITE_ROOTS:
        p = _expand(cand)
        if _is_suite_root(p):
            return p
    return None


def oss_cad_bin(required=False):
    """The suite's bin directory, or None (or die when `required`)."""
    root = suite_root()
    if root and os.path.isdir(os.path.join(root, "bin")):
        return os.path.join(root, "bin")
    if required:
        die("cannot find the oss-cad-suite bin directory; set $OSS_CAD_SUITE "
            f"to the install root (tried PATH and {', '.join(_SUITE_ROOTS)})")
    return None


def tool(name, env_var=None, required=False):
    """Resolve an executable: $env_var, then PATH, then the suite's bin.

    Returns the bare `name` as a last resort when not `required`, so a caller
    that only ever shells out still produces the familiar
    "command not found" rather than a confusing `None` -- but see `required`
    for anything whose absence should stop the run.
    """
    if env_var:
        p = os.environ.get(env_var)
        if p:
            return p
    found = shutil.which(name)
    if found:
        return found
    bindir = oss_cad_bin()
    if bindir:
        for sub in ("bin", "libexec"):
            cand = os.path.join(os.path.dirname(bindir), sub, name)
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
    if required:
        die(f"cannot find {name!r}; put it on PATH" +
            (f" or set ${env_var}" if env_var else ""))
    return name


def have(name, env_var=None):
    """True when `tool()` resolved to something that actually exists."""
    p = tool(name, env_var)
    return os.path.isabs(p) and os.path.isfile(p)


def trellis_dbroot(required=True):
    """The device (tile) database directory.

    Pluribus OWNS this now: `device-db/` in the repo is the canonical tree, and
    it wins over any external copy.  It is DEVICE data -- what bit F25B0 means in
    a CIB_EBR1 tile -- which is a property of the silicon, identical for every
    board using that part.  That is engine data, like schema.py; it is not board
    data, and the board-agnostic rule never applied to it.

    Owning it fixes a real failure.  While the tree was external, two copies had
    diverged: the fuzz corpus validated against one and a board pipeline lifted
    against another, in tile types that board actually used, so the two results
    were never comparable.  One copy had also been hand-edited with a correction
    that db_overrides.py already applies -- an invisible edit that any re-clone
    or rebuild would have silently dropped.

    The vendored tree is kept PRISTINE upstream.  Every pluribus correction goes
    in db_overrides.py and is applied on top at decode time.  Never hand-edit
    device-db/: an edit there is invisible to review and cannot survive a
    regeneration.

    $TRELLIS_DBROOT still wins, for A/B testing against another tree.
    """
    env = os.environ.get("TRELLIS_DBROOT")
    if env:
        return env
    own = os.path.join(REPO, "device-db")
    if os.path.isdir(own):
        return own
    root = suite_root()
    if root:
        cand = os.path.join(root, "share", "trellis", "database")
        if os.path.isdir(cand):
            return cand
    # A source build of prjtrellis, which keeps the database in the checkout.
    build = os.environ.get("TRELLIS_BUILD")
    if build:
        cand = os.path.join(os.path.dirname(_expand(build)), "database")
        if os.path.isdir(cand):
            return cand
    if required:
        die("cannot find the prjtrellis database; set $TRELLIS_DBROOT to "
            "<prjtrellis>/database or <oss-cad-suite>/share/trellis/database")
    return None


def suite_share(*parts, required=False):
    """A path under the suite's `share/`, e.g. suite_share("yosys", "ecp5").

    Derived rather than defaulted so the yosys cell library and the Trellis
    database always come from the SAME install as the tools being run.
    """
    root = suite_root()
    if root:
        cand = os.path.join(root, "share", *parts)
        if os.path.exists(cand):
            return cand
    if required:
        die(f"cannot find share/{os.path.join(*parts)} in the oss-cad-suite; "
            "set $OSS_CAD_SUITE to the install root")
    return None


def diamond_root(required=True):
    """The Lattice Diamond install root.

    `$DIAMOND` wins; otherwise the newest versioned directory under a
    user-relative `~/lscc/diamond`, which is the installer's own default layout.
    Version is discovered rather than pinned so a Diamond upgrade does not
    silently leave scripts pointing at the old tree -- and picking the tree
    matters more here than elsewhere, because Diamond's device directories are
    themselves a trap: `ep5c00` is LatticeECP3, while ECP5 is `sa5p00` (#92).
    """
    env = os.environ.get("DIAMOND")
    if env:
        if os.path.isdir(_expand(env)):
            return _expand(env)
        die(f"$DIAMOND is set to {env!r} but that is not a directory")
    base = _expand("~/lscc/diamond")
    if os.path.isdir(base):
        vers = sorted((d for d in os.listdir(base)
                       if os.path.isdir(os.path.join(base, d))),
                      key=lambda s: [int(p) if p.isdigit() else p
                                     for p in s.replace(".", " ").split()],
                      reverse=True)
        if vers:
            return os.path.join(base, vers[0])
    if required:
        die("cannot find Lattice Diamond; set $DIAMOND to the install root "
            "(e.g. <prefix>/lscc/diamond/3.14)")
    return None


def gowin_python(required=False):
    """An interpreter that can import apycula.

    apycula only imports under the suite's own interpreter, so this is the
    suite's python rather than `sys.executable`; scripts/gowin_unpack.py runs as
    a subprocess under it for exactly that reason.
    """
    env = os.environ.get("PLURIBUS_GOWIN_PYTHON")
    if env:
        return env
    root = suite_root()
    if root:
        for rel in (("py3bin", "python3"), ("bin", "python3")):
            cand = os.path.join(root, *rel)
            if os.path.isfile(cand):
                return cand
    if required:
        die("cannot find an interpreter with apycula; set "
            "$PLURIBUS_GOWIN_PYTHON to <oss-cad-suite>/py3bin/python3")
    return None


def sibling_repo(name, env_var, what, required=True):
    """A directory in another checkout, found beside this one.

    Order: `$env_var`, then `<parent of pluribus>/<name>`.  The sibling search is
    what makes this work with no configuration -- checkouts of related projects
    normally live next to each other, so `../awto-2000` and `../cynthion-workspace`
    resolve correctly without naming anybody's home directory.  Relative to the
    repository, not to a machine, so it survives being cloned anywhere.
    """
    p = os.environ.get(env_var)
    if p:
        if os.path.isdir(_expand(p)):
            return _expand(p)
        die(f"${env_var} is set to {p!r} but that is not a directory")
    for cand in _sibling_candidates(name):
        if os.path.isdir(cand):
            return cand
    if required:
        die(f"cannot find the {what}; set ${env_var}, or check {name!r} out "
            f"beside this repository (searched under {os.path.dirname(REPO)})")
    return None


def _sibling_candidates(name):
    """Where a related checkout plausibly sits, nearest first.

    Beyond a direct sibling, one level of host/owner nesting is searched, because
    a `<root>/github.com/<owner>/<repo>` layout is common and prjtrellis in fact
    lives there here.  Bounded to two globbed levels deliberately: an unbounded
    walk of a directory holding dozens of checkouts would be slow and could match
    something unintended.
    """
    parent = os.path.dirname(REPO)
    yield os.path.join(parent, name)
    for pattern in (os.path.join(parent, "*", name),
                    os.path.join(parent, "*", "*", name)):
        for hit in sorted(glob.glob(pattern)):
            yield hit


def external_dir(env_var, what, required=True):
    """A directory in ANOTHER repository -- environment or die, never guessed.

    There is no conventional location for someone else's checkout, so inventing
    a default here would only reintroduce the machine-specific path this module
    exists to remove.
    """
    p = os.environ.get(env_var)
    if p and os.path.isdir(_expand(p)):
        return _expand(p)
    if p:
        die(f"${env_var} is set to {p!r} but that is not a directory")
    if required:
        die(f"set ${env_var} to the {what} directory (no default: it lives in a "
            "different repository)")
    return None


def die(msg):
    """Fail fast, matching db.die()'s contract."""
    sys.exit(f"{os.path.basename(sys.argv[0]) or 'toolchain'}: {msg}")


def summary():
    """Human-readable resolution report, for --show-toolchain style output."""
    root = suite_root()
    return {
        "oss_cad_suite": root,
        "oss_cad_bin": oss_cad_bin(),
        "trellis_dbroot": trellis_dbroot(required=False),
        "gowin_python": gowin_python(),
        "ecpunpack": tool("ecpunpack", "ECPUNPACK"),
        "ecppack": tool("ecppack", "ECPPACK"),
        "yosys": tool("yosys", "YOSYS"),
    }


if __name__ == "__main__":
    for k, v in summary().items():
        mark = "ok " if v and os.path.exists(str(v)) else "MISSING"
        print(f"{mark} {k:16s} {v}")
