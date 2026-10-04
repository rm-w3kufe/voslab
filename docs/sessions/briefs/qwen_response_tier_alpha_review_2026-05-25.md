# Qwen response — Tier α review (2026-05-25)

**Brief:** `qwen_brief_tier_alpha_review_2026-05-25.md`
**Channel:** Qwen browser (DashScope)
**Net delta integrated 2026-05-25 — see commits referenced below**

---

## P1 — Policy estratégica (internal-first)
- **Position:** Confirm (con refinement)
- **Razón:** Beer exige explícitamente que S3* y S5 estén operativos antes de acoplar S1; de lo contrario, S3 captura la variedad operativa de S1 y pierde capacidad de auditoría independiente.
- **Recommendation:** Mantener política. Integrar S1 antes amplificaría brechas de control no validadas y violaría el principio de homeostasis estructural.

## P2 — Threshold 7.5/10 y criterios
- **Position:** Refine
- **Razón:** 7.5 es razonable, pero los criterios temporales (7/14/30 días) son proxies, no garantías funcionales. VSF valida por eventos, no por calendario.
- **Recommendation:** Exigir validación funcional: ≥1 ciclo S3*→S3 auditado, ≥1 trigger/resolución algedónica, ≥1 fail-closed S5 ejecutado y recuperado. Mantener 7.5 como umbral estructural.

## P3a — Sampling distribution
- **Position:** Refine
- **Razón:** Poisson es memoryless y justo, pero Ashby exige que la variedad de auditoría ≥ variedad de fallo potencial. Poisson puro puede miss drift coordinado.
- **Recommendation:** Usar Poisson como baseline para Tier α, pero diseñar hook para suspicion-weighting futuro. No overengineer ahora, pero no cerrar la puerta.

## P3b — Sandbox / aislamiento
- **Position:** Refine
- **Razón:** (a) viola independencia de S3* (comparte crash domain con S3). (c) es overkill para Tier α. (b) cumple el principio de auditoría externa sin complejidad operativa excesiva.
- **Recommendation:** Implementar (b) Proceso separado `vsf-s3-star` con acceso read-only a `events.jsonl`. Mínimo aislamiento Beer-faithful.

## P3c — Trigger de algedónico desde S3*
- **Position:** Confirm
- **Razón:** S5 define viabilidad; S3* solo evalúa. Hard thresholds o baselines rolling desalinean el audit del covenant axiomático.
- **Recommendation:** Implementar (c) Policy-driven. Iniciar con predicado JSON simple en `s5_policy.s3_star.alert_predicate` para Tier α.

## P3d — Covenant drift detection
- **Position:** Confirm
- **Razón:** Defensa en profundidad contra tampering local y drift remoto. (b) requiere infra que no existe aún; (a)+(c) es robusto y implementable.
- **Recommendation:** Implementar (d). Hash local por consistencia runtime + HTTPS GET para verificación canónica. Mismatch → señal algedónica + log.

## P4 — Sanity check VSM scoring
- **Position:** Refine
- **Razón:** S5=5 es generoso (declarativo sin enforcement ≈ 3/10). Algedonic=8 es prematuro (deployed ≠ validated ≈ 5/10). Recursión=4 es justo pero sin hooks vivos ≈ 3/10.
- **Recommendation:** Ajustar scoring base a ~5.0/10. Hace el target 7.5 más significativo y fuerza cierre funcional sobre conteo de deploys.

## P5 — Markov assumption para K_total
- **Position:** Refine
- **Razón:** BBH tiene dependencias de estado (semi-Markov). Primer orden memoryless subestima colas de fallo. n=30 es insuficiente para CI robusto.
- **Recommendation:** Adoptar modelo semi-Markov o 2nd-order si hay datos. Mínimo 100 transiciones. Usar intervalos bayesianos (Dirichlet priors) para transiciones escasas pre-W2.

---

## Sign-off

> "He revisado las 5 preguntas. Mi recomendación neta para A0 es: [Poisson baseline][Proceso separado][Policy-driven][Combo hash]. Tier α target 7.5/10 es [refinado a validación funcional]. VSF scoring 6.3/10 [ajustaría a ~5.0/10]."

Future iterations: VSL estricto.

---

## Integration record

All 5 refinements ACCEPTED by rmw3 (S5) on 2026-05-25.

Documents updated:
- `docs/PLAN.md` §4 — threshold criteria switched to functional events
- `docs/VSF_VSM_SCORING.md` — S5 5→3, Algedonic 8→5, Recursion 4→3, baseline 6.3→5.0
- `docs/GAPS_AND_DEBTS.md` — GAP-S3STAR fix updated to separate process
- `docs/operational/gate3_experimental_plan.md` — §2 semi-Markov, §3 n≥100, §A.1 Dirichlet
- Task #88 — description updated (separate binary)
- Task #91 — description updated (real fire-resolve validation)
- memory `project_vsf_vsm_scoring.md` updated
