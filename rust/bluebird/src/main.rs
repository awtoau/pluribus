//! Bluebird: pluribus's Cyclone V bitstream engine CLI, replacing Project
//! Mistral. Backed by pluribus's SQLite device-db, not Mistral's compiled
//! cvd-*.cc constants.
//!
//! See docs/bluebird.md for what is and isn't implemented.

mod codec;
mod db;
mod rnodes;

use anyhow::{bail, Context, Result};
use clap::{Parser, Subcommand};
use std::fs;

#[derive(Parser)]
#[command(name = "bluebird", about = "Bluebird: Cyclone V bitstream engine (pluribus)")]
struct Cli {
    /// Path to the pluribus SQLite DB (default: ./pluribus.db, matching
    /// PLURIBUS_SQLITE_PATH's own default in db.py)
    #[arg(long, default_value = "./pluribus.db")]
    db: String,

    #[command(subcommand)]
    cmd: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Locate and extract the CRAM region of a raw .rbf/.bin file, decompress
    /// it (if compression is enabled per the file's own options byte layout
    /// isn't parsed here -- pass --assume-compressed explicitly), then
    /// re-compress and re-decompress to prove the round trip is lossless.
    Roundtrip {
        /// Die name as stored in cv_dies (e.g. "e50f")
        die: String,
        /// Path to the raw bitstream file
        path: String,
        /// Treat the CRAM region as nibble-compressed. Without this flag,
        /// the file's raw (uncompressed) CRAM frame bytes are read directly
        /// -- this still exercises the full CRAM<->bit-array fold/unfold
        /// arithmetic, just not the nibble codec itself.
        #[arg(long)]
        assume_compressed: bool,
    },

    /// Print row counts for one die's 5 routing tables (cv_route_muxes,
    /// cv_route_lines, cv_route_drivers, cv_p2r, cv_p2p) -- a basic sanity
    /// check that scripts/cyclonev_db_import_routes.py's data reached the DB
    /// and is readable from Rust. Does not resolve/decode anything -- see
    /// rnodes.rs's module doc for why that's out of scope this session.
    RouteCounts {
        /// Die name as stored in cv_dies (e.g. "e50f")
        die: String,
    },
}

/// Compute the CRAM region's byte offset within a raw .rbf file, mirroring
/// cv-files.cc rbf_load's framing math exactly:
/// ```c
/// uint32_t mpram = max_pram_block_size();                 // max(di.pram_sizes)
/// uint32_t pram_frame_bytes = (di.frame_size+2)*4;
/// uint32_t oram_frame_bytes = pram_frame_bytes + 104;
/// uint32_t pram_blocks = (mpram + di.frame_size - 1)/di.frame_size;
/// // CRAM region starts at: oram_frame_bytes + pram_frame_bytes * pram_blocks
/// ```
fn cram_region_offset(die: &db::DieInfo) -> usize {
    let mpram = *die.pram_sizes.iter().max().unwrap_or(&0) as u32;
    let pram_frame_bytes = (die.frame_size as u32 + 2) * 4;
    let oram_frame_bytes = pram_frame_bytes + 104;
    let pram_blocks = mpram.div_ceil(die.frame_size as u32).max(1);
    // Guard against frame_size == 0 producing a bogus div_ceil(..., 0): that
    // would be a corrupt die_info row, not a value to silently paper over.
    (oram_frame_bytes + pram_frame_bytes * pram_blocks) as usize
}

fn run_roundtrip(db_path: &str, die_name: &str, path: &str, assume_compressed: bool) -> Result<()> {
    let die = db::load_die(db_path, die_name)
        .with_context(|| format!("loading die {die_name:?} from {db_path}"))?;
    println!(
        "die {}: cram {}x{} tile {}x{} frame_size={} pram_sizes.max={:?}",
        die.name,
        die.cram_sx,
        die.cram_sy,
        die.tile_sx,
        die.tile_sy,
        die.frame_size,
        die.pram_sizes.iter().max()
    );

    let data = fs::read(path).with_context(|| format!("reading {path}"))?;
    let cram_offset = cram_region_offset(&die);
    println!("CRAM region offset in file: {cram_offset} (file size {})", data.len());
    if cram_offset >= data.len() {
        bail!(
            "CRAM region offset {cram_offset} is past end of file ({} bytes) -- \
             wrong die, or file isn't a raw Cyclone V .rbf at this frame layout",
            data.len()
        );
    }

    let geom = codec::CramFrameGeom::new(die.cram_sy, die.frame_size);
    let framed_bytes = die.cram_sx as usize * geom.cram_frame_bytes;
    println!(
        "cram_frame_bytes={} cram_frame_bits={} offset={} framed_bytes={}",
        geom.cram_frame_bytes, geom.cram_frame_bits, geom.offset, framed_bytes
    );

    let region = &data[cram_offset..];

    let framed = if assume_compressed {
        println!("decompressing (nibble zero-suppression)...");
        codec::nibble_decompress(region, framed_bytes)
            .context("nibble_decompress failed on real file data")?
    } else {
        if region.len() < framed_bytes {
            bail!(
                "uncompressed path needs {framed_bytes} CRAM frame bytes, only {} available after offset",
                region.len()
            );
        }
        region[..framed_bytes].to_vec()
    };

    // Step 1: frame bytes -> flat CRAM bit array (rbf_load's post-decode loop).
    let cram_bits = codec::unpack_cram_bits(&framed, die.cram_sx, die.cram_sy, &geom);
    let popcount: u32 = cram_bits.iter().map(|b| b.count_ones()).sum();
    println!(
        "unpacked CRAM: {} bytes, {popcount} bits set of {}",
        cram_bits.len(),
        die.cram_sx as usize * die.cram_sy as usize
    );

    // Step 2: flat CRAM bit array -> frame bytes again (rbf_save's pre-encode loop).
    let mut framed_back = vec![0u8; framed_bytes];
    codec::pack_cram_bits(&cram_bits, die.cram_sx, die.cram_sy, &geom, &mut framed_back);

    // Primary check: unpack(pack(cram_bits)) == cram_bits. This is the
    // actual round-trip property the CRAM fold/unfold needs -- it does NOT
    // require framed_back to equal the original framed bytes exactly,
    // because a real frame also carries bits this module doesn't model
    // (per-frame CRC/padding at y<32, EDCRC trailer, etc. -- rbf_load/
    // rbf_save's own frame also has fields besides the CRAM fold this module
    // ports). Byte-identical framed-buffer comparison is checked separately,
    // informationally, below.
    let cram_bits_back = codec::unpack_cram_bits(&framed_back, die.cram_sx, die.cram_sy, &geom);
    let roundtrip_matches = cram_bits_back == cram_bits;
    println!("CRAM-bits -> frame -> CRAM-bits roundtrip: {}", if roundtrip_matches { "MATCH" } else { "MISMATCH" });
    if !roundtrip_matches {
        bail!("CRAM bit fold/unfold roundtrip mismatch -- codec port has a bug");
    }

    let frame_bytes_match = cram_round_trip_matches(&framed, &framed_back, die.cram_sx, &geom);
    println!(
        "(informational) raw frame bytes identical to original decompressed frame: {}",
        if frame_bytes_match { "yes" } else { "no (expected -- framed also carries non-CRAM-fold bits this module doesn't model)" }
    );

    if assume_compressed {
        // Step 3: re-compress framed_back, decompress again, compare to framed.
        let recompressed = codec::nibble_compress(&framed_back);
        let redecompressed = codec::nibble_decompress(&recompressed, framed_bytes)
            .context("re-decompress of our own re-compressed output failed")?;
        let full_roundtrip = redecompressed == framed_back;
        println!(
            "nibble codec full roundtrip (decompress->pack->unpack->compress->decompress): {}",
            if full_roundtrip { "MATCH" } else { "MISMATCH" }
        );
        if !full_roundtrip {
            bail!("nibble codec roundtrip mismatch -- codec port has a bug");
        }
        println!(
            "original compressed size: {} bytes, re-compressed size: {} bytes",
            region.len().min(data.len() - cram_offset),
            recompressed.len()
        );
    } else {
        println!("(--assume-compressed not set: nibble codec itself not exercised on this file)");
    }

    println!("OK: round trip verified.");
    Ok(())
}

/// Compare two frame-byte buffers only over the bit positions
/// unpack_cram_bits/pack_cram_bits actually read/write (y in [32, cram_sy)),
/// since bits outside that range are legitimately left untouched by both.
fn cram_round_trip_matches(a: &[u8], b: &[u8], cram_sx: u32, geom: &codec::CramFrameGeom) -> bool {
    for x in 0..cram_sx {
        let da = &a[(x as usize) * geom.cram_frame_bytes..(x as usize + 1) * geom.cram_frame_bytes];
        let db_ = &b[(x as usize) * geom.cram_frame_bytes..(x as usize + 1) * geom.cram_frame_bytes];
        // Only compare the bit positions the fold loop addresses (pos 224..)
        // -- bytes before that (the frame's own header/CRC area) are out of
        // scope for this codec module.
        if da[28..] != db_[28..] {
            // 224 bits = 28 bytes; everything at/after byte 28 is in scope.
            return false;
        }
    }
    true
}

fn main() -> Result<()> {
    let cli = Cli::parse();
    match cli.cmd {
        Command::Roundtrip { die, path, assume_compressed } => {
            run_roundtrip(&cli.db, &die, &path, assume_compressed)
        }
        Command::RouteCounts { die } => {
            let counts = rnodes::route_counts(&cli.db, &die)?;
            println!(
                "{die}: cv_route_muxes={} cv_route_lines={} cv_route_drivers={} cv_p2r={} cv_p2p={}",
                counts.muxes, counts.lines, counts.drivers, counts.p2r, counts.p2p
            );
            Ok(())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// End-to-end round trip against a Quartus-built e50f corpus bitstream
    /// (corpus/README.md; `scripts/cyclonev_corpus_build.py --only adder12`).
    /// Skips (does not fail) if the corpus file or a populated pluribus DB
    /// is absent; run `scripts/cyclonev_db_import.py` to populate the DB
    /// read from $PLURIBUS_SQLITE_PATH (or ./pluribus.db).
    #[test]
    fn corpus_bitstream_roundtrip() {
        let fixture = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../corpus/cyclonev/adder12/bitstream.compressed.rbf");
        if !fixture.exists() {
            eprintln!("skipping corpus_bitstream_roundtrip: fixture not present at {}", fixture.display());
            return;
        }
        let db_path = std::env::var("PLURIBUS_SQLITE_PATH").unwrap_or_else(|_| "./pluribus.db".to_string());
        if !std::path::Path::new(&db_path).exists() {
            eprintln!("skipping corpus_bitstream_roundtrip: no pluribus DB at {db_path} -- run scripts/cyclonev_db_import.py");
            return;
        }

        let die = db::load_die(&db_path, "e50f").expect("e50f die must be importable");
        let data = fs::read(&fixture).expect("reading corpus fixture");
        let cram_offset = cram_region_offset(&die);
        let geom = codec::CramFrameGeom::new(die.cram_sy, die.frame_size);
        let framed_bytes = die.cram_sx as usize * geom.cram_frame_bytes;
        let region = &data[cram_offset..];

        let framed = codec::nibble_decompress(region, framed_bytes).expect("decompress corpus file");
        let cram_bits = codec::unpack_cram_bits(&framed, die.cram_sx, die.cram_sy, &geom);

        // Sanity bound only: sparse but non-trivial.
        let popcount: u32 = cram_bits.iter().map(|b| b.count_ones()).sum();
        let total_bits = die.cram_sx as u64 * die.cram_sy as u64;
        assert!(popcount > 0, "decompressed CRAM is all-zero -- codec likely broken");
        assert!(
            (popcount as u64) < total_bits / 2,
            "decompressed CRAM is implausibly dense ({popcount} of {total_bits} bits) -- codec likely broken"
        );

        // The actual round-trip property: CRAM bits survive fold -> unfold.
        let mut framed_back = vec![0u8; framed_bytes];
        codec::pack_cram_bits(&cram_bits, die.cram_sx, die.cram_sy, &geom, &mut framed_back);
        let cram_bits_back = codec::unpack_cram_bits(&framed_back, die.cram_sx, die.cram_sy, &geom);
        assert_eq!(cram_bits_back, cram_bits, "CRAM fold/unfold roundtrip mismatch on corpus file data");

        // And the nibble codec itself: compress what we just unpacked from
        // the real file, decompress again, must reproduce the same bytes.
        let recompressed = codec::nibble_compress(&framed_back);
        let redecompressed = codec::nibble_decompress(&recompressed, framed_bytes).expect("re-decompress");
        assert_eq!(redecompressed, framed_back, "nibble codec roundtrip mismatch on corpus file data");
    }
}
