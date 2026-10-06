// vmem.rs — V_mem: vectorial memory for vOS kernels
// Spec: docs/vos_kernel_spec.vsm §6 boot_params.V_mem
//       docs/vos_memory_architecture.vsm
// Watermark: ⟦ vsf-nucleus | rmw3 | vsm-0.3 ⟧

use crate::state_vector::StateVector;

/// VMemEntry: one memory record — a StateVector with a decaying weight.
///
/// weight decays at rate λ_mem per tick: w(t) = w(t-1) * (1 - λ_mem)
/// Entries with weight < θ_min are pruned.
#[derive(Clone, Debug)]
pub struct VMemEntry {
    pub state:        StateVector,
    pub weight:       f64,   // ∈ [0, 1] — decays with time
    pub created_tick: u64,
    pub last_hit:     u64,   // last tick this entry was matched in query
    pub hit_count:    u64,
}

impl VMemEntry {
    fn new(state: StateVector, tick: u64) -> Self {
        VMemEntry {
            state,
            weight:       1.0,
            created_tick: tick,
            last_hit:     tick,
            hit_count:    0,
        }
    }

    /// Apply exponential decay: w *= (1 - λ)
    fn decay(&mut self, lambda: f64) {
        self.weight *= 1.0 - lambda;
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// VectorMemory
// ─────────────────────────────────────────────────────────────────────────────

/// V_mem — 128-dim cosine memory store per vos_kernel_spec.vsm §6
///
/// Parameters (from spec):
///   capacity:   10_000    max entries before oldest are evicted
///   λ_mem:      0.02      per-tick weight decay
///   θ_min:      0.01      prune threshold (weight < θ_min → remove)
///   θ_merge:    0.95      cosine similarity threshold for merging entries
///   θ_viable:   0.70      cosine for viable_full check (from StateVector)
pub struct VectorMemory {
    entries:    Vec<VMemEntry>,
    pub config: VMemConfig,
    tick:       u64,
    pub stats:  VMemStats,
}

#[derive(Clone, Debug)]
pub struct VMemConfig {
    pub capacity:  usize,
    pub lambda:    f64,   // λ_mem decay rate
    pub theta_min: f64,   // prune threshold
    pub theta_merge: f64, // merge threshold
}

impl Default for VMemConfig {
    fn default() -> Self {
        VMemConfig {
            capacity:    10_000,
            lambda:      0.02,
            theta_min:   0.01,
            theta_merge: 0.95,
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct VMemStats {
    pub total_inserted:  u64,
    pub total_merged:    u64,
    pub total_pruned:    u64,
    pub total_evicted:   u64,
    pub queries:         u64,
}

impl VectorMemory {
    pub fn new() -> Self {
        VectorMemory::with_config(VMemConfig::default())
    }

    pub fn with_config(config: VMemConfig) -> Self {
        VectorMemory {
            entries: Vec::with_capacity(config.capacity.min(1024)),
            config,
            tick:    0,
            stats:   VMemStats::default(),
        }
    }

    /// insert: add a new state vector at current tick.
    ///
    /// If an existing entry has cosine ≥ θ_merge, merge instead of inserting.
    /// If at capacity, evict the lowest-weight entry.
    pub fn insert(&mut self, state: StateVector) {
        self.stats.total_inserted += 1;

        // check for merge candidate (highest cosine ≥ θ_merge)
        let mut best_idx:  Option<usize> = None;
        let mut best_cos:  f64 = self.config.theta_merge - f64::EPSILON;

        for (i, entry) in self.entries.iter().enumerate() {
            let cos = state.cosine_similarity(&entry.state);
            if cos > best_cos {
                best_cos = cos;
                best_idx = Some(i);
            }
        }

        if let Some(idx) = best_idx {
            // merge: weighted average of dims, weight += new weight
            let existing_w = self.entries[idx].weight;
            let new_w      = 1.0;
            let total_w    = existing_w + new_w;
            for d in 0..128 {
                self.entries[idx].state.dims[d] =
                    (self.entries[idx].state.dims[d] * existing_w
                     + state.dims[d] * new_w) / total_w;
            }
            self.entries[idx].weight    = total_w.min(1.0);
            self.entries[idx].last_hit  = self.tick;
            self.entries[idx].hit_count += 1;
            self.stats.total_merged += 1;
            return;
        }

        // evict if at capacity
        if self.entries.len() >= self.config.capacity {
            // evict lowest weight
            let min_idx = self.entries.iter().enumerate()
                .min_by(|(_, a), (_, b)| a.weight.partial_cmp(&b.weight).unwrap())
                .map(|(i, _)| i)
                .unwrap();
            self.entries.swap_remove(min_idx);
            self.stats.total_evicted += 1;
        }

        self.entries.push(VMemEntry::new(state, self.tick));
    }

    /// query_nearest: return up to k entries sorted by cosine similarity (descending).
    /// Only returns entries with cosine ≥ threshold (default 0.0).
    pub fn query_nearest(&mut self, query: &StateVector, k: usize, threshold: f64)
        -> Vec<VMemQueryResult>
    {
        self.stats.queries += 1;
        let tick = self.tick;

        let mut results: Vec<VMemQueryResult> = self.entries.iter_mut()
            .enumerate()
            .map(|(i, entry)| {
                let cos = query.cosine_similarity(&entry.state);
                (i, cos, entry)
            })
            .filter(|(_, cos, _)| *cos >= threshold)
            .map(|(i, cos, entry)| {
                entry.last_hit  = tick;
                entry.hit_count += 1;
                VMemQueryResult {
                    index:   i,
                    cosine:  cos,
                    weight:  entry.weight,
                    created: entry.created_tick,
                    hits:    entry.hit_count,
                }
            })
            .collect();

        results.sort_by(|a, b| b.cosine.partial_cmp(&a.cosine).unwrap());
        results.truncate(k);
        results
    }

    /// decay: apply λ_mem decay to all entries for one tick
    pub fn tick_decay(&mut self) {
        self.tick += 1;
        let lambda = self.config.lambda;
        for entry in self.entries.iter_mut() {
            entry.decay(lambda);
        }
    }

    /// prune: remove entries with weight < θ_min
    pub fn prune(&mut self) -> usize {
        let before = self.entries.len();
        let theta  = self.config.theta_min;
        self.entries.retain(|e| e.weight >= theta);
        let pruned = before - self.entries.len();
        self.stats.total_pruned += pruned as u64;
        pruned
    }

    /// merge_similar: scan all pairs and merge entries with cosine ≥ θ_merge.
    ///
    /// O(n²) — call infrequently (e.g. every 100 ticks).
    /// Returns number of merges performed.
    pub fn merge_similar(&mut self) -> usize {
        let mut merges = 0;
        let mut i = 0;
        while i < self.entries.len() {
            let mut j = i + 1;
            while j < self.entries.len() {
                let cos = self.entries[i].state.cosine_similarity(&self.entries[j].state);
                if cos >= self.config.theta_merge {
                    // merge j into i
                    let wi = self.entries[i].weight;
                    let wj = self.entries[j].weight;
                    let wt = wi + wj;
                    for d in 0..128 {
                        self.entries[i].state.dims[d] =
                            (self.entries[i].state.dims[d] * wi
                             + self.entries[j].state.dims[d] * wj) / wt;
                    }
                    self.entries[i].weight    = wt.min(1.0);
                    self.entries[i].hit_count += self.entries[j].hit_count;
                    self.entries.swap_remove(j);
                    self.stats.total_merged += 1;
                    merges += 1;
                    // don't advance j — swap_remove moved last element to j
                } else {
                    j += 1;
                }
            }
            i += 1;
        }
        merges
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    pub fn current_tick(&self) -> u64 {
        self.tick
    }

    /// half_life: number of ticks until weight 1.0 → 0.5
    /// = ln(2) / λ_mem
    pub fn half_life_ticks(&self) -> f64 {
        std::f64::consts::LN_2 / self.config.lambda
    }
}

impl Default for VectorMemory {
    fn default() -> Self { Self::new() }
}

// ─────────────────────────────────────────────────────────────────────────────
// VMemQueryResult
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Clone, Debug)]
pub struct VMemQueryResult {
    pub index:   usize,
    pub cosine:  f64,
    pub weight:  f64,
    pub created: u64,
    pub hits:    u64,
}

// ─────────────────────────────────────────────────────────────────────────────
// Tests
// ─────────────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn sv_with(dim: usize, val: f64) -> StateVector {
        let mut sv = StateVector::new();
        sv.dims[dim] = val;
        sv
    }

    fn sv_uniform(val: f64) -> StateVector {
        let mut sv = StateVector::new();
        for d in 0..128 { sv.dims[d] = val; }
        sv
    }

    #[test]
    fn insert_and_query() {
        let mut mem = VectorMemory::new();
        let a = sv_with(0, 1.0);
        let b = sv_with(1, 1.0);  // orthogonal to a

        mem.insert(a.clone());
        mem.insert(b.clone());
        assert_eq!(mem.len(), 2);

        // query closest to a
        let results = mem.query_nearest(&a, 5, 0.0);
        assert!(!results.is_empty());
        assert!((results[0].cosine - 1.0).abs() < 1e-9, "nearest to a should be a (cos=1.0)");
    }

    #[test]
    fn merge_on_insert_when_similar() {
        let mut cfg = VMemConfig::default();
        cfg.theta_merge = 0.95;
        let mut mem = VectorMemory::with_config(cfg);

        // two vectors that are nearly identical — cosine will be 1.0
        let a = sv_uniform(1.0);
        let b = sv_uniform(1.0);

        mem.insert(a);
        mem.insert(b);

        // should merge, not insert twice
        assert_eq!(mem.len(), 1, "identical vectors should merge to 1 entry");
        assert_eq!(mem.stats.total_merged, 1);
    }

    #[test]
    fn no_merge_when_orthogonal() {
        let mut mem = VectorMemory::new();
        mem.insert(sv_with(0, 1.0));
        mem.insert(sv_with(1, 1.0));
        assert_eq!(mem.len(), 2, "orthogonal vectors should not merge");
        assert_eq!(mem.stats.total_merged, 0);
    }

    #[test]
    fn decay_reduces_weight() {
        let mut mem = VectorMemory::new();
        mem.insert(sv_uniform(1.0));

        let w_before = mem.entries[0].weight;
        mem.tick_decay();
        let w_after = mem.entries[0].weight;

        assert!(w_after < w_before, "decay should reduce weight");
        let expected = w_before * (1.0 - mem.config.lambda);
        assert!((w_after - expected).abs() < 1e-12);
    }

    #[test]
    fn prune_removes_low_weight() {
        let mut cfg = VMemConfig::default();
        cfg.lambda    = 0.5;   // aggressive decay for test
        cfg.theta_min = 0.10;
        let mut mem = VectorMemory::with_config(cfg);

        mem.insert(sv_uniform(1.0));

        // decay enough times to drop weight below θ_min
        // w after n ticks = (1-0.5)^n. Need w < 0.10 → n ≥ 4 (0.5^4=0.0625)
        for _ in 0..4 { mem.tick_decay(); }

        let pruned = mem.prune();
        assert_eq!(pruned, 1, "low-weight entry should be pruned");
        assert_eq!(mem.len(), 0);
    }

    #[test]
    fn merge_similar_scans_all_pairs() {
        let mut cfg = VMemConfig::default();
        cfg.theta_merge = 0.95;
        let mut mem = VectorMemory::with_config(cfg);

        // insert two identical + one orthogonal, bypassing insert-merge
        // by manipulating entries directly
        mem.entries.push(VMemEntry::new(sv_uniform(1.0), 0));
        mem.entries.push(VMemEntry::new(sv_uniform(1.0), 0));
        mem.entries.push(VMemEntry::new(sv_with(0, 1.0), 0));
        assert_eq!(mem.len(), 3);

        let merges = mem.merge_similar();
        assert_eq!(merges, 1, "one pair should merge");
        assert_eq!(mem.len(), 2, "3 entries - 1 merge = 2 entries");
    }

    #[test]
    fn evict_lowest_weight_at_capacity() {
        let mut cfg = VMemConfig::default();
        cfg.capacity = 3;
        let mut mem = VectorMemory::with_config(cfg);

        // fill to capacity with orthogonal vectors
        for i in 0..3 {
            mem.insert(sv_with(i, 1.0));
        }
        assert_eq!(mem.len(), 3);

        // manually lower weight of entry 0
        mem.entries[0].weight = 0.001;

        // insert one more — should evict entry 0
        mem.insert(sv_with(10, 1.0));
        assert_eq!(mem.len(), 3, "capacity maintained after eviction");
        assert_eq!(mem.stats.total_evicted, 1);
    }

    #[test]
    fn half_life_formula() {
        let mem = VectorMemory::new();  // λ = 0.02
        let hl = mem.half_life_ticks();
        // ln(2) / 0.02 ≈ 34.66 ticks
        assert!((hl - 34.66).abs() < 0.1, "half_life should be ~34.66 ticks, got {}", hl);
    }

    #[test]
    fn query_threshold_filters() {
        let mut mem = VectorMemory::new();
        mem.insert(sv_with(0, 1.0));   // unit vector at dim 0
        mem.insert(sv_with(1, 1.0));   // orthogonal (cos=0.0 with query)

        let query   = sv_with(0, 1.0);
        // only return results with cosine ≥ 0.5 — should get 1 result
        let results = mem.query_nearest(&query, 10, 0.5);
        assert_eq!(results.len(), 1, "only one entry passes threshold 0.5");
        assert!((results[0].cosine - 1.0).abs() < 1e-9);
    }
}
