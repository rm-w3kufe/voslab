// vr_complex.rs — F5.x.5 — Vietoris-Rips complex + GF(2) Betti numbers (β₀, β₁)
//
// Implements: docs/theory/dynamics_choice.vsm §T3 (Def_VRComplex, Hypothesis_ViabilityTopology)
//             calibrated by EXP-TDA-01 (docs/experiments/EXP-TDA-01/prereqs_standup.vsm + results).
//
//   Hypothesis_ViabilityTopology: β₀ = 1 ∧ β₁ = 0 ∧ β₂ = 0  ⇔  single attractor (viable).
//
// EXP-TDA-01 calibration (2026-06-01, 3043-pt rich trajectory, 3 regimes):
//   - β₀ = 1 is the ROBUST signal (raw-cosine H0 max-persistence 0.25 vs H1 noise ≤0.003 → ~80×
//     separation ⇒ wide stable ε-plateau, H_TDA1 confirmed).
//   - raw ℝ¹²⁸ cosine does NOT need projection here (H_TDA2 partially refuted).
//   - H1 "loops" all had persistence ≤ 0.028 < absolute noise floor 0.05 ⇒ β₁ = 0 (no real hole).
//   - cosine components merge into 1 by ε ≈ 0.25 ⇒ a runtime ε in the plateau (~0.30) gives β₀ = 1.
//
// This computes EXACT Z₂ homology of the VR 2-truncated complex at a FIXED ε (maxdim = 1, matching
// the calibration): β₀ = V − rank ∂₁,  β₁ = (E − rank ∂₁) − rank ∂₂. For runtime use feed a bounded
// (windowed/subsampled) trajectory — VR is super-linear in point count. β₂ deferred (needs ∂₃).
//
// Watermark: ⟦ vsf-nucleus | rmw3+claude-opus-4.8 | vsm-1.0 ⟧

use crate::state_vector::StateVector;

/// Calibrated runtime ε for cosine distance (EXP-TDA-01): within the β₀=1 plateau.
pub const VR_EPSILON_COSINE: f64 = crate::calibration::VR_EPSILON_COSINE;  // single source (EXP-TDA-01)

/// Cosine distance d(a,b) = 1 − cos(a,b) ∈ [0, 2]. Zero vectors → distance 1.0 (orthogonal-ish).
pub fn cosine_distance(a: &StateVector, b: &StateVector) -> f64 {
    let mut dot = 0.0;
    let mut na = 0.0;
    let mut nb = 0.0;
    for i in 0..128 {
        dot += a.dims[i] * b.dims[i];
        na += a.dims[i] * a.dims[i];
        nb += b.dims[i] * b.dims[i];
    }
    if na <= 0.0 || nb <= 0.0 {
        return 1.0;
    }
    (1.0 - dot / (na.sqrt() * nb.sqrt())).clamp(0.0, 2.0)
}

/// Betti numbers (truncated at dim 1).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Betti {
    pub b0: usize,
    pub b1: usize,
}

impl Betti {
    /// Hypothesis_ViabilityTopology (maxdim=1 form): single connected attractor, no hole.
    pub fn viability_signal(&self) -> bool {
        self.b0 == 1 && self.b1 == 0
    }
}

/// Vietoris-Rips complex (2-truncated) at scale ε over a finite point set.
#[derive(Debug, Clone)]
pub struct VrComplex {
    pub n_vertices: usize,
    pub edges: Vec<(usize, usize)>,       // i<j with d(i,j) ≤ ε
    pub triangles: Vec<(usize, usize, usize)>, // all pairwise ≤ ε
}

impl VrComplex {
    /// Build from a symmetric distance matrix (dist[i][j]); ε is the VR scale.
    pub fn from_distance_matrix(dist: &[Vec<f64>], epsilon: f64) -> Self {
        let n = dist.len();
        let mut edges = Vec::new();
        for i in 0..n {
            for j in (i + 1)..n {
                if dist[i][j] <= epsilon {
                    edges.push((i, j));
                }
            }
        }
        // edge lookup for triangle membership
        let connected = |a: usize, b: usize| -> bool {
            let (x, y) = if a < b { (a, b) } else { (b, a) };
            dist[x][y] <= epsilon
        };
        let mut triangles = Vec::new();
        for i in 0..n {
            for j in (i + 1)..n {
                if !connected(i, j) {
                    continue;
                }
                for k in (j + 1)..n {
                    if connected(i, k) && connected(j, k) {
                        triangles.push((i, j, k));
                    }
                }
            }
        }
        VrComplex { n_vertices: n, edges, triangles }
    }

    /// Build from ℝ¹²⁸ points with cosine distance.
    pub fn from_points_cosine(points: &[StateVector], epsilon: f64) -> Self {
        let n = points.len();
        let mut dist = vec![vec![0.0f64; n]; n];
        for i in 0..n {
            for j in (i + 1)..n {
                let d = cosine_distance(&points[i], &points[j]);
                dist[i][j] = d;
                dist[j][i] = d;
            }
        }
        Self::from_distance_matrix(&dist, epsilon)
    }

    /// Exact Z₂ Betti numbers (β₀, β₁) of the 2-truncated complex.
    ///   β₀ = V − rank ∂₁ ;  β₁ = (E − rank ∂₁) − rank ∂₂.
    pub fn betti(&self) -> Betti {
        // ∂₁ : edges → vertices. Row per edge with its two vertex bits.
        let v_words = self.n_vertices.div_ceil(64);
        let d1: Vec<Vec<u64>> = self
            .edges
            .iter()
            .map(|&(i, j)| {
                let mut row = vec![0u64; v_words];
                row[i / 64] |= 1 << (i % 64);
                row[j / 64] |= 1 << (j % 64);
                row
            })
            .collect();
        let rank1 = gf2_rank(d1);

        // ∂₂ : triangles → edges. Need an edge index map.
        let mut edge_index = std::collections::HashMap::new();
        for (idx, &(i, j)) in self.edges.iter().enumerate() {
            edge_index.insert((i, j), idx);
        }
        let e_words = self.edges.len().div_ceil(64).max(1);
        let d2: Vec<Vec<u64>> = self
            .triangles
            .iter()
            .map(|&(i, j, k)| {
                let mut row = vec![0u64; e_words];
                for &(a, b) in &[(i, j), (i, k), (j, k)] {
                    if let Some(&ei) = edge_index.get(&(a, b)) {
                        row[ei / 64] |= 1 << (ei % 64);
                    }
                }
                row
            })
            .collect();
        let rank2 = gf2_rank(d2);

        let v = self.n_vertices;
        let e = self.edges.len();
        let b0 = v.saturating_sub(rank1);
        let b1 = (e.saturating_sub(rank1)).saturating_sub(rank2);
        Betti { b0, b1 }
    }
}

/// Rank of a GF(2) matrix given as bitset rows (each row a Vec<u64>). Gaussian elimination.
fn gf2_rank(mut rows: Vec<Vec<u64>>) -> usize {
    if rows.is_empty() {
        return 0;
    }
    let words = rows[0].len();
    let mut rank = 0;
    let mut pivot_row = 0;
    for col in 0..(words * 64) {
        let w = col / 64;
        let bit = 1u64 << (col % 64);
        // find a row at/after pivot_row with this column set
        let mut sel = None;
        for r in pivot_row..rows.len() {
            if rows[r][w] & bit != 0 {
                sel = Some(r);
                break;
            }
        }
        let Some(sel) = sel else { continue };
        rows.swap(pivot_row, sel);
        // eliminate this column from all other rows
        for r in 0..rows.len() {
            if r != pivot_row && rows[r][w] & bit != 0 {
                for k in 0..words {
                    rows[r][k] ^= rows[pivot_row][k];
                }
            }
        }
        pivot_row += 1;
        rank += 1;
        if pivot_row == rows.len() {
            break;
        }
    }
    rank
}

// ──────────────────────────────────────────────────────────────────────────────
// TESTS
// ──────────────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod tests {
    use super::*;

    // symmetric distance matrix helper
    fn dm(n: usize, pairs: &[(usize, usize, f64)]) -> Vec<Vec<f64>> {
        let mut d = vec![vec![10.0f64; n]; n]; // far by default
        for i in 0..n {
            d[i][i] = 0.0;
        }
        for &(i, j, v) in pairs {
            d[i][j] = v;
            d[j][i] = v;
        }
        d
    }

    #[test]
    fn single_cluster_is_b0_1_b1_0() {
        // 3 mutually-close points → a filled triangle → β₀=1, β₁=0.
        let d = dm(3, &[(0, 1, 0.1), (0, 2, 0.1), (1, 2, 0.1)]);
        let b = VrComplex::from_distance_matrix(&d, 0.3).betti();
        assert_eq!(b, Betti { b0: 1, b1: 0 });
        assert!(b.viability_signal());
    }

    #[test]
    fn two_far_clusters_is_b0_2() {
        // {0,1} close, {2,3} close, clusters far apart → β₀=2.
        let d = dm(4, &[(0, 1, 0.1), (2, 3, 0.1)]);
        let b = VrComplex::from_distance_matrix(&d, 0.3).betti();
        assert_eq!(b.b0, 2);
        assert!(!b.viability_signal());
    }

    #[test]
    fn square_loop_is_b1_1() {
        // 4 points, edges = sides (≤ε), diagonals > ε ⇒ no triangles ⇒ a hole, β₁=1.
        // sides: 0-1,1-2,2-3,3-0 = 0.2 ; diagonals 0-2,1-3 = 0.5 (> ε=0.3)
        let d = dm(4, &[
            (0, 1, 0.2), (1, 2, 0.2), (2, 3, 0.2), (3, 0, 0.2),
            (0, 2, 0.5), (1, 3, 0.5),
        ]);
        let c = VrComplex::from_distance_matrix(&d, 0.3);
        assert_eq!(c.edges.len(), 4);
        assert_eq!(c.triangles.len(), 0);
        let b = c.betti();
        assert_eq!(b, Betti { b0: 1, b1: 1 });
        assert!(!b.viability_signal()); // a hole ⇒ not the single-attractor signature
    }

    #[test]
    fn square_loop_fills_at_larger_epsilon() {
        // raise ε to include diagonals → triangles fill the loop → β₁=0.
        let d = dm(4, &[
            (0, 1, 0.2), (1, 2, 0.2), (2, 3, 0.2), (3, 0, 0.2),
            (0, 2, 0.5), (1, 3, 0.5),
        ]);
        let b = VrComplex::from_distance_matrix(&d, 0.6).betti();
        assert_eq!(b.b0, 1);
        assert_eq!(b.b1, 0);
        assert!(b.viability_signal());
    }

    #[test]
    fn cosine_distance_basics() {
        let mut a = StateVector { dims: [0.0; 128] };
        let mut b = StateVector { dims: [0.0; 128] };
        a.dims[0] = 1.0;
        b.dims[0] = 1.0;
        assert!(cosine_distance(&a, &b) < 1e-9); // identical direction → 0
        b.dims[0] = 0.0;
        b.dims[1] = 1.0;
        assert!((cosine_distance(&a, &b) - 1.0).abs() < 1e-9); // orthogonal → 1
    }

    #[test]
    fn from_points_cosine_single_attractor() {
        // tight cluster of near-identical vectors → β₀=1, β₁=0 at the calibrated ε.
        let mut pts = Vec::new();
        for k in 0..6 {
            let mut s = StateVector { dims: [0.0; 128] };
            s.dims[0] = 1.0;
            s.dims[1] = 0.01 * k as f64; // tiny spread
            pts.push(s);
        }
        let b = VrComplex::from_points_cosine(&pts, VR_EPSILON_COSINE).betti();
        assert!(b.viability_signal(), "expected single-attractor signature, got {:?}", b);
    }

    #[test]
    fn dense_cluster_32_is_fast_and_point_sink() {
        // Mirrors the W3 live monitor worst case: 32 near-identical vectors → COMPLETE complex
        // (all pairwise within ε). Must compute fast + give the point-sink signature β₀=1, β₁=0.
        let mut pts = Vec::new();
        for k in 0..32 {
            let mut s = StateVector { dims: [0.0; 128] };
            s.dims[0] = 1.0;
            s.dims[1] = 0.001 * k as f64; // tiny spread — all within VR_EPSILON_COSINE
            pts.push(s);
        }
        let b = VrComplex::from_points_cosine(&pts, VR_EPSILON_COSINE).betti();
        assert_eq!(b.b0, 1, "complete complex should be one component");
        assert_eq!(b.b1, 0, "2-skeleton of a simplex is simply connected");
        assert!(b.viability_signal());
    }

    #[test]
    fn gf2_rank_identity_and_dep() {
        // rows e0, e1, e0^e1 → rank 2 (third is dependent).
        let rows = vec![vec![0b001u64], vec![0b010u64], vec![0b011u64]];
        assert_eq!(gf2_rank(rows), 2);
    }
}
