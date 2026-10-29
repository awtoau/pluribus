"""RCF element names (A7): `TYPE:X<x>Y<y>S<z>I<index>` -> exact key over (type, x, y, z, index).  No aliasing, no fallback."""
import re

NAME = re.compile(r"\b([A-Z][A-Z0-9_]*):X(\d+)Y(\d+)S(\d+)I(\d+)\b")


def rcf_names(path):
    """Distinct (type, x, y, z, index) tuples of one routing.rcf."""
    with open(path) as f:
        text = f.read()
    return sorted({(m[1], int(m[2]), int(m[3]), int(m[4]), int(m[5])) for m in NAME.finditer(text)})
