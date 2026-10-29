"""sof / rbf file helpers (black box: the vendor converter is the oracle).  Used by the tables script and tests."""
import gzip
import hashlib
import os
import struct
import subprocess
import sys

import numpy as np

from . import plane as P

SCRIPTS = os.path.join(P.REPO, "scripts")
# quartus_cpf sof -> rbf on a 4.7 MB image: ~2 s measured (cycloneiv_corpus_fetch.CPF_TIMEOUT_S = 60 keeps ~30x for host load); expiry -> RuntimeError
CPF_TIMEOUT_S = 60


class VendorMissing(FileNotFoundError):
    pass


def quartus_bin():
    sys.path.insert(0, SCRIPTS)
    import toolchain
    b = toolchain.quartus_bin(required=False)
    if not b or not os.path.isfile(os.path.join(b, "quartus_cpf")):
        raise VendorMissing("quartus_cpf not found ($PLURIBUS_QUARTUS_BIN)")
    return b


def programmer_sof(name):
    p = os.path.join(quartus_bin(), "..", "common", "devinfo", "programmer", name)
    p = os.path.normpath(p)
    if not os.path.exists(p):
        raise VendorMissing(p)
    return p


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def _sections(d):
    p = 12
    while p < len(d):
        tag, ln = struct.unpack_from("<HI", d, p)
        yield tag, p + 6, ln
        p += 6 + ln


def read_sof(path):
    """(decompressed bytes, offset, length) of the CRAM section (tag 17)."""
    d = gzip.decompress(open(path, "rb").read())
    for tag, off, ln in _sections(d):
        if tag == 17:
            return d, off, ln
    raise ValueError("no tag 17 section")


def sof_bits(path):
    """CRAM data bits of a sof as uint8 0/1, length N_BITS (12-byte section header skipped)."""
    d, off, ln = read_sof(path)
    b = np.unpackbits(np.frombuffer(d[off + 12:off + ln], np.uint8), bitorder="little")
    if len(b) != P.N_BITS:
        raise ValueError(f"sof data {len(b)} bits, want {P.N_BITS} (other die?)")
    return b


# source: sof trailer CRC16, reflected 0x8408 (= 0x1021 reversed), init 0xFFFF, complemented (vendor sof, docs/cycloneiv-bitstream.md)
def _crc_table():
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0x8408 if c & 1 else c >> 1
        t.append(c)
    return t


_T = _crc_table()


def sof_crc(buf):
    c = 0xFFFF
    for b in buf:
        c = (c >> 8) ^ _T[(c ^ b) & 0xFF]
    return ~c & 0xFFFF


def make_sof(template, out, bits):
    """Write a sof equal to `template` with the CRAM data replaced by `bits` (uint8 0/1)."""
    d, off, ln = read_sof(template)
    sec = bytearray(d[off:off + ln])
    sec[12:] = np.packbits(bits, bitorder="little").tobytes()
    new = bytearray(d[:off] + bytes(sec) + d[off + ln:])
    new[-2:] = struct.pack("<H", sof_crc(bytes(new[:-2])))
    with open(out, "wb") as f:
        f.write(gzip.compress(bytes(new), 1))


def to_rbf(sof, rbf):
    r = subprocess.run([os.path.join(quartus_bin(), "quartus_cpf"), "-c", "-o", "bitstream_compression=off", sof, rbf],
                       capture_output=True, text=True, timeout=CPF_TIMEOUT_S)
    if r.returncode:
        raise RuntimeError(f"quartus_cpf rc={r.returncode} on {sof}: {r.stdout[-200:]} {r.stderr[-200:]}")


def rbf_cram(path):
    """uint8 [FRAMES, ROWS, 8]: CRAM bit (r, j - 1, k) of an rbf."""
    b = np.fromfile(path, np.uint8)
    lo = P.RBF_HEADER + P.RBF_PRE_FRAMES * P.RBF_FRAME_BYTES
    fr = b[lo:lo + P.FRAMES * P.RBF_FRAME_BYTES].reshape(P.FRAMES, P.RBF_FRAME_BYTES)
    return np.unpackbits(fr[:, 1:1 + P.ROWS, None], axis=2, bitorder="little")
