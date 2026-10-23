"""Decode MachXO2 EFB 0x72 config blocks into EFB primitive attributes.

Every bit position below was measured with the Diamond oracle
(scripts/efb_oracle.py, single-attribute toggles; table in docs/efb-config.md).
Bits not in the table are reported as `unexplained`, never guessed.
"""

# sel byte -> (attribute enabled by the block, block name)
SEL_ENABLES = {
    0x40: ("EFB_I2C1", "I2C1"),
    0x4A: ("EFB_I2C2", "I2C2"),
    0x54: ("EFB_SPI", "SPI"),
    0x5E: ("EFB_TC", "TC"),
}
ENABLE_ATTRS = ("EFB_I2C1", "EFB_I2C2", "EFB_SPI", "EFB_TC")

# SPI block = registers 0x54..0x5D (SPICR0, SPICR1, SPICR2, SPIBR, SPICSR,
# SPITXDR, SPISR, SPIRXDR, SPIIRQ, SPIIRQEN); byte index = register offset.
SPI_REGS = ("SPICR0", "SPICR1", "SPICR2", "SPIBR", "SPICSR",
            "SPITXDR", "SPISR", "SPIRXDR", "SPIIRQ", "SPIIRQEN")
# (byte, mask, attribute): attribute ENABLED when (byte & mask) == mask
SPI_FLAGS = (
    (1, 0x40, "SPI_WAKEUP"),
    (2, 0x01, "SPI_LSB_FIRST"),
    (2, 0x02, "SPI_PHASE_ADJ"),
    (2, 0x04, "SPI_CLK_INV"),
    (2, 0x28, "SPI_SLAVE_HANDSHAKE"),
    (9, 0x02, "SPI_INTR_RXOVR"),
    (9, 0x04, "SPI_INTR_TXOVR"),
    (9, 0x08, "SPI_INTR_RXRDY"),
    (9, 0x10, "SPI_INTR_TXRDY"),
)
SPI_MODE_BIT = (2, 0x80)          # SPICR2.MSTR
SPI_ENABLE_BIT = (1, 0x80)        # SPICR1.SPE: set in every SPI-enabled stream
SPI_DIV_BYTE = 3                  # SPIBR = SPI_CLK_DIVIDER - 1 (master)
SPI_DEFAULT_BYTES = {4: 0xFF}     # SPICSR resets to 0xFF in every SPI stream
SPI_ATTR_ORDER = tuple(a for _, _, a in SPI_FLAGS)


def decode_spi(payload):
    """payload: list[int] (10 bytes).  Returns (attrs, unexplained).

    attrs: {EFB attribute: value}; unexplained: [(register, byte, bits)] set
    outside the measured table.
    """
    if len(payload) != len(SPI_REGS):
        return {}, [("length", len(payload), 0)]
    attrs = {}
    explained = {i: 0 for i in range(len(payload))}
    explained[SPI_ENABLE_BIT[0]] |= SPI_ENABLE_BIT[1]
    explained[SPI_MODE_BIT[0]] |= SPI_MODE_BIT[1]
    master = bool(payload[SPI_MODE_BIT[0]] & SPI_MODE_BIT[1])
    attrs["SPI_MODE"] = "MASTER" if master else "SLAVE"
    for byte, mask, name in SPI_FLAGS:
        explained[byte] |= mask
        attrs[name] = "ENABLED" if (payload[byte] & mask) == mask else "DISABLED"
    explained[SPI_DIV_BYTE] = 0xFF
    if master:
        attrs["SPI_CLK_DIVIDER"] = str(payload[SPI_DIV_BYTE] + 1)
    unexplained = []
    for i, b in enumerate(payload):
        rest = b & ~explained[i]
        if i in SPI_DEFAULT_BYTES:
            rest = b ^ SPI_DEFAULT_BYTES[i]
        if rest:
            unexplained.append((SPI_REGS[i], i, rest))
    return attrs, unexplained


def decode(efb_config):
    """efb_config: rows (sel, kind, length, payload) with payload a JSON/list str.

    Returns (attrs, unexplained, notes).  Peripherals with no 0x72 block are
    DISABLED (negative controls: no block <=> not enabled); EFB_UFM emits no
    block, so it is not recoverable and is left out of attrs.
    """
    import json
    attrs = {a: "DISABLED" for a in ENABLE_ATTRS}
    unexplained, notes = [], []
    for sel, _kind, _length, payload in efb_config:
        data = json.loads(payload) if isinstance(payload, str) else list(payload)
        if sel in SEL_ENABLES:
            attrs[SEL_ENABLES[sel][0]] = "ENABLED"
        if sel == 0x54:
            a, u = decode_spi(data)
            attrs.update(a)
            unexplained += u
        else:
            notes.append(f"sel 0x{sel:02x} payload {data} not decoded")
    notes.append("EFB_UFM: emits no 0x72 block, not recoverable from config")
    return attrs, unexplained, notes
