//! Cyclone V bitstream compression codec -- Rust port of Mistral's
//! libmistral/cv-files.cc `rbf_load`/`rbf_save` CRAM (de)compression.
//!
//! Mistral's nibble zero-suppression codec (NOT RLE, despite old docs):
//! each output byte pair (2 bytes) is preceded by a 1-nibble mask whose 4
//! bits say which of the pair's 4 nibbles are non-zero and present in the
//! stream; zero nibbles are omitted entirely. This module ports exactly
//! that transform, both directions, plus the CRAM y-position bit-folding
//! arithmetic that sits around it (shared between the compressed and
//! uncompressed paths in the original).
//!
//! Scope this session: the CRAM compression/decompression core only --
//! ORAM header and PRAM (fixed-block) framing are NOT implemented here (see
//! docs/cyclonev-rust-port.md). Operates on a CRAM "frame" byte buffer
//! (the `framed`/`framed_cram` buffer in cv-files.cc), not a full .rbf file.

use anyhow::{bail, Result};

/// Unpack one CRAM frame area from Mistral's nibble zero-suppression codec.
///
/// Mirrors cv-files.cc rbf_load's compressed branch exactly:
/// ```c
/// while(uncomp < &framed_cram[framed_bytes]) {
///   uint8_t key = r();
///   uint8_t v;
///   v = key & 1 ? r() : 0;
///   v |= key & 2 ? r() << 4 : 0;
///   *uncomp++ = v;
///   v = key & 4 ? r() : 0;
///   v |= key & 8 ? r() << 4 : 0;
///   *uncomp++ = v;
/// }
/// ```
/// `r()` reads one nibble at a time from `comp`, low nibble first then high
/// nibble of each source byte (the `high` flag below mirrors that exactly).
///
/// `framed_bytes` is the exact decompressed size the caller expects
/// (`cram_sx * cram_frame_bytes` in the original) -- decompression stops the
/// moment that many bytes have been produced, same as the C++ loop bound.
pub fn nibble_decompress(comp: &[u8], framed_bytes: usize) -> Result<Vec<u8>> {
    /// Nibble-at-a-time reader over `comp`: low nibble of each source byte
    /// first, then its high nibble (mirrors cv-files.cc's `r()` lambda).
    struct NibbleReader<'a> {
        comp: &'a [u8],
        pos: usize,
        high: bool,
    }
    impl<'a> NibbleReader<'a> {
        fn read(&mut self) -> Result<u8> {
            if self.pos >= self.comp.len() {
                bail!("nibble_decompress: ran out of input at comp byte {}", self.pos);
            }
            if self.high {
                let v = self.comp[self.pos] >> 4;
                self.high = false;
                self.pos += 1;
                Ok(v)
            } else {
                let v = self.comp[self.pos] & 0xf;
                self.high = true;
                Ok(v)
            }
        }
    }

    let mut r = NibbleReader { comp, pos: 0, high: false };
    let mut out = Vec::with_capacity(framed_bytes);

    while out.len() < framed_bytes {
        let key = r.read()?;

        let mut v = if key & 1 != 0 { r.read()? } else { 0 };
        if key & 2 != 0 {
            v |= r.read()? << 4;
        }
        out.push(v);

        let mut v2 = if key & 4 != 0 { r.read()? } else { 0 };
        if key & 8 != 0 {
            v2 |= r.read()? << 4;
        }
        out.push(v2);
    }

    out.truncate(framed_bytes);
    Ok(out)
}

/// Pack one CRAM frame area with Mistral's nibble zero-suppression codec.
///
/// Mirrors cv-files.cc rbf_save's compressed branch exactly:
/// ```c
/// for(uint32_t i = 0; i < framed_bytes; i += 2) {
///   uint8_t sv1 = *framed++;
///   uint8_t sv2 = *framed++;
///   uint8_t mask = 0;
///   if(sv1 & 0x0f) mask |= 1;
///   if(sv1 & 0xf0) mask |= 2;
///   if(sv2 & 0x0f) mask |= 4;
///   if(sv2 & 0xf0) mask |= 8;
///   w(mask);
///   if(mask & 1) w(sv1 & 0xf);
///   if(mask & 2) w(sv1 >> 4);
///   if(mask & 4) w(sv2 & 0xf);
///   if(mask & 8) w(sv2 >> 4);
/// }
/// while(high) w(0xf);
/// ```
/// `w()` packs two nibbles per output byte, low nibble first (`high` flag
/// mirrors the original exactly, including the trailing pad-with-0xf if an
/// odd number of nibbles was written, so the output byte count matches a
/// real mistral encode bit-for-bit, not just functionally).
pub fn nibble_compress(framed: &[u8]) -> Vec<u8> {
    assert!(framed.len().is_multiple_of(2), "framed buffer must have even length (byte pairs)");

    /// Nibble-at-a-time writer, packing low nibble then high nibble per
    /// output byte (mirrors cv-files.cc's `w()` lambda exactly).
    struct NibbleWriter {
        out: Vec<u8>,
        high: bool,
    }
    impl NibbleWriter {
        fn write(&mut self, nib: u8) {
            if self.high {
                *self.out.last_mut().unwrap() |= nib << 4;
                self.high = false;
            } else {
                self.out.push(nib);
                self.high = true;
            }
        }
    }

    let mut w = NibbleWriter { out: Vec::new(), high: false };

    for pair in framed.chunks_exact(2) {
        let (sv1, sv2) = (pair[0], pair[1]);
        let mut mask = 0u8;
        if sv1 & 0x0f != 0 {
            mask |= 1;
        }
        if sv1 & 0xf0 != 0 {
            mask |= 2;
        }
        if sv2 & 0x0f != 0 {
            mask |= 4;
        }
        if sv2 & 0xf0 != 0 {
            mask |= 8;
        }
        w.write(mask);
        if mask & 1 != 0 {
            w.write(sv1 & 0xf);
        }
        if mask & 2 != 0 {
            w.write(sv1 >> 4);
        }
        if mask & 4 != 0 {
            w.write(sv2 & 0xf);
        }
        if mask & 8 != 0 {
            w.write(sv2 >> 4);
        }
    }

    while w.high {
        w.write(0xf);
    }

    w.out
}

/// CRAM frame geometry derived the same way rbf_load/rbf_save derive it from
/// `die_info` before touching the codec -- kept separate from DieInfo so the
/// codec module has no SQLite dependency.
pub struct CramFrameGeom {
    pub cram_frame_bytes: usize,
    pub cram_frame_bits: u32,
    pub offset: i32,
}

impl CramFrameGeom {
    /// `cram_sy` and `frame_size` are the two die_info fields this depends on:
    /// ```c
    /// uint32_t padding = (64 - (di.cram_sy & 63)) ^ 32;
    /// uint32_t cram_frame_size = di.cram_sy + 256 + padding;
    /// uint32_t cram_frame_bytes = cram_frame_size / 8;
    /// uint32_t cram_frame_bits = di.frame_size - 7;
    /// int32_t offset = padding - 32;
    /// ```
    pub fn new(cram_sy: u32, frame_size: u16) -> Self {
        let padding = (64 - (cram_sy & 63)) ^ 32;
        let cram_frame_size = cram_sy + 256 + padding;
        let cram_frame_bytes = (cram_frame_size / 8) as usize;
        let cram_frame_bits = frame_size as u32 - 7;
        let offset = padding as i32 - 32;
        CramFrameGeom { cram_frame_bytes, cram_frame_bits, offset }
    }
}

/// Unpack the per-column CRAM bit array from decompressed frame bytes into a
/// flat `cram_sx * cram_sy` bit array (1 bit per cell, LSB-first packed into
/// bytes), mirroring rbf_load's post-decompression loop:
/// ```c
/// for(uint32_t x = 0; x != di.cram_sx; x++) {
///   const uint8_t *d = framed + x*cram_frame_bytes;
///   for(uint32_t y = 32; y != di.cram_sy; y++) {
///     uint32_t ya = (y + offset) % cram_frame_bits;
///     uint32_t yb = (y + offset) / cram_frame_bits;
///     uint32_t pos = 224 + (31^yb) + 32*ya;
///     if((d[pos >> 3] >> (pos & 7)) & 1) cram[x + cram_sx*y] = 1;
///   }
/// }
/// ```
pub fn unpack_cram_bits(framed: &[u8], cram_sx: u32, cram_sy: u32, geom: &CramFrameGeom) -> Vec<u8> {
    let total_bits = (cram_sx as usize) * (cram_sy as usize);
    let mut cram = vec![0u8; total_bits.div_ceil(8)];

    for x in 0..cram_sx {
        let d = &framed[(x as usize) * geom.cram_frame_bytes..];
        for y in 32..cram_sy {
            let yi = y as i64 + geom.offset as i64;
            let ya = yi.rem_euclid(geom.cram_frame_bits as i64) as u32;
            let yb = yi.div_euclid(geom.cram_frame_bits as i64) as u32;
            let pos = 224u32 + (31 ^ yb) + 32 * ya;
            let bit = (d[(pos >> 3) as usize] >> (pos & 7)) & 1;
            if bit != 0 {
                let cpos = (x as usize) + (cram_sx as usize) * (y as usize);
                cram[cpos >> 3] |= 1 << (cpos & 7);
            }
        }
    }
    cram
}

/// Inverse of [`unpack_cram_bits`]: fold a flat CRAM bit array back into
/// per-column frame bytes, mirroring rbf_save's pre-compression loop. The
/// caller must pre-zero `framed` to its full `cram_sx * cram_frame_bytes`
/// size (rbf_save does this via `std::vector<uint8_t> framed_cram(..., 0x00)`
/// before this loop runs) and have already written the two fixed per-die
/// framing markers at offsets 0 and `(cram_sx-1)*cram_frame_bytes` (the
/// 0x843e01 / 0x429f00 header bytes rbf_save hardcodes) -- those are file
/// framing constants, not part of the CRAM<->frame bit transform itself, so
/// they stay out of scope here and belong in a higher-level rbf_save port.
pub fn pack_cram_bits(cram: &[u8], cram_sx: u32, cram_sy: u32, geom: &CramFrameGeom, framed: &mut [u8]) {
    for x in 0..cram_sx {
        let d = &mut framed[(x as usize) * geom.cram_frame_bytes..(x as usize + 1) * geom.cram_frame_bytes];
        for y in 32..cram_sy {
            let cpos = (x as usize) + (cram_sx as usize) * (y as usize);
            let bit = (cram[cpos >> 3] >> (cpos & 7)) & 1;
            if bit != 0 {
                let yi = y as i64 + geom.offset as i64;
                let ya = yi.rem_euclid(geom.cram_frame_bits as i64) as u32;
                let yb = yi.div_euclid(geom.cram_frame_bits as i64) as u32;
                let pos = 224u32 + (31 ^ yb) + 32 * ya;
                d[(pos >> 3) as usize] |= 1 << (pos & 7);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nibble_roundtrip_empty() {
        let framed: Vec<u8> = vec![];
        let comp = nibble_compress(&framed);
        let back = nibble_decompress(&comp, 0).unwrap();
        assert_eq!(back, framed);
    }

    #[test]
    fn nibble_roundtrip_all_zero() {
        let framed = vec![0u8; 256];
        let comp = nibble_compress(&framed);
        // All-zero input -> every mask nibble is 0, no data nibbles at all,
        // so compressed size is exactly framed_bytes/2 (one mask nibble per
        // byte pair), packed 2 nibbles/byte -> framed_bytes/4 bytes.
        assert_eq!(comp.len(), framed.len() / 4);
        let back = nibble_decompress(&comp, framed.len()).unwrap();
        assert_eq!(back, framed);
    }

    #[test]
    fn nibble_roundtrip_all_ff() {
        let framed = vec![0xffu8; 256];
        let comp = nibble_compress(&framed);
        let back = nibble_decompress(&comp, framed.len()).unwrap();
        assert_eq!(back, framed);
    }

    #[test]
    fn nibble_roundtrip_random_patterns() {
        // Deterministic pseudo-random pattern (no external RNG dependency),
        // covering every nibble value and both even/odd total nibble counts.
        for len in [2usize, 4, 6, 100, 1024, 4096 + 2] {
            let mut framed = Vec::with_capacity(len);
            let mut state: u32 = 0x12345678 ^ len as u32;
            for _ in 0..len {
                state = state.wrapping_mul(1103515245).wrapping_add(12345);
                framed.push((state >> 16) as u8);
            }
            let comp = nibble_compress(&framed);
            let back = nibble_decompress(&comp, framed.len()).unwrap();
            assert_eq!(back, framed, "roundtrip mismatch at len={len}");
        }
    }

    #[test]
    fn nibble_roundtrip_sparse() {
        // Mostly-zero with scattered set bits -- the realistic CRAM case
        // zero-suppression is meant for.
        let mut framed = vec![0u8; 2048];
        for i in (0..framed.len()).step_by(37) {
            framed[i] = (i % 251) as u8;
        }
        let comp = nibble_compress(&framed);
        assert!(comp.len() < framed.len(), "sparse data should compress smaller");
        let back = nibble_decompress(&comp, framed.len()).unwrap();
        assert_eq!(back, framed);
    }

    #[test]
    fn nibble_compress_then_decompress_then_compress_is_stable() {
        // Decompress(Compress(x)) == x is tested above. This additionally
        // checks Compress(Decompress(Compress(x))) == Compress(x), i.e. the
        // compressed encoding itself is a stable fixed point once produced
        // by this encoder (no second encoding ambiguity introduced by us).
        let mut framed = vec![0u8; 512];
        for i in 0..framed.len() {
            framed[i] = ((i * 7 + 3) % 256) as u8;
        }
        let comp1 = nibble_compress(&framed);
        let back = nibble_decompress(&comp1, framed.len()).unwrap();
        let comp2 = nibble_compress(&back);
        assert_eq!(comp1, comp2);
    }

    #[test]
    fn cram_bit_roundtrip() {
        // Real e50f dimensions (cram_sx reduced to keep the test fast; the
        // y-axis geometry -- cram_sy and frame_size -- must stay at the real
        // die's scale, since the position formula's `ya`/`yb` split only
        // stays in-bounds when cram_sy and frame_size are scaled together
        // the way an actual die's numbers are, confirmed against
        // mistral/libmistral/cvd-e50f.cc: cram_sy=3928, frame_size=129).
        let cram_sx = 8u32; // trimmed from e50f's real 4958 for test speed
        let cram_sy = 3928u32; // e50f's real cram_sy
        let frame_size = 129u16; // e50f's real frame_size
        let geom = CramFrameGeom::new(cram_sy, frame_size);

        // Deterministic pseudo-random CRAM bit pattern.
        let total_bits = (cram_sx * cram_sy) as usize;
        let mut cram = vec![0u8; total_bits.div_ceil(8)];
        let mut state: u32 = 0xdeadbeef;
        for bit in 0..total_bits {
            state = state.wrapping_mul(1103515245).wrapping_add(12345);
            if state & 1 != 0 {
                cram[bit >> 3] |= 1 << (bit & 7);
            }
        }

        let mut framed = vec![0u8; (cram_sx as usize) * geom.cram_frame_bytes];
        pack_cram_bits(&cram, cram_sx, cram_sy, &geom, &mut framed);
        let cram_back = unpack_cram_bits(&framed, cram_sx, cram_sy, &geom);

        // Only y in [32, cram_sy) round-trips (y<32 is never touched by
        // either direction, matching the original's loop bounds exactly).
        for x in 0..cram_sx {
            for y in 32..cram_sy {
                let cpos = (x as usize) + (cram_sx as usize) * (y as usize);
                let bit_in = (cram[cpos >> 3] >> (cpos & 7)) & 1;
                let bit_out = (cram_back[cpos >> 3] >> (cpos & 7)) & 1;
                assert_eq!(bit_in, bit_out, "mismatch at x={x} y={y}");
            }
        }
    }
}
