//! Query pluribus's SQLite device-db for Cyclone V die geometry.
//!
//! Schema owned by pluribus's schema.py (cv_dies / cv_pram_strips tables).
//! This module only reads -- it never creates or migrates the schema; that
//! stays in schema.py per pluribus's own "schema.py owns all DDL" rule.

use anyhow::{Context, Result};
use rusqlite::Connection;

/// Mirrors Mistral's `die_info` struct (cyclonev.h) for the fields the
/// compression codec (cv-files.cc rbf_load/rbf_save) needs.
///
/// postamble_1/postamble_2/noedcrc_zones are not yet read by this crate's
/// codec path (CRC/postamble framing is out of scope this session -- see
/// docs/bluebird.md) but are pulled from the DB now so callers
/// outside this crate (or a future session) don't need a second DieInfo type.
#[derive(Debug, Clone)]
#[allow(dead_code)]
pub struct DieInfo {
    pub name: String,
    pub cram_sx: u32,
    pub cram_sy: u32,
    pub tile_sx: u8,
    pub tile_sy: u8,
    pub frame_size: u16,
    pub postamble_1: u16,
    pub postamble_2: u16,
    pub pram_sizes: Vec<u16>,
    pub noedcrc_zones: Vec<u32>,
}

/// Open the pluribus SQLite DB at `path` and load one die's geometry by name.
pub fn load_die(db_path: &str, die_name: &str) -> Result<DieInfo> {
    let conn = Connection::open(db_path)
        .with_context(|| format!("opening pluribus SQLite DB at {db_path}"))?;

    let mut stmt = conn.prepare(
        "SELECT name, cram_sx, cram_sy, tile_sx, tile_sy, frame_size, \
                postamble_1, postamble_2, pram_sizes, noedcrc_zones \
         FROM cv_dies WHERE name = ?1",
    )?;

    let row = stmt
        .query_row([die_name], |row| {
            let pram_sizes_json: String = row.get(8)?;
            let noedcrc_json: String = row.get(9)?;
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, i64>(1)? as u32,
                row.get::<_, i64>(2)? as u32,
                row.get::<_, i64>(3)? as u8,
                row.get::<_, i64>(4)? as u8,
                row.get::<_, i64>(5)? as u16,
                row.get::<_, i64>(6)? as u16,
                row.get::<_, i64>(7)? as u16,
                pram_sizes_json,
                noedcrc_json,
            ))
        })
        .with_context(|| format!("die {die_name:?} not found in cv_dies -- run scripts/cyclonev_db_import.py first"))?;

    let pram_sizes: Vec<u16> = serde_json_lite_parse_u16(&row.8)?;
    let noedcrc_zones: Vec<u32> = serde_json_lite_parse_u16(&row.9)?.into_iter().map(u32::from).collect();

    Ok(DieInfo {
        name: row.0,
        cram_sx: row.1,
        cram_sy: row.2,
        tile_sx: row.3,
        tile_sy: row.4,
        frame_size: row.5,
        postamble_1: row.6,
        postamble_2: row.7,
        pram_sizes,
        noedcrc_zones,
    })
}

/// Minimal JSON-array-of-ints parser so this crate doesn't need a full JSON
/// dependency for the handful of integer-array columns schema.py stores as
/// JSON (cross-dialect portability choice documented in schema.py's header).
fn serde_json_lite_parse_u16(s: &str) -> Result<Vec<u16>> {
    let s = s.trim();
    let inner = s
        .strip_prefix('[')
        .and_then(|s| s.strip_suffix(']'))
        .with_context(|| format!("expected JSON array, got {s:?}"))?;
    if inner.trim().is_empty() {
        return Ok(Vec::new());
    }
    inner
        .split(',')
        .map(|tok| {
            tok.trim()
                .parse::<u16>()
                .with_context(|| format!("non-integer JSON array element {tok:?}"))
        })
        .collect()
}
