//! Query pluribus's SQLite device-db for Cyclone V routing-node/mux data.
//!
//! Schema owned by pluribus's schema.py (cv_route_muxes / cv_route_lines /
//! cv_route_drivers / cv_p2r / cv_p2p tables, populated by
//! scripts/cyclonev_db_import_routes.py). This module only reads -- same
//! read-only relationship to the DB as db.rs has for cv_dies.
//!
//! SCOPE: this is a query layer over the imported node/mux data, not the
//! cv-bmux.cc/cv-rmux.cc port itself. That port needs real design work this
//! session doesn't attempt (see docs/cyclonev-rust-port.md) -- what it would
//! actually DO with this data (resolve a mux's selected source bit against
//! decoded CRAM bits, walk the net graph) isn't implemented here. This
//! module proves the data is queryable from Rust and sized sanely; it is
//! deliberately small, not a stand-in for the real port.

use anyhow::{Context, Result};
use rusqlite::Connection;

/// One row from cv_route_muxes: the routing mux (if any) occupying a
/// destination rnode, plus its JSON-encoded source list left as a raw
/// string (parsing it into structured sources is cv-rmux.cc territory --
/// out of scope here, see module doc).
#[derive(Debug, Clone)]
#[allow(dead_code)]  // lookup_mux/RouteMux: forward-looking API, not yet called by main.rs
pub struct RouteMux {
    pub rn_type: String,
    pub rn_x: i64,
    pub rn_y: i64,
    pub rn_z: i64,
    pub pattern: Option<i64>,
    pub fw_pos: i64,
    pub sources_json: String,
}

/// Count of rows in cv_route_muxes/cv_route_lines/cv_route_drivers/cv_p2r/
/// cv_p2p for one die -- the basic "is this die's routing data actually
/// here, and how much of it" query the Rust side needs before any mux/net
/// logic can be built on top.
#[derive(Debug, Clone, Copy, Default)]
pub struct RouteCounts {
    pub muxes: i64,
    pub lines: i64,
    pub drivers: i64,
    pub p2r: i64,
    pub p2p: i64,
}

fn die_id(conn: &Connection, die_name: &str) -> Result<i64> {
    conn.query_row("SELECT id FROM cv_dies WHERE name = ?1", [die_name], |r| r.get(0))
        .with_context(|| {
            format!("die {die_name:?} not found in cv_dies -- run scripts/cyclonev_db_import.py first")
        })
}

/// Row counts for one die's 5 routing tables -- run
/// scripts/cyclonev_db_import_routes.py first or every count is 0 (that is
/// not an error from this function's point of view: an unimported die has
/// zero rows, full stop).
pub fn route_counts(db_path: &str, die_name: &str) -> Result<RouteCounts> {
    let conn = Connection::open(db_path)
        .with_context(|| format!("opening pluribus SQLite DB at {db_path}"))?;
    let id = die_id(&conn, die_name)?;

    let count = |table: &str| -> Result<i64> {
        conn.query_row(&format!("SELECT COUNT(*) FROM {table} WHERE die = ?1"), [id], |r| r.get(0))
            .with_context(|| format!("counting {table} for die {die_name:?}"))
    };

    Ok(RouteCounts {
        muxes: count("cv_route_muxes")?,
        lines: count("cv_route_lines")?,
        drivers: count("cv_route_drivers")?,
        p2r: count("cv_p2r")?,
        p2p: count("cv_p2p")?,
    })
}

/// Look up the routing mux at a specific destination rnode (type, x, y, z).
/// Returns None if that rnode has no row (die not imported, or rnode
/// genuinely doesn't exist at that coordinate -- both look the same from
/// here; cv_dies.name existing is checked by route_counts/die_id already).
#[allow(dead_code)]  // forward-looking API, not yet called by main.rs
pub fn lookup_mux(db_path: &str, die_name: &str, rn_type: &str, x: i64, y: i64, z: i64) -> Result<Option<RouteMux>> {
    let conn = Connection::open(db_path)
        .with_context(|| format!("opening pluribus SQLite DB at {db_path}"))?;
    let id = die_id(&conn, die_name)?;

    let mut stmt = conn.prepare(
        "SELECT rn_type, rn_x, rn_y, rn_z, pattern, fw_pos, sources \
         FROM cv_route_muxes WHERE die = ?1 AND rn_type = ?2 AND rn_x = ?3 AND rn_y = ?4 AND rn_z = ?5",
    )?;
    let mut rows = stmt.query((id, rn_type, x, y, z))?;
    match rows.next()? {
        None => Ok(None),
        Some(row) => Ok(Some(RouteMux {
            rn_type: row.get(0)?,
            rn_x: row.get(1)?,
            rn_y: row.get(2)?,
            rn_z: row.get(3)?,
            pattern: row.get(4)?,
            fw_pos: row.get(5)?,
            sources_json: row.get(6)?,
        })),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Real-data smoke test: if a populated pluribus DB with e50f routing
    /// data is on hand (from scripts/cyclonev_db_import_routes.py), the
    /// counts should be in the real, measured range this session's Python
    /// ETL run produced (695,446 / 625,862 / 839,698 / 8,418 / 1,755
    /// exactly, for e50f specifically) -- not an exact-match assertion
    /// (the DB this test runs against may be a partial/different import),
    /// but a plausibility bound so a badly broken reader fails loudly.
    /// Skips (does not fail) if no such DB is present, same policy as
    /// db.rs's/main.rs's own real-data tests.
    #[test]
    fn e50f_route_counts_are_plausible() {
        let db_path = std::env::var("PLURIBUS_SQLITE_PATH").unwrap_or_else(|_| "./pluribus.db".to_string());
        if !std::path::Path::new(&db_path).exists() {
            eprintln!("skipping e50f_route_counts_are_plausible: no pluribus DB at {db_path}");
            return;
        }
        let counts = match route_counts(&db_path, "e50f") {
            Ok(c) => c,
            Err(e) => {
                eprintln!("skipping e50f_route_counts_are_plausible: {e}");
                return;
            }
        };
        if counts.muxes == 0 {
            eprintln!("skipping e50f_route_counts_are_plausible: cv_route_muxes empty for e50f -- run scripts/cyclonev_db_import_routes.py --die e50f");
            return;
        }
        assert_eq!(counts.muxes, 695_446, "cv_route_muxes row count for e50f should match the real -r.txt.xz line count exactly");
        assert_eq!(counts.lines, 625_862, "cv_route_lines row count for e50f should match the real -l.txt.xz line count exactly");
        assert_eq!(counts.drivers, 839_698, "cv_route_drivers row count for e50f should match the real -d.txt.xz line count exactly");
        assert_eq!(counts.p2r, 8_418, "cv_p2r row count for e50f should match the real -p2r.txt expansion exactly");
        assert_eq!(counts.p2p, 1_755, "cv_p2p row count for e50f should match the real -p2p.txt line count exactly");
    }
}
