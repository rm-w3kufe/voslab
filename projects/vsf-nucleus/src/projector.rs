// projector.rs — ITEM_13.2 — S4 linear projector (Beer-compliant predictive intelligence)
//
// Maintains a rolling buffer of TwinPoints (dual-channel readings per tick).
// Fits simple linear regression: stasis_cos ~ alpha + beta * tick.
// Computes Pearson correlation(stasis_cos, loadavg_1m) — cross-channel relationship.
// Projects stasis_cos PROJ_HORIZON_TICKS ahead.
//
// Design choices:
//   - No external crates: implements least-squares in ~30 lines of float arithmetic.
//   - Buffer of 24 ticks (~24 min at 60s cadence): enough history, bounded memory.
//   - Minimum 6 points before fitting (avoids noise on cold start).
//   - Emits a ProjectionRegime: Stable / Degrading / Recovering / Insufficient.

use std::collections::VecDeque;

pub const PROJ_MIN_POINTS: usize = 6;
pub const PROJ_BUFFER_N: usize = 24;
pub const PROJ_HORIZON_TICKS: u64 = 5;

// Slope thresholds for regime classification (per tick at 60s cadence)
const SLOPE_DEGRADING: f64 = -0.0001;
const SLOPE_RECOVERING: f64 = 0.0001;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ProjectionRegime {
    Stable,
    Degrading,
    Recovering,
    Insufficient,
}

impl ProjectionRegime {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Stable => "stable",
            Self::Degrading => "degrading",
            Self::Recovering => "recovering",
            Self::Insufficient => "insufficient_data",
        }
    }
}

#[derive(Debug, Clone)]
pub struct TwinPoint {
    pub tick: u64,
    pub stasis_cos: f64,
    pub h_t: f64,
    pub loadavg_1m: Option<f64>,
    pub cpu_temp_c: Option<f64>,
}

#[derive(Debug, Clone)]
pub struct Projection {
    pub horizon_ticks: u64,
    pub projected_stasis_cos: f64,
    pub trend_slope: f64,
    pub load_correlation: f64,  // Pearson(stasis_cos, loadavg_1m); NaN if no external data
    pub r_squared: f64,
    pub confidence: f64,        // 0..1 derived from R²
    pub n_points: usize,
    pub regime: ProjectionRegime,
}

impl Projection {
    pub fn insufficient(n: usize) -> Self {
        Projection {
            horizon_ticks: PROJ_HORIZON_TICKS,
            projected_stasis_cos: f64::NAN,
            trend_slope: 0.0,
            load_correlation: f64::NAN,
            r_squared: 0.0,
            confidence: 0.0,
            n_points: n,
            regime: ProjectionRegime::Insufficient,
        }
    }
}

pub struct Projector {
    buffer: VecDeque<TwinPoint>,
}

impl Projector {
    pub fn new() -> Self {
        Projector { buffer: VecDeque::with_capacity(PROJ_BUFFER_N + 1) }
    }

    pub fn push(&mut self, point: TwinPoint) {
        self.buffer.push_back(point);
        if self.buffer.len() > PROJ_BUFFER_N {
            self.buffer.pop_front();
        }
    }

    pub fn project(&self) -> Projection {
        let n = self.buffer.len();
        if n < PROJ_MIN_POINTS {
            return Projection::insufficient(n);
        }

        // ── simple OLS: stasis_cos ~ alpha + beta * tick ──────────────────
        let n_f = n as f64;
        let sum_x: f64 = self.buffer.iter().map(|p| p.tick as f64).sum();
        let sum_y: f64 = self.buffer.iter().map(|p| p.stasis_cos).sum();
        let sum_xx: f64 = self.buffer.iter().map(|p| (p.tick as f64).powi(2)).sum();
        let sum_xy: f64 = self.buffer.iter().map(|p| p.tick as f64 * p.stasis_cos).sum();

        let denom = n_f * sum_xx - sum_x * sum_x;
        let (alpha, beta) = if denom.abs() < f64::EPSILON {
            (sum_y / n_f, 0.0)
        } else {
            let b = (n_f * sum_xy - sum_x * sum_y) / denom;
            let a = (sum_y - b * sum_x) / n_f;
            (a, b)
        };

        // ── R² ────────────────────────────────────────────────────────────
        let mean_y = sum_y / n_f;
        let ss_tot: f64 = self.buffer.iter().map(|p| (p.stasis_cos - mean_y).powi(2)).sum();
        let ss_res: f64 = self.buffer.iter()
            .map(|p| (p.stasis_cos - (alpha + beta * p.tick as f64)).powi(2))
            .sum();
        let r_squared = if ss_tot < f64::EPSILON { 1.0 } else { (1.0 - ss_res / ss_tot).clamp(0.0, 1.0) };

        // ── projection ────────────────────────────────────────────────────
        let last_tick = self.buffer.back().map(|p| p.tick).unwrap_or(0) as f64;
        let projected_stasis_cos = (alpha + beta * (last_tick + PROJ_HORIZON_TICKS as f64)).clamp(0.0, 1.0);

        // ── Pearson(stasis_cos, loadavg_1m) — cross-channel ──────────────
        let load_pairs: Vec<(f64, f64)> = self.buffer.iter()
            .filter_map(|p| p.loadavg_1m.map(|l| (p.stasis_cos, l)))
            .collect();
        let load_correlation = pearson(&load_pairs);

        // ── regime ────────────────────────────────────────────────────────
        let regime = if beta < SLOPE_DEGRADING {
            ProjectionRegime::Degrading
        } else if beta > SLOPE_RECOVERING {
            ProjectionRegime::Recovering
        } else {
            ProjectionRegime::Stable
        };

        Projection {
            horizon_ticks: PROJ_HORIZON_TICKS,
            projected_stasis_cos,
            trend_slope: beta,
            load_correlation,
            r_squared,
            confidence: r_squared,
            n_points: n,
            regime,
        }
    }
}

// Pearson correlation coefficient for a slice of (x, y) pairs.
// Returns NaN when fewer than 2 pairs or zero variance.
fn pearson(pairs: &[(f64, f64)]) -> f64 {
    let n = pairs.len();
    if n < 2 {
        return f64::NAN;
    }
    let n_f = n as f64;
    let sum_x: f64 = pairs.iter().map(|(x, _)| x).sum();
    let sum_y: f64 = pairs.iter().map(|(_, y)| y).sum();
    let sum_xx: f64 = pairs.iter().map(|(x, _)| x.powi(2)).sum();
    let sum_yy: f64 = pairs.iter().map(|(_, y)| y.powi(2)).sum();
    let sum_xy: f64 = pairs.iter().map(|(x, y)| x * y).sum();
    let num = n_f * sum_xy - sum_x * sum_y;
    let den = ((n_f * sum_xx - sum_x * sum_x) * (n_f * sum_yy - sum_y * sum_y)).sqrt();
    if den < f64::EPSILON { f64::NAN } else { (num / den).clamp(-1.0, 1.0) }
}

// ── TESTS ─────────────────────────────────────────────────────────────────────
#[cfg(test)]
mod tests {
    use super::*;

    fn make_projector_with(data: &[(u64, f64, Option<f64>)]) -> Projector {
        let mut p = Projector::new();
        for &(tick, sc, load) in data {
            p.push(TwinPoint { tick, stasis_cos: sc, h_t: 1.9, loadavg_1m: load, cpu_temp_c: None });
        }
        p
    }

    #[test]
    fn insufficient_below_min_points() {
        let p = make_projector_with(&[(1, 0.99, None), (2, 0.99, None)]);
        let proj = p.project();
        assert_eq!(proj.regime, ProjectionRegime::Insufficient);
        assert_eq!(proj.n_points, 2);
    }

    #[test]
    fn stable_flat_trajectory() {
        // Constant stasis_cos → slope ≈ 0 → Stable
        let data: Vec<(u64, f64, Option<f64>)> = (1..=10).map(|t| (t, 0.999, None)).collect();
        let p = make_projector_with(&data);
        let proj = p.project();
        assert_eq!(proj.regime, ProjectionRegime::Stable);
        assert!(proj.trend_slope.abs() < 1e-9);
        assert!(proj.r_squared >= 0.0);
        // Projection should stay near 0.999
        assert!((proj.projected_stasis_cos - 0.999).abs() < 0.01);
    }

    #[test]
    fn degrading_trajectory() {
        // Steeply declining stasis_cos → Degrading
        let data: Vec<(u64, f64, Option<f64>)> = (1u64..=10)
            .map(|t| (t, 1.0 - t as f64 * 0.01, None))
            .collect();
        let p = make_projector_with(&data);
        let proj = p.project();
        assert_eq!(proj.regime, ProjectionRegime::Degrading);
        assert!(proj.trend_slope < 0.0);
        assert!(proj.r_squared > 0.99);
    }

    #[test]
    fn recovering_trajectory() {
        let data: Vec<(u64, f64, Option<f64>)> = (1u64..=10)
            .map(|t| (t, 0.90 + t as f64 * 0.005, None))
            .collect();
        let p = make_projector_with(&data);
        let proj = p.project();
        assert_eq!(proj.regime, ProjectionRegime::Recovering);
        assert!(proj.trend_slope > 0.0);
    }

    #[test]
    fn pearson_perfect_negative_correlation() {
        // stasis_cos and loadavg perfectly anticorrelated
        let data: Vec<(u64, f64, Option<f64>)> = (1u64..=10)
            .map(|t| (t, 1.0 - t as f64 * 0.01, Some(t as f64 * 0.5)))
            .collect();
        let p = make_projector_with(&data);
        let proj = p.project();
        // correlation should be close to -1
        assert!(proj.load_correlation < -0.95, "got {}", proj.load_correlation);
    }

    #[test]
    fn buffer_caps_at_proj_buffer_n() {
        let mut p = Projector::new();
        for i in 0..(PROJ_BUFFER_N + 10) as u64 {
            p.push(TwinPoint { tick: i, stasis_cos: 0.99, h_t: 1.9, loadavg_1m: None, cpu_temp_c: None });
        }
        assert_eq!(p.buffer.len(), PROJ_BUFFER_N);
    }

    #[test]
    fn projection_clamps_to_unit_interval() {
        // Extreme degrading slope should not produce negative stasis_cos
        let data: Vec<(u64, f64, Option<f64>)> = (1u64..=10)
            .map(|t| (t, (1.0 - t as f64 * 0.15).max(0.0), None))
            .collect();
        let p = make_projector_with(&data);
        let proj = p.project();
        assert!(proj.projected_stasis_cos >= 0.0);
        assert!(proj.projected_stasis_cos <= 1.0);
    }
}
