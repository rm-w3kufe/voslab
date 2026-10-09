// feeders.rs — TELEMETRY-PORTS D1 (P1) — FeederSource + dispatcher de puertos.
//
// Design (ratificado S5 2026-10-08, R17 aplicacion habilitada):
//   docs/plans/telemetry_ports_proposal.vsm — bloques P2-FIRST-PORTS (trait
//   FeederSource{StateDb, Fallback, Synthetic}, kill-switch q2, fallback q3,
//   provenance P/X/S/R) + design("ARCHITECTURE") (dispatcher estable en el
//   tick loop: ingest -> feed -> step -> emit; core inmutable ante puerto
//   nuevo; status:paused = apagar un puerto es estado de registro).
//
// La fórmula A_breath canon (vos_core_theory.vsm:175-183, cert 2026-08-07)
// vive UNA vez aquí — los ~11 sitios que hoy la reimplementan inline (clase S)
// leen del dispatcher. Canon:
//   pressure = 0.4·queue_up + 0.3·cpu + 0.3·(1 − absorption)
// solo los tres términos divergían del kernel; al rewire se paga la deuda
// KERNEL-ABREATH-ALIGN (SPEC_KERNEL_DEVIATIONS drift 1→0).
//
// Provenance (auditoría P/X/S/R en runtime — proposal P2-FIRST-PORTS.audit):
//   Measured  = R — señal real con verificación (PSI cross-read /proc,
//               backlog doble entrada sqlite)
//   Param     = P/X — parámetro de spec o knob de experimento (source lo
//               declara; el fallback queue=0/abs=1.0 cae aquí, nunca finge R)
//   Scaffold  = S — andamiaje que FINGE señal (debe cablearse o etiquetarse;
//               el detector de clase S es que ningún Sample Scaffold quede
//               sin declarar en el provenance_manifest)
//   Synthetic = sintético DECLARADO (state_coupled / osc — q3)
// "cifra measured sin verificación = falla del gate" → gate port-verified (P2).
//
// Watermark: ⟦ vsf-nucleus | rmw3 | vsm-1.0 ⟧

use std::path::{Path, PathBuf};

/// Divisor de normalización de queue_up — idéntico a state_vector.rs:154
/// (dims[QUEUE_PHI_UP] = queue/1000 .min(1.0)); una sola fuente de verdad.
pub const QUEUE_NORM_DIVISOR: f64 = 1000.0;

/// StateDb por defecto (n02 host — ledger_A). LXC sin state.db → error del
/// read → fallback declarado (q3), jamás provenance=measured.
pub const DEFAULT_STATE_DB: &str = "/var/lib/vsf-state/state.db";

/// Env kill-switch (q2: wire + kill-switch, default ON). "paused" (o cualquier
/// valor ≠ "on") corta el feed: los sitios reciben fallback declarado.
/// El descriptor de registro (state/telemetry_ports.json) llega en P2; este
/// env es el corte operativo de P1, mismo significado que status:paused.
pub const ENV_FEEDERS: &str = "VSF_FEEDERS";

// ─── Provenance + Sample ──────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Provenance {
    Measured,
    Param,
    Scaffold,
    Synthetic,
}

#[derive(Debug, Clone, Copy)]
pub struct Sample {
    pub value: f64,
    pub provenance: Provenance,
    pub source: &'static str,
}

impl Sample {
    pub fn new(value: f64, provenance: Provenance, source: &'static str) -> Self {
        Sample { value, provenance, source }
    }
    /// R — señal real con verificación.
    pub fn measured(value: f64, source: &'static str) -> Self {
        Sample::new(value, Provenance::Measured, source)
    }
    /// P/X — parámetro/knob declarado.
    pub fn param(value: f64, source: &'static str) -> Self {
        Sample::new(value, Provenance::Param, source)
    }
    /// Sintético declarado (state_coupled / osc).
    pub fn synthetic(value: f64, source: &'static str) -> Self {
        Sample::new(value, Provenance::Synthetic, source)
    }
}

// ─── FeederValues — el contrato que los sitios leen ───────────────────────────

#[derive(Debug, Clone, Copy)]
pub struct FeederValues {
    pub queue_up: Sample,
    pub absorption: Sample,
    pub cpu: Sample,
}

impl FeederValues {
    /// CANON A_breath (vos_core_theory.vsm): 0.4·queue + 0.3·cpu + 0.3·(1−abs).
    /// Términos normalizados [0,1]; determinista (R10): mismos samples → mismo
    /// resultado, sin aleatoriedad.
    pub fn pressure(&self) -> f64 {
        0.4 * self.queue_up.value
            + 0.3 * self.cpu.value
            + 0.3 * (1.0 - self.absorption.value)
    }

    /// Provenance más débil de los tres (para el provenance_manifest: la cifra
    /// publicada hereda la honestidad de su peor componente).
    pub fn weakest_provenance(&self) -> Provenance {
        use Provenance::*;
        for p in [self.queue_up, self.absorption, self.cpu] {
            if p.provenance == Scaffold {
                return Scaffold;
            }
        }
        if self.queue_up.provenance == Synthetic
            || self.absorption.provenance == Synthetic
            || self.cpu.provenance == Synthetic
        {
            return Synthetic;
        }
        if self.queue_up.provenance == Param
            || self.absorption.provenance == Param
            || self.cpu.provenance == Param
        {
            return Param;
        }
        Measured
    }

    /// dump para provenance_manifest (valores + clase + fuente por corrida).
    pub fn to_manifest_json(&self) -> serde_json::Value {
        let f = |s: &Sample| {
            serde_json::json!({
                "value": s.value,
                "provenance": match s.provenance {
                    Provenance::Measured => "measured",
                    Provenance::Param => "param",
                    Provenance::Scaffold => "scaffold",
                    Provenance::Synthetic => "synthetic",
                },
                "source": s.source,
            })
        };
        serde_json::json!({
            "queue_up": f(&self.queue_up),
            "absorption": f(&self.absorption),
            "cpu": f(&self.cpu),
            "pressure": self.pressure(),
            "weakest": match self.weakest_provenance() {
                Provenance::Measured => "measured",
                Provenance::Param => "param",
                Provenance::Scaffold => "scaffold",
                Provenance::Synthetic => "synthetic",
            },
        })
    }
}

// ─── FeederCtx — locales del run que solo el sitio conoce ─────────────────────

/// Clase del psi inyectado: Measured (test) vs Sim — los térmicos usan
/// cpu:=temp/SAFETY_TEMP etiquetado sim_cpu (decision S5 b/B1, finding_6:
/// "la corrida SÍ es su máquina"); jamás finge measured.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PsiKind {
    Measured,
    Sim,
}

/// ctx por tick: los locales del run (H/H_max, trust) alimentan el acoplamiento
/// sintético (q3 state_coupled: queue := H/H_max, absorption := trust);
/// `psi` permite inyectar PSI en tests (determinismo, R10) — en vivo = None
/// (lectura real de /proc).
#[derive(Debug, Clone, Copy)]
pub struct FeederCtx {
    pub h_norm: f64,
    pub trust: f64,
    pub tick: u64,
    pub psi: Option<f64>,
    pub psi_kind: PsiKind,
}

impl FeederCtx {
    /// Contexto de corrida/vivo — PSI leído de /proc (R).
    pub fn live(h_norm: f64, trust: f64, tick: u64) -> Self {
        FeederCtx { h_norm, trust, tick, psi: None, psi_kind: PsiKind::Measured }
    }
    /// Contexto de test — PSI inyectado (determinista, R).
    pub fn with_psi(h_norm: f64, trust: f64, tick: u64, psi: f64) -> Self {
        FeederCtx { h_norm, trust, tick, psi: Some(psi), psi_kind: PsiKind::Measured }
    }
    /// Térmicos — cpu:=temp/SAFETY declarado sim_cpu (S, nunca R).
    pub fn with_sim_psi(h_norm: f64, trust: f64, tick: u64, sim_cpu: f64) -> Self {
        FeederCtx { h_norm, trust, tick, psi: Some(sim_cpu), psi_kind: PsiKind::Sim }
    }
}

// ─── PSI (cross-read /proc — patrón hardware_ingest.rs:226) ──────────────────

/// /proc/pressure/cpu some avg10 → [0,1]. None si ausente (WSL/containers sin
/// PSI): el caller decide (fallback Param declarado, jamás 0.0 "medido").
pub fn read_psi_cpu() -> Option<f64> {
    let s = std::fs::read_to_string("/proc/pressure/cpu").ok()?;
    for tok in s.split_whitespace() {
        if let Some(v) = tok.strip_prefix("avg10=") {
            if let Ok(pct) = v.parse::<f64>() {
                return Some((pct / 100.0).clamp(0.0, 1.0));
            }
        }
    }
    None
}

fn psi_sample(ctx: &FeederCtx) -> Sample {
    match ctx.psi {
        Some(v) => match ctx.psi_kind {
            PsiKind::Measured => Sample::measured(v.clamp(0.0, 1.0), "psi:injected"),
            // sim_cpu declarado — Synthetic, jamás finge measured (R9)
            PsiKind::Sim => Sample::synthetic(v.clamp(0.0, 1.0), "sim_cpu:temp/SAFETY"),
        },
        None => match read_psi_cpu() {
            Some(v) => Sample::measured(v, "psi:/proc/pressure/cpu"),
            None => Sample::param(0.0, "psi:absent→param0"),
        },
    }
}

// ─── FeederSource trait ───────────────────────────────────────────────────────

/// Send: KernelStepper vive dentro del future de operational.rs — sin supertrait
/// Send el trait object rompe spawn_supervised (error E0277 no-Send).
/// clone_box: KernelStepper derive(Clone) lo exige (Dispatcher clonable para
/// tests/wiring) — dyn-clone manual, cada fuente es un struct simple Clone.
pub trait FeederSource: Send {
    fn sample(&mut self, ctx: &FeederCtx) -> FeederValues;
    fn name(&self) -> &'static str;
    fn clone_box(&self) -> Box<dyn FeederSource>;
}

// ─── Fallback (q3) — runs sin feeder: queue=0, abs=1.0, PSI direct ───────────
// Es EXACTAMENTE lo que los sitios hardcodeaban hoy (queue=0, abs=1.0) más el
// PSI real — al rewire la numérica cambia solo en el término 0.3·cpu que antes
// era 0.3·|Δh|/h_max. Declarado, jamás provenance=measured para queue/abs.

#[derive(Clone)]
pub struct FallbackFeeder;

impl FeederSource for FallbackFeeder {
    fn sample(&mut self, ctx: &FeederCtx) -> FeederValues {
        FeederValues {
            queue_up: Sample::param(0.0, "fallback:queue=0"),
            absorption: Sample::param(1.0, "fallback:abs=1.0"),
            cpu: psi_sample(ctx),
        }
    }
    fn name(&self) -> &'static str { "fallback" }
    fn clone_box(&self) -> Box<dyn FeederSource> { Box::new(self.clone()) }
}

// ─── StateDb (queue_state — mirror del ledger_A vivo) ────────────────────────
// REWIRE 2026-10-09 (S5 "todo aprobado"): antes leía algedonic_ledger
// (= ledger_B RETIRADA → 1456 filas congeladas → queue_up=1.0 pinneado,
// absorption=0.0 congelado — clase-S declarada en P4). Ahora lee la fila
// única de queue_state, espejo del ledger_A vivo escrito por el mirror
// timer vsf-queue-mirror (n02 → LXC101 state.db, cadencia 5min) con
// feeder_stale wall-clock estricto: mirror más viejo que 900s → fallback
// declarado visible (nunca measured falso, R9).

/// max_age del mirror (canonizado en P4: state/telemetry_ports.json
/// abreath.queue_up.freshness.max_age_s = 900).
pub const MIRROR_MAX_AGE_S: i64 = 900;

#[derive(Clone)]
pub struct StateDbFeeder {
    pub path: PathBuf,
    /// max_age estricto (ronda-2): una lectura con éxito Y fresca es
    /// measured; stale o error degrada a fallback declarado + source tag
    /// "statedb:stale→…" / "statedb:error→…".
    pub enabled: bool,
}

impl StateDbFeeder {
    pub fn new(path: impl Into<PathBuf>) -> Self {
        StateDbFeeder { path: path.into(), enabled: true }
    }
    pub fn default_path() -> PathBuf {
        std::env::var("VSF_STATE_DB")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from(DEFAULT_STATE_DB))
    }
    pub fn from_env() -> Self {
        Self::new(Self::default_path())
    }

    fn read(&self) -> Result<FeederValues, String> {
        // READ-ONLY (rewire 2026-10-09): el feeder SOLO hace SELECT sobre el
        // mirror. En LXC101 /var/lib/vsf-state es un bind-mount ro=1 (la
        // escritura vive en el host vía timer); Connection::open (RW por
        // defecto) falla con SQLITE_CANTOPEN en mount ro → fallback eterno
        // abs=1.0/queue=0.0 (bug observado en prod 2026-10-09T01:19Z).
        let conn = rusqlite::Connection::open_with_flags(
            &self.path,
            rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
        )
        .map_err(|e| format!("open: {e}"))?;
        conn.busy_timeout(std::time::Duration::from_millis(2000))
            .map_err(|e| format!("busy: {e}"))?;
        let (pending, total, handled, mirrored_at): (i64, i64, i64, i64) = conn
            .query_row(
                "SELECT pending, total, handled, mirrored_at \
                 FROM queue_state WHERE id = 1",
                [],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
            )
            .map_err(|e| format!("query queue_state: {e}"))?;
        // feeder_stale wall-clock (canon P4, max_age 900s): mirror viejo →
        // Err → fallback declarado visible. Sin esto una lectura con éxito
        // siempre es "fresh" aunque el mirror lleve días caído (la
        // divergencia R9 que P4 declaró).
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs() as i64)
            .unwrap_or(0);
        let age = now.saturating_sub(mirrored_at);
        if age > MIRROR_MAX_AGE_S {
            return Err(format!(
                "stale(mirror): age {age}s > {MIRROR_MAX_AGE_S}s"
            ));
        }
        let queue = ((pending as f64) / QUEUE_NORM_DIVISOR).min(1.0);
        let absorption = if total == 0 {
            1.0 // mirror de ledger vacío: nada por absorber (convención declarada)
        } else {
            (handled as f64 / total as f64).clamp(0.0, 1.0)
        };
        Ok(FeederValues {
            queue_up: Sample::measured(queue, "statedb:queue_state.pending_human"),
            absorption: Sample::measured(absorption, "statedb:queue_state.status_rates"),
            cpu: psi_sample(&FeederCtx::live(0.0, 0.0, 0)),
        })
    }
}

impl FeederSource for StateDbFeeder {
    fn sample(&mut self, ctx: &FeederCtx) -> FeederValues {
        if !self.enabled {
            let mut fb = FallbackFeeder;
            let mut v = fb.sample(ctx);
            v.queue_up = Sample::param(0.0, "statedb:disabled→fallback");
            v.absorption = Sample::param(1.0, "statedb:disabled→fallback");
            return v;
        }
        match self.read() {
            Ok(mut v) => {
                // cpu del ctx (tests inyectan PSI; vivo relee /proc)
                v.cpu = psi_sample(ctx);
                v
            }
            Err(e) => {
                // Stale/error → valores fallback PERO con provenance Param y
                // source tag que deja el fallo visible (R9: jamás silencio).
                // stale(mirror) → "statedb:stale→…", cualquier otro → error.
                let stale = e.starts_with("stale(");
                let (qtag, atag) = if stale {
                    ("statedb:stale→fallback.queue", "statedb:stale→fallback.abs")
                } else {
                    ("statedb:error→fallback.queue", "statedb:error→fallback.abs")
                };
                let mut fb = FallbackFeeder;
                let mut v = fb.sample(ctx);
                v.queue_up = Sample::param(0.0, qtag);
                v.absorption = Sample::param(1.0, atag);
                v
            }
        }
    }
    fn name(&self) -> &'static str { "statedb" }
    fn clone_box(&self) -> Box<dyn FeederSource> { Box::new(self.clone()) }
}

// ─── Synthetic::state_coupled (q3 — spec_boot nominal) ────────────────────────
// queue := H/H_max, absorption := trust (locales del run vía ctx), cpu := PSI.

#[derive(Clone)]
pub struct SyntheticCoupled;

impl FeederSource for SyntheticCoupled {
    fn sample(&mut self, ctx: &FeederCtx) -> FeederValues {
        FeederValues {
            queue_up: Sample::synthetic(ctx.h_norm.clamp(0.0, 1.0), "synthetic:state_coupled.queue=H/H_max"),
            absorption: Sample::synthetic(ctx.trust.clamp(0.0, 1.0), "synthetic:state_coupled.abs=trust"),
            cpu: psi_sample(ctx),
        }
    }
    fn name(&self) -> &'static str { "synthetic_coupled" }
    fn clone_box(&self) -> Box<dyn FeederSource> { Box::new(self.clone()) }
}

// ─── Synthetic::osc (q3 — stress A_breath λ_max) ──────────────────────────────
// Barrido queue 0→1→0 (triángulo determinista sobre tick; period en ticks).

#[derive(Clone)]
pub struct SyntheticOsc {
    pub period_ticks: u64,
}

impl SyntheticOsc {
    pub fn new(period_ticks: u64) -> Self {
        SyntheticOsc { period_ticks: period_ticks.max(2) }
    }
    /// barrido 0→1→0 determinista (R10 — sin trigonometría: exacto por tick).
    pub fn queue_at(tick: u64, period_ticks: u64) -> f64 {
        let period = period_ticks.max(2);
        let phase = tick % period;
        let half = period / 2;
        if phase <= half {
            phase as f64 / half as f64
        } else {
            (period - phase) as f64 / (period - half) as f64
        }
    }
}

impl FeederSource for SyntheticOsc {
    fn sample(&mut self, ctx: &FeederCtx) -> FeederValues {
        FeederValues {
            queue_up: Sample::synthetic(
                Self::queue_at(ctx.tick, self.period_ticks),
                "synthetic:osc.queue_sweep",
            ),
            absorption: Sample::synthetic(ctx.trust.clamp(0.0, 1.0), "synthetic:osc.abs=trust"),
            cpu: psi_sample(ctx),
        }
    }
    fn name(&self) -> &'static str { "synthetic_osc" }
    fn clone_box(&self) -> Box<dyn FeederSource> { Box::new(self.clone()) }
}

// ─── Dispatcher — ingest → feed → step → emit (core inmutable) ────────────────

pub struct Dispatcher {
    source: Box<dyn FeederSource>,
    /// q2: default ON. false = status:paused — el corte es estado, no un if
    /// escondido; los sitios reciben fallback declarado.
    enabled: bool,
    last: Option<FeederValues>,
    feeds: u64,
}

// KernelStepper deriva Debug+Clone y vive en el future de operational.rs:
// Dispatcher necesita los dos + Send (vía FeederSource: Send) para que la
// derive compile y el async spawn sea Send. Debug manual — el trait object
// no es Debug, logueamos el nombre de la fuente en su lugar.
impl Clone for Dispatcher {
    fn clone(&self) -> Self {
        Dispatcher {
            source: self.source.clone_box(),
            enabled: self.enabled,
            last: self.last,
            feeds: self.feeds,
        }
    }
}

impl std::fmt::Debug for Dispatcher {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Dispatcher")
            .field("source", &self.source.name())
            .field("enabled", &self.enabled)
            .field("feeds", &self.feeds)
            .field("last", &self.last)
            .finish()
    }
}

impl Dispatcher {
    pub fn new(source: Box<dyn FeederSource>) -> Self {
        let enabled = match std::env::var(ENV_FEEDERS) {
            Ok(v) => v != "paused" && !v.is_empty(),
            Err(_) => true, // default ON (q2)
        };
        Dispatcher { source, enabled, last: None, feeds: 0 }
    }
    /// runs sin feeder (q3): queue=0, abs=1.0, PSI direct — declarado.
    pub fn fallback() -> Self {
        Self::new(Box::new(FallbackFeeder))
    }
    /// spec_boot nominal (q3 state_coupled).
    pub fn coupled() -> Self {
        Self::new(Box::new(SyntheticCoupled))
    }
    /// stress A_breath λ_max (q3 osc).
    pub fn osc(period_ticks: u64) -> Self {
        Self::new(Box::new(SyntheticOsc::new(period_ticks)))
    }
    /// live daemon (n02/LXC101): ledger_A directo.
    pub fn state_db(path: impl Into<PathBuf>) -> Self {
        Self::new(Box::new(StateDbFeeder::new(path)))
    }
    pub fn state_db_from_env() -> Self {
        Self::new(Box::new(StateDbFeeder::from_env()))
    }
    /// override manual del kill-switch (tests / wiring explícito).
    pub fn with_kill_switch(mut self, on: bool) -> Self {
        self.enabled = on;
        self
    }

    /// fase feed del tick loop: muestrea (o corta a fallback si paused).
    pub fn feed(&mut self, ctx: &FeederCtx) -> &FeederValues {
        let v = if self.enabled {
            self.source.sample(ctx)
        } else {
            let mut fb = FallbackFeeder;
            let mut v = fb.sample(ctx);
            v.queue_up = Sample::param(0.0, "paused:feed_off");
            v.absorption = Sample::param(1.0, "paused:feed_off");
            v
        };
        self.last = Some(v);
        self.feeds += 1;
        self.last.as_ref().expect("just set")
    }

    pub fn last(&self) -> Option<&FeederValues> {
        self.last.as_ref()
    }

    pub fn feeds(&self) -> u64 { self.feeds }
    pub fn enabled(&self) -> bool { self.enabled }
    pub fn source_name(&self) -> &'static str { self.source.name() }

    /// presión canon del último feed (si aún no hubo feed, fallback honesto).
    pub fn pressure(&self) -> f64 {
        match &self.last {
            Some(v) => v.pressure(),
            None => FallbackFeeder.sample(&FeederCtx::live(0.0, 0.0, 0)).pressure(),
        }
    }

    /// dump del último feed para provenance_manifest (P1: accesible; el
    /// escritor por corrida llega con los gates de P2).
    pub fn manifest(&self) -> Option<serde_json::Value> {
        self.last.as_ref().map(|v| {
            let mut m = v.to_manifest_json();
            m["source"] = serde_json::json!(self.source.name());
            m["enabled"] = serde_json::json!(self.enabled);
            m["feeds"] = serde_json::json!(self.feeds);
            m
        })
    }
}

// ─── tests ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canon_formula_exact() {
        let v = FeederValues {
            queue_up: Sample::param(0.5, "t"),
            absorption: Sample::param(0.25, "t"),
            cpu: Sample::param(1.0, "t"),
        };
        // 0.4·0.5 + 0.3·1.0 + 0.3·0.75 = 0.2 + 0.3 + 0.225
        assert!((v.pressure() - 0.725).abs() < 1e-12, "got {}", v.pressure());
    }

    #[test]
    fn fallback_matches_declared_class_s_values() {
        let mut d = Dispatcher::fallback().with_kill_switch(true);
        let v = d.feed(&FeederCtx::with_psi(0.7, 0.9, 3, 0.4));
        assert_eq!(v.queue_up.value, 0.0);
        assert_eq!(v.absorption.value, 1.0);
        assert_eq!(v.cpu.value, 0.4);
        // declared, never measured
        assert_eq!(v.queue_up.provenance, Provenance::Param);
        assert_eq!(v.absorption.provenance, Provenance::Param);
        assert_eq!(v.cpu.provenance, Provenance::Measured);
        // pressure = 0.4·0 + 0.3·0.4 + 0.3·0 = 0.12
        assert!((d.pressure() - 0.12).abs() < 1e-12);
    }

    #[test]
    fn kill_switch_paused_declares_fallback() {
        let mut d = Dispatcher::coupled().with_kill_switch(false);
        // .clone() → valor owned: FeederValues es Copy, así `d.enabled()` después
        // no choca con el borrow que devuelve feed() (E0502).
        let v = d.feed(&FeederCtx::with_psi(0.9, 0.1, 0, 0.3)).clone();
        assert_eq!(v.queue_up.value, 0.0, "paused → queue fallback");
        assert_eq!(v.queue_up.source, "paused:feed_off");
        assert!(!d.enabled());
        assert_eq!(v.weakest_provenance(), Provenance::Param);
    }

    #[test]
    fn state_coupled_uses_run_locals() {
        let mut d = Dispatcher::coupled();
        let v = d.feed(&FeederCtx::with_psi(0.5, 0.8, 0, 0.2));
        assert_eq!(v.queue_up.value, 0.5);
        assert_eq!(v.queue_up.provenance, Provenance::Synthetic);
        assert_eq!(v.absorption.value, 0.8);
        // 0.4·0.5 + 0.3·0.2 + 0.3·0.2 = 0.2+0.06+0.06 = 0.32
        assert!((v.pressure() - 0.32).abs() < 1e-12);
        assert_eq!(v.weakest_provenance(), Provenance::Synthetic);
    }

    #[test]
    fn osc_sweeps_0_to_1_to_0_deterministically() {
        let period = 10u64;
        let vals: Vec<f64> = (0..=period).map(|t| SyntheticOsc::queue_at(t, period)).collect();
        assert_eq!(vals[0], 0.0);
        assert_eq!(vals[5], 1.0, "half period = peak: {vals:?}");
        assert_eq!(vals[10], 0.0);
        // monotone up then down
        for w in vals.windows(2) {
            assert!(w[0] <= w[1] || w[1] <= w[0]);
        }
        // determinism (R10): same tick → same value
        assert_eq!(SyntheticOsc::queue_at(3, period), SyntheticOsc::queue_at(3, period));
        let mut d = Dispatcher::osc(period);
        let v = d.feed(&FeederCtx::with_psi(0.0, 1.0, 5, 0.0));
        assert_eq!(v.queue_up.value, 1.0);
        assert_eq!(v.queue_up.provenance, Provenance::Synthetic);
    }

    #[test]
    fn statedb_reads_mirror_rates() {
        let dir = std::env::temp_dir().join(format!("feeders_test_{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let db = dir.join("ledger.db");
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs() as i64;
        {
            let c = rusqlite::Connection::open(&db).unwrap();
            c.execute(
                "CREATE TABLE queue_state \
                 (id INTEGER PRIMARY KEY, pending INTEGER, total INTEGER, \
                  handled INTEGER, mirrored_at INTEGER)",
                [],
            )
            .unwrap();
            c.execute(
                "INSERT INTO queue_state (id,pending,total,handled,mirrored_at) \
                 VALUES (1, 3, 5, 2, ?1)",
                [now],
            )
            .unwrap();
        }
        let mut f = StateDbFeeder::new(&db);
        let v = f.sample(&FeederCtx::with_psi(0.0, 0.0, 0, 0.1));
        // queue = 3/1000
        assert!((v.queue_up.value - 0.003).abs() < 1e-12, "got {}", v.queue_up.value);
        assert_eq!(v.queue_up.provenance, Provenance::Measured);
        assert_eq!(v.queue_up.source, "statedb:queue_state.pending_human");
        // absorption = 2/5 = 0.4
        assert!((v.absorption.value - 0.4).abs() < 1e-12, "got {}", v.absorption.value);
        assert_eq!(v.absorption.provenance, Provenance::Measured);
        assert_eq!(v.cpu.value, 0.1);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn statedb_stale_mirror_falls_back_declared_never_measured() {
        let dir = std::env::temp_dir().join(format!("feeders_stale_{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let db = dir.join("ledger.db");
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs() as i64;
        {
            let c = rusqlite::Connection::open(&db).unwrap();
            c.execute(
                "CREATE TABLE queue_state \
                 (id INTEGER PRIMARY KEY, pending INTEGER, total INTEGER, \
                  handled INTEGER, mirrored_at INTEGER)",
                [],
            )
            .unwrap();
            // mirror de hace 1000s > MIRROR_MAX_AGE_S (900) → stale
            c.execute(
                "INSERT INTO queue_state (id,pending,total,handled,mirrored_at) \
                 VALUES (1, 500, 5000, 100, ?1)",
                [now - 1000],
            )
            .unwrap();
        }
        let mut f = StateDbFeeder::new(&db);
        let v = f.sample(&FeederCtx::with_psi(0.0, 0.0, 0, 0.1));
        // feeder_stale honesto: valores fallback + tag stale visible, NUNCA
        // measured con el 500 pendientes congelados del mirror viejo.
        assert_eq!(v.queue_up.value, 0.0);
        assert_eq!(v.absorption.value, 1.0);
        assert_eq!(v.queue_up.provenance, Provenance::Param);
        assert!(v.queue_up.source.starts_with("statedb:stale"), "source={}", v.queue_up.source);
        assert!(v.absorption.source.starts_with("statedb:stale"), "source={}", v.absorption.source);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn statedb_error_falls_back_declared_never_measured() {
        let mut f = StateDbFeeder::new("/nonexistent/definitely_missing.db");
        let v = f.sample(&FeederCtx::with_psi(0.5, 0.5, 0, 0.2));
        assert_eq!(v.queue_up.value, 0.0);
        assert_eq!(v.absorption.value, 1.0);
        assert_eq!(v.queue_up.provenance, Provenance::Param);
        assert!(v.queue_up.source.starts_with("statedb:error"), "source={}", v.queue_up.source);
    }

    #[test]
    fn empty_mirror_absorption_convention() {
        let dir = std::env::temp_dir().join(format!("feeders_empty_{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let db = dir.join("ledger.db");
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_secs() as i64;
        {
            let c = rusqlite::Connection::open(&db).unwrap();
            c.execute(
                "CREATE TABLE queue_state \
                 (id INTEGER PRIMARY KEY, pending INTEGER, total INTEGER, \
                  handled INTEGER, mirrored_at INTEGER)",
                [],
            )
            .unwrap();
            c.execute(
                "INSERT INTO queue_state (id,pending,total,handled,mirrored_at) \
                 VALUES (1, 0, 0, 0, ?1)",
                [now],
            )
            .unwrap();
        }
        let mut f = StateDbFeeder::new(&db);
        let v = f.sample(&FeederCtx::with_psi(0.0, 0.0, 0, 0.0));
        assert_eq!(v.queue_up.value, 0.0);
        assert_eq!(v.absorption.value, 1.0, "vacío = nada por absorber (convención)");
        assert_eq!(v.absorption.provenance, Provenance::Measured);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn manifest_declares_everything() {
        let mut d = Dispatcher::state_db("/nonexistent/x.db").with_kill_switch(true);
        let _ = d.feed(&FeederCtx::with_psi(0.1, 0.2, 1, 0.3));
        let m = d.manifest().expect("manifest after feed");
        assert_eq!(m["source"], "statedb");
        assert_eq!(m["enabled"], true);
        assert_eq!(m["feeds"], 1);
        assert!(m["queue_up"]["provenance"].is_string());
        assert!(m["pressure"].is_number());
    }
}
