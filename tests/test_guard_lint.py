"""Lint: scripts/*.py must not run an external EDA tool through bare subprocess (#122).

- Every subprocess.run/Popen/check_output/check_call/call whose enclosing function mentions a known
  tool name must go through heavy_guard.guarded / run_stall_guarded instead.
- Exceptions live in ALLOW, keyed (file, function), each with its reason.
"""
import ast
import re
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
CALLS = {"run", "Popen", "check_output", "check_call", "call"}
TOOL_RE = re.compile(
    r"quartus_\w+|diamondc|pnmainc|ldbanno|bstool|nextpnr|yosys|iverilog|\bvvp\b|vsim|vlog|vcom|gw_sh|"
    r"mistral|ecpunpack|ecppack|unsquashfs", re.I)

# (file, function) -> reason. Own stall guard (output-silence based, kills on expiry) or not a tool run.
ALLOW = {
    ("cycloneiv_fuzz.py", "run"): "own output-stall + overall guard (STALL_S/OVERALL_S, measured 3x)",
    ("cyclonev_corpus_build.py", "run"): "own output-stall + overall guard (STALL_S/OVERALL_S, measured 3x)",
    ("questa.py", "_run"): "own output-stall + LIMIT_S guard",
    ("cyclonev_lifted_sim_check.py", "run"): "own CPU-progress stall + overall guard",
    ("efb_oracle.py", "run_diamond"): "own log-growth stall + OVERALL_S guard",
    ("machxo2_construct_build.py", "run_flow"): "own log-growth stall + backstop guard",
    ("verify_common.py", "probe"): "cancellable yosys sat probe: Popen handle is tracked and killed on cancel",
    ("cyclonev_clock_tree_extract.py", "main"): "version-control query only, no EDA tool",
    ("carve_classify_flow.py", "peek"): "curl range fetch, no EDA tool",
    ("fuzz_lec.py", "run_candidate"): "runs verilog.py (python) only; the yosys call is guarded",
    ("run_pipeline.py", "main"): "runs pluribus python stages only",
    ("sim_no_ip.py", "main"): "runs verilog.py (python) only; iverilog is guarded",
    ("cycloneiv_corpus_fetch.py", "analyze_one"): "one quartus_cpf .sof->.rbf conversion with subprocess timeout CPF_TIMEOUT_S",
}
ALLOW_FILES = {"heavy_guard.py": "implements the guard"}


def _mentions_tool(fn):
    parts = []
    doc = ast.get_docstring(fn, clean=False) if isinstance(fn, (ast.FunctionDef, ast.Module)) else None
    for n in ast.walk(fn):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value != doc:
            parts.append(n.value)
        elif isinstance(n, ast.Name):
            parts.append(n.id)
        elif isinstance(n, ast.Attribute):
            parts.append(n.attr)
    return bool(TOOL_RE.search("\n".join(parts)))


def _is_sp_call(n):
    f = n.func
    return isinstance(f, ast.Attribute) and f.attr in CALLS and isinstance(f.value, ast.Name) \
        and f.value.id == "subprocess"


def violations():
    out = []
    for path in sorted(SCRIPTS.glob("*.py")):
        if path.name in ALLOW_FILES:
            continue
        tree = ast.parse(path.read_text(), str(path))
        stack = []

        def visit(node):
            is_fn = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            if is_fn:
                stack.append(node)
            if isinstance(node, ast.Call) and _is_sp_call(node):
                fn = stack[-1] if stack else tree
                name = stack[-1].name if stack else "<module>"
                if _mentions_tool(fn) and (path.name, name) not in ALLOW:
                    out.append(f"{path.name}:{node.lineno} in {name}()")
            for c in ast.iter_child_nodes(node):
                visit(c)
            if is_fn:
                stack.pop()

        visit(tree)
    return out


def test_no_unguarded_tool_subprocess():
    v = violations()
    assert not v, ("external tool run via bare subprocess; use heavy_guard.guarded / run_stall_guarded "
                   "or add to ALLOW with a reason (#122):\n  " + "\n  ".join(v))


def test_allowlist_has_no_stale_entries():
    stale = []
    for (fname, func), _why in ALLOW.items():
        p = SCRIPTS / fname
        if not p.exists():
            stale.append(f"{fname} missing")
            continue
        src = p.read_text()
        if func != "<module>" and not re.search(rf"def {func}\(", src):
            stale.append(f"{fname}:{func} missing")
    assert not stale, stale
