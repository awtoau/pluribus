"""Closed vocabulary + weakest-link rule (docs/provenance-and-feedback.md section 2).

Tier is fixed at creation and never promoted; status moves. Anything outside these sets dies.
Coverage names (verified, measured, sampled, pattern-predicted, decoded, statistical, ...): Glossary in the doc above.
"""
import db

# strongest first; weakest(chain) = the right-most member present
TIERS = ("measured", "vendor-decoded", "eliminated", "pattern-predicted", "statistical",
         "never-exercised", "unknown")
STATUSES = ("open", "confirmed", "verified-by-sampling", "oracle-verified", "suspect", "refuted",
            "superseded", "conflict", "parked")
VERIFIED_STATUSES = ("oracle-verified", "verified-by-sampling")
KNOWN_STATUSES = ("open", "confirmed", "verified-by-sampling", "oracle-verified")   # counts as known in coverage
EVIDENCE_KINDS = ("specimen-pair", "vendor-decode", "oracle-compare", "audit", "elimination",
                  "absence", "image-hit", "roundtrip", "derived-table")   # derived-table: computed from other rows by a named generator, kept verbatim
CONFIRMING_KINDS = ("specimen-pair", "audit", "oracle-compare", "roundtrip")   # never a claim (circularity)
SPACES = ("bit", "tile-bit", "pip", "mux-input", "cell-param", "net-attr", "stream-option",
          "coord-map", "port-map")
SCOPE_KINDS = ("cells", "range", "tile", "tile-class", "keys", "formula", "all")
SCOPE_SPECIFICITY = {"cells": 0, "keys": 0, "tile": 1, "range": 2, "tile-class": 3, "formula": 4, "all": 5}
EXPECTATION_STATUSES = ("open", "confirmed", "refuted", "parked")
UNKNOWN_REASONS = ("unasked", "unforceable", "seen-in-image", "orphan", "conflict", "not-required-by-corpus")
UNKNOWN_STATUSES = ("open", "parked", "promoted")
MATCHER_KINDS = ("deterministic", "statistical", "llm-proposed")
AUDIT_REASONS = ("suspect", "sampling", "new-pattern", "corpus-fail")
AUDIT_STATUSES = ("queued", "built", "confirmed", "refuted", "cancelled")
EVENTS = ("created", "confirmed", "refuted", "suspect", "cleared", "superseded", "audited", "stale",
          "conflict", "parked", "reopened", "hit", "predicted")
CORPUS_KINDS = ("oracle-build", "third-party-image", "roundtrip", "lec")
# sampling rule: confirmations at N distinct scopes graduate a pattern to verified-by-sampling
SAMPLING_N = {1: 3, 2: 5}

# families registry rows (one database per family; scripts/claims_register.py and evidence_io.ensure_family)
FAMILIES = {
    "cycloneiv": dict(vendor="altera", name="Cyclone IV", lut_inputs=4, bit_model="frame,v",
                      device_db="Quartus asm.ddb / routing.ddb (decoded, docs/cycloneiv-ddb-format.md)"),
    "cyclonev":  dict(vendor="altera", name="Cyclone V", lut_inputs=6, bit_model="cram x,y",
                      device_db="cv_* tables (Mistral generator inputs)"),
    "machxo2":   dict(vendor="lattice", name="MachXO2", lut_inputs=4, bit_model="tile,frame,bit",
                      device_db="device-db/MachXO2 (prjtrellis)"),
    "ecp5":      dict(vendor="lattice", name="ECP5", lut_inputs=4, bit_model="tile,frame,bit",
                      device_db="device-db/ECP5 (prjtrellis)"),
    "gowin":     dict(vendor="gowin", name="GW1N", lut_inputs=4, bit_model="tile,row,col",
                      device_db="apycula chipdb"),
    "anlogic":   dict(vendor="anlogic", name="EG4", lut_inputs=4, bit_model="frame,bit",
                      device_db="Tang Dynasty fuse DB"),
}


def check(value, allowed, what):
    if value not in allowed:
        db.die(f"{what} {value!r} is not in the closed vocabulary {allowed}")
    return value


def rank(tier):
    check(tier, TIERS, "tier")
    return TIERS.index(tier)


def weakest(tiers):
    """Weakest tier in an evidence chain (a derived claim is as weak as its weakest parent)."""
    tiers = list(tiers)
    if not tiers:
        return "unknown"
    return max(tiers, key=rank)


def weakest_status(statuses):
    """Status precedence for the lift: refuted > conflict > suspect > superseded > parked > open > confirmed > verified."""
    order = ("refuted", "conflict", "suspect", "superseded", "parked", "open", "confirmed",
             "verified-by-sampling", "oracle-verified")
    statuses = [check(s, STATUSES, "status") for s in statuses]
    if not statuses:
        return "open"
    return min(statuses, key=order.index)


def is_known(tier, status):
    """Counts toward 'known' coverage: a non-unknown tier with a non-failing status."""
    return tier not in ("unknown", "never-exercised") and status in KNOWN_STATUSES
