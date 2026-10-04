#include <Arduino.h>
#include <math.h>

// ════════════════════════════════════════════════════════════════════════════
// vOS-nano Kernel v4.0 — Claude-patched per addendum_v2.vsm (2026-06-22)
// Base: Qwen Web v2.0 (2026-06-19). v2 preserved in git history.
// v3 fixes (addendum_v2):
//   FIX-1 (showstopper): bins[] sized to W_H_BINS (was [4] → OOB corruption)
//   FIX-2 (scaffold):    g = real measured SRAM slack (was hardcoded 1−200/1536)
//   FIX-3 (scaffold):    covenant sram_ok = free_ram()>512 (was hardcoded true)
//   FIX-4 (scaffold):    covenant loop_ok = real body_ms (was overwritten to 20)
//   FIX-5 (deviation):   λ_max Benettin tick-to-tick on RATIO (spec §5); cos_buf de-dual-used
// v4 (S5-chosen Option F, senescence bench — docs/theory/h_rest_senescence.vsm):
//   H_rest = running entropy FLOOR (slow EMA, sampled only at rest). state[12] (calibrated
//   stasis_H) stays FIXED ⇒ h_rest_drift = state[5]−state[12] = the SENESCENCE signal, LOGGED.
//   OBSERVE-DON'T-IMPOSE: control law L is UNCHANGED. Lets the 8-step protocol (esp. step 8,
//   turn off the room light) MEASURE whether H_rest drifts — then fit Law A/B/C to the drift.
// ════════════════════════════════════════════════════════════════════════════

// ─── PIN DEFINES ─────────────────────────────────────────────────────────
#define LED_ROJO_IZQ    3    // D3 PWM (Timer2 — now 31kHz)
#define LED_AMAR_IZQ    5    // D5 PWM (Timer0 — 976Hz)
#define LED_VERDE       6    // D6 PWM (Timer0 — 976Hz)
#define LED_AMAR_DER    9    // D9 PWM (Timer1 — 490Hz)
#define LED_ROJO_DER    10   // D10 PWM (Timer1 — 490Hz)
#define LED_BLANCO      11   // D11 PWM (Timer2 — now 31kHz) — actuador φ↓

#define FOTO_PRINCIPAL  A0   // phi_up control
#define FOTO_AMBIENTAL  A1   // phi_up referencia

// ─── CONSTANTS ───────────────────────────────────────────────────────────
#define STATE_SIZE      16
#define H_MAX           2.0f       // log2(4) = 2 bits
#define THETA_VIABLE    0.70f
#define THETA_PSI       0.79f
#define THETA_STASIS    0.95f
#define LYAP_ALPHA      0.6f
#define LYAP_BETA       0.4f
#define EMA_ALPHA       0.1f
#define H_REST_EMA      0.001f     // F (EXP-SEN-01 bench): slow running-baseline rate for H_rest
                                   //   (τ ≈ 1000 ticks ≈ 20s). Observe senescence; tunable.
#define DELTA_PWM       3
#define PWM_MIN         10
#define PWM_MAX         245
#define THETA_VAR       0.001f
#define DELTA_X_FLOOR   0.001f
#define LOOP_TARGET_MS  20
#define W_BENETTIN      10
#define W_COS_BUF       20
#define W_H_BINS        10
#define PHASE1_TICKS    250
#define PHASE2_TICKS    500
#define TAU_DEGEN       50
#define H1_THRESHOLD    150        // 150 ticks × 20ms = 3 seconds
#define RECALIB_MAX     3
#define SERIAL_LOG_EVERY 10
#define COVENANT_SRAM   512
#define COVENANT_LOOP   20
#define COVENANT_COS    0.85f
#define SRAM_TOTAL      2048       // ATmega328P SRAM (FIX-2/3)
#define SRAM_BUDGET     1536       // A3 dynamic budget

// ─── AVR MATH CONSTANTS ──────────────────────────────────────────────────
#define INV_LN2         1.4426950408889634f  // 1/ln(2) for log2 via logf

// ─── STATE VECTOR (Block A-G, 16 floats = 64 bytes) ─────────────────────
float state[STATE_SIZE];

// ─── STATIC BUFFERS ─────────────────────────────────────────────────────
// FIX-1: bins is the RING of the last W_H_BINS organelo-assignments (NOT '4 organelos').
//        The 4-organelo histogram is the local counts[4] in compute_H().
uint8_t bins[W_H_BINS];             // last-10 organelo indices (W=10)
uint8_t bin_idx = 0;               // circular index for bins
float   dx_buf[W_BENETTIN];        // Benettin window (tick-to-tick |Δratio|)
uint8_t dx_idx = 0;
float   cos_buf[W_COS_BUF];        // stasis_cos history — variance/excursion ONLY (FIX-5)
uint8_t cos_idx = 0;

// ─── CALIBRATION (phase_1) ──────────────────────────────────────────────
float   stasis_ratio = 0.0f;
float   stasis_H = 0.0f;

// ─── BENETTIN ────────────────────────────────────────────────────────────
uint32_t tick_count = 0;
float   prev_ratio = 0.0f;         // FIX-5: tick-to-tick reference for δx

// ─── LYAPUNOV ────────────────────────────────────────────────────────────
float   L_prev = 0.0f;

// ─── PWM CONTROL ─────────────────────────────────────────────────────────
int     pwm_blanco = 128;

// ─── A_AUTO / RECALIBRATION ─────────────────────────────────────────────
uint16_t degen_counter = 0;
uint8_t  recalib_attempts = 0;

// ─── H1 COUNTER ──────────────────────────────────────────────────────────
uint16_t h1_counter = 0;
bool     h1_pass = false;

// ─── LOOP TIMING ─────────────────────────────────────────────────────────
uint32_t last_loop_ms = 0;
uint16_t loop_delta_ms = 0;        // FIX-4: holds REAL body compute time (not pacing)

// ─── PHASE ───────────────────────────────────────────────────────────────
// 0=boot, 1=phase_1, 2=phase_2, 3=operational, 4=alarm
uint8_t current_phase = 0;

// ─── SERIAL MODE ─────────────────────────────────────────────────────────
#define MODE_CSV        0
#define MODE_DEBUG      1
#define MODE_PLOTTER    2
uint8_t serial_mode = MODE_CSV;
uint16_t debug_interval = 50;

// ─── FORWARD DECLARATIONS ────────────────────────────────────────────────
void phase_1();
void phase_2();
void loop_operational();
void update_leds();
bool covenant_check();
float compute_H();
float compute_stasis_cos();
float compute_L();
float estimate_lambda_max(float ratio);   // FIX-5: tick-to-tick on ratio
float compute_V();
float compute_variance();
float compute_excursion_max();
int   free_ram();                          // FIX-2/3: real SRAM measurement
void handle_serial_commands();
void print_debug_info();
void print_plotter_data();

// ─── FREE RAM (FIX-2/3) ──────────────────────────────────────────────────
// Canonical Arduino free-RAM idiom (JeeLabs). No heap ⇒ __brkval==0 ⇒
// free = stack-pointer − __heap_start (bytes between static top and stack).
extern int __heap_start, *__brkval;
int free_ram() {
    int v;
    return (int)&v - (__brkval == 0 ? (int)&__heap_start : (int)__brkval);
}

// ════════════════════════════════════════════════════════════════════════
// SETUP
// ════════════════════════════════════════════════════════════════════════
void setup() {
    Serial.begin(9600);

    Serial.println(F("\n=== vOS-nano Kernel v4.0 Starting ==="));
    Serial.println(F("v3: bins/g/sram/loop/benettin | v4: H_rest senescence bench (Option F)"));
    Serial.println(F("Serial Commands:"));
    Serial.println(F("  'c' = CSV mode (default logging)"));
    Serial.println(F("  'd' = Debug mode (detailed output)"));
    Serial.println(F("  'p' = Plotter mode (Arduino Serial Plotter)"));
    Serial.println(F("  's' = Status snapshot"));
    Serial.println(F("  'r' = Reset kernel"));
    Serial.println(F("  'i' = Info (this help)\n"));
    Serial.println(F("tick,stasis_cos,lambda_max,dL,V,pwm_blanco,phase,trust,entropy,h_rest,h_rest_drift"));

    // Pin modes
    pinMode(LED_ROJO_IZQ,  OUTPUT);
    pinMode(LED_AMAR_IZQ,  OUTPUT);
    pinMode(LED_VERDE,     OUTPUT);
    pinMode(LED_AMAR_DER,  OUTPUT);
    pinMode(LED_ROJO_DER,  OUTPUT);
    pinMode(LED_BLANCO,    OUTPUT);

    pinMode(FOTO_PRINCIPAL,  INPUT);
    pinMode(FOTO_AMBIENTAL,  INPUT);

    // ════════════════════════════════════════════════════════════════════
    // PWM FREQUENCY FIX: Timer2 prescaler = 1 → ~31kHz on pins D3, D11
    // At 490Hz the fotoresistor sees flicker; at 31kHz it sees continuous light.
    // Timer2 controls D3/D11 only; millis()/Timer0 unaffected.
    // ════════════════════════════════════════════════════════════════════
    TCCR2B = TCCR2B & 0b11111000 | 0x01;  // prescaler = 1 → ~31kHz PWM

    // Initialize state + buffers
    for (uint8_t i = 0; i < STATE_SIZE; i++) state[i] = 0.0f;
    for (uint8_t i = 0; i < W_H_BINS;  i++) bins[i] = 0;
    for (uint8_t i = 0; i < W_BENETTIN; i++) dx_buf[i] = DELTA_X_FLOOR;
    for (uint8_t i = 0; i < W_COS_BUF; i++) cos_buf[i] = 0.0f;

    state[6] = 0.0f;    // entropy_phase = boot
    state[15] = 0.25f;  // lifecycle = boot

    last_loop_ms = millis();

    // Run phase_1 (blocking, 250 ticks = 5 seconds)
    phase_1();

    // Run phase_2 (blocking, up to 500 ticks = 10 seconds)
    phase_2();
}

// ════════════════════════════════════════════════════════════════════════
// SERIAL COMMAND HANDLER (works in ALL phases)
// ════════════════════════════════════════════════════════════════════════
void handle_serial_commands() {
    if (Serial.available() > 0) {
        char cmd = Serial.read();

        switch (cmd) {
            case 'c':
                serial_mode = MODE_CSV;
                Serial.println(F("\n[MODE] CSV logging enabled"));
                Serial.println(F("tick,stasis_cos,lambda_max,dL,V,pwm_blanco,phase,trust,entropy,h_rest,h_rest_drift"));
                break;

            case 'd':
                serial_mode = MODE_DEBUG;
                Serial.println(F("\n[MODE] Debug output enabled"));
                Serial.print(F("Detailed state every "));
                Serial.print(debug_interval);
                Serial.println(F(" ticks\n"));
                break;

            case 'p':
                serial_mode = MODE_PLOTTER;
                Serial.println(F("\n[MODE] Plotter mode enabled"));
                Serial.println(F("Open Tools > Serial Plotter"));
                Serial.println(F("Format: stasis_cos:lambda_max:dL:V:trust:entropy:pwm\n"));
                break;

            case 's':
                print_debug_info();
                break;

            case 'r':
                Serial.println(F("\n[RESET] Kernel reset requested"));
                delay(100);
                asm volatile ("jmp 0");
                break;

            case 'i':
                Serial.println(F("\n=== vOS-nano Help ==="));
                Serial.println(F("Commands: c=CSV, d=Debug, p=Plotter, s=Status, r=Reset, i=Info"));
                break;

            default:
                break;
        }
    }
}

// ════════════════════════════════════════════════════════════════════════
// DEBUG INFO PRINTER
// ════════════════════════════════════════════════════════════════════════
void print_debug_info() {
    Serial.println(F("\n=== KERNEL STATUS ==="));
    Serial.print(F("Tick: ")); Serial.println(tick_count);
    Serial.print(F("Phase: "));
    switch(current_phase) {
        case 0: Serial.println(F("boot")); break;
        case 1: Serial.println(F("phase_1 (calibrating)")); break;
        case 2: Serial.println(F("phase_2 (converging)")); break;
        case 3: Serial.println(F("operational")); break;
        case 4: Serial.println(F("ALARM")); break;
    }

    Serial.print(F("Governed: ")); Serial.println(state[3] > 0.5f ? F("TRUE") : F("FALSE"));
    Serial.print(F("Lifecycle: ")); Serial.println(state[15], 3);

    Serial.println(F("\n--- Sensors (EMA) ---"));
    Serial.print(F("A0 (principal): ")); Serial.println((int)state[7]);
    Serial.print(F("A1 (ambiental): ")); Serial.println((int)state[8]);

    Serial.println(F("\n--- Viability Metrics ---"));
    Serial.print(F("stasis_cos: ")); Serial.println(state[10], 4);
    Serial.print(F("lambda_max: ")); Serial.println(state[13], 6);
    Serial.print(F("dL: ")); Serial.println(state[14], 6);

    float V = compute_V();
    Serial.print(F("V (viability): ")); Serial.println(V, 4);

    Serial.println(F("\n--- Trust & Entropy ---"));
    Serial.print(F("trust(t): ")); Serial.println(state[2], 4);
    Serial.print(F("H(t): ")); Serial.println(state[4], 4);
    Serial.print(F("H_rest (floor): ")); Serial.println(state[5], 4);
    Serial.print(F("H_rest_drift: ")); Serial.println(state[5] - state[12], 4);  // senescence

    Serial.println(F("\n--- Control ---"));
    Serial.print(F("PWM blanco: ")); Serial.println(pwm_blanco);
    Serial.print(F("Recalib attempts: ")); Serial.println(recalib_attempts);
    Serial.print(F("Degen counter: ")); Serial.println(degen_counter);
    Serial.print(F("H1 pass: ")); Serial.println(h1_pass ? F("YES") : F("NO"));

    Serial.println(F("\n--- Resources (REAL) ---"));
    Serial.print(F("free_ram (bytes): ")); Serial.println(free_ram());
    Serial.print(F("loop body (ms): ")); Serial.println(loop_delta_ms);

    Serial.println(F("\n--- Stasis Calibration ---"));
    Serial.print(F("stasis_ratio: ")); Serial.println(stasis_ratio, 4);
    Serial.print(F("stasis_H: ")); Serial.println(stasis_H, 4);

    Serial.println(F("\n--- Covenant Check (REAL) ---"));
    bool covenant = covenant_check();
    Serial.print(F("Covenant: ")); Serial.println(covenant ? F("PASS") : F("FAIL"));

    Serial.println(F("=====================\n"));
}

// ════════════════════════════════════════════════════════════════════════
// PLOTTER DATA PRINTER
// ════════════════════════════════════════════════════════════════════════
void print_plotter_data() {
    float V = compute_V();

    Serial.print(F("stasis_cos:")); Serial.print(state[10], 4);
    Serial.print(F(",lambda_max:")); Serial.print(state[13], 6);
    Serial.print(F(",dL:")); Serial.print(state[14], 6);
    Serial.print(F(",V:")); Serial.print(V, 4);
    Serial.print(F(",trust:")); Serial.print(state[2], 4);
    Serial.print(F(",entropy:")); Serial.print(state[4], 4);
    Serial.print(F(",pwm:")); Serial.print(pwm_blanco);
    Serial.print(F(",hrest_drift:")); Serial.println(state[5] - state[12], 4);
}

// ════════════════════════════════════════════════════════════════════════
// PHASE 1: CALIBRACIÓN PASIVA (250 ticks)
// ════════════════════════════════════════════════════════════════════════
void phase_1() {
    current_phase = 1;
    state[6] = 0.25f;
    state[15] = 0.5f;

    analogWrite(LED_BLANCO, 0);

    Serial.println(F("\n[PHASE 1] Calibrating..."));

    float ratio_sum = 0.0f;
    uint16_t n = 0;

    for (uint8_t i = 0; i < W_H_BINS; i++) bins[i] = 0;
    bin_idx = 0;

    for (uint16_t t = 0; t < PHASE1_TICKS; t++) {
        handle_serial_commands();

        uint32_t now = millis();
        uint32_t elapsed = now - last_loop_ms;
        if (elapsed < LOOP_TARGET_MS) {
            delay(LOOP_TARGET_MS - elapsed);
        }
        last_loop_ms = millis();

        int a0 = analogRead(FOTO_PRINCIPAL);
        int a1 = analogRead(FOTO_AMBIENTAL);

        state[7] = (1.0f - EMA_ALPHA) * state[7] + EMA_ALPHA * (float)a0;
        state[8] = (1.0f - EMA_ALPHA) * state[8] + EMA_ALPHA * (float)a1;

        float ratio;
        if (state[8] > 10.0f) {
            ratio = state[7] / state[8];
        } else {
            ratio = state[7] / 10.0f;
        }

        ratio_sum += ratio;
        n++;

        uint8_t organelo;
        if (a0 <= 255)       organelo = 0;
        else if (a0 <= 511)  organelo = 1;
        else if (a0 <= 767)  organelo = 2;
        else                 organelo = 3;

        bins[bin_idx] = organelo;
        bin_idx = (bin_idx + 1) % W_H_BINS;

        uint8_t progress = (uint8_t)map(t, 0, PHASE1_TICKS - 1, 0, 255);
        analogWrite(LED_ROJO_IZQ, 0);
        analogWrite(LED_AMAR_IZQ, 0);
        analogWrite(LED_VERDE, progress);
        analogWrite(LED_AMAR_DER, 0);
        analogWrite(LED_ROJO_DER, 0);
    }

    stasis_ratio = ratio_sum / (float)n;
    state[11] = stasis_ratio;

    stasis_H = compute_H();
    state[5] = stasis_H;
    state[12] = stasis_H;

    state[10] = 1.0f;
    prev_ratio = stasis_ratio;   // FIX-5: warm-start Benettin reference

    Serial.println(F("[PHASE 1] Calibration complete"));
    Serial.print(F("  stasis_ratio: ")); Serial.println(stasis_ratio, 4);
    Serial.print(F("  stasis_H: ")); Serial.println(stasis_H, 4);
}

// ════════════════════════════════════════════════════════════════════════
// PHASE 2: CONVERGENCIA ACTIVA (≤500 ticks)
// ════════════════════════════════════════════════════════════════════════
void phase_2() {
    current_phase = 2;
    state[6] = 0.5f;
    state[15] = 0.75f;

    pwm_blanco = 128;
    analogWrite(LED_BLANCO, pwm_blanco);

    Serial.println(F("\n[PHASE 2] Converging..."));

    for (uint16_t t = 0; t < PHASE2_TICKS; t++) {
        handle_serial_commands();

        uint32_t now = millis();
        uint32_t elapsed = now - last_loop_ms;
        if (elapsed < LOOP_TARGET_MS) {
            delay(LOOP_TARGET_MS - elapsed);
        }
        last_loop_ms = millis();
        uint32_t t_body = millis();   // FIX-4: start body timing (after pacing)

        tick_count++;

        // 1. Read sensors + EMA
        int a0 = analogRead(FOTO_PRINCIPAL);
        int a1 = analogRead(FOTO_AMBIENTAL);
        state[7] = (1.0f - EMA_ALPHA) * state[7] + EMA_ALPHA * (float)a0;
        state[8] = (1.0f - EMA_ALPHA) * state[8] + EMA_ALPHA * (float)a1;

        // 2. Ratio
        float ratio;
        if (state[8] > 10.0f) ratio = state[7] / state[8];
        else ratio = state[7] / 10.0f;

        // 3. H_t
        uint8_t organelo;
        if (a0 <= 255)       organelo = 0;
        else if (a0 <= 511)  organelo = 1;
        else if (a0 <= 767)  organelo = 2;
        else                 organelo = 3;
        bins[bin_idx] = organelo;
        bin_idx = (bin_idx + 1) % W_H_BINS;
        state[4] = compute_H();

        // 4. stasis_cos  (+ FIX-5: cos_buf is variance/excursion history ONLY)
        state[10] = compute_stasis_cos();
        cos_buf[cos_idx] = state[10];
        cos_idx = (cos_idx + 1) % W_COS_BUF;

        // 5. trust = stasis_cos
        state[0] = state[1];
        state[1] = state[2];
        state[2] = state[10];

        // 6. dL
        float L_now = compute_L();
        state[14] = L_now - L_prev;
        L_prev = L_now;

        // 7. lambda_max (FIX-5: tick-to-tick on ratio)
        state[13] = estimate_lambda_max(ratio);

        // 8. V
        float V = compute_V();

        // 9. PWM control
        if (state[14] > 0.0f) {
            pwm_blanco = constrain(pwm_blanco + DELTA_PWM, PWM_MIN, PWM_MAX);
        } else if (state[14] < 0.0f) {
            pwm_blanco = constrain(pwm_blanco - DELTA_PWM, PWM_MIN, PWM_MAX);
        }
        analogWrite(LED_BLANCO, pwm_blanco);
        state[9] = (float)pwm_blanco / 255.0f;

        // 10. LEDs
        update_leds();

        // 11. viable + A_auto
        bool viable = (state[10] >= THETA_VIABLE) && (V > 0.0f);
        state[3] = viable ? 1.0f : 0.0f;

        if (state[10] < THETA_VIABLE) {
            degen_counter++;
        } else {
            degen_counter = 0;
        }

        // FIX-4: real body time before covenant
        loop_delta_ms = (uint16_t)(millis() - t_body);

        // Check covenant at end of phase_2
        if (t == PHASE2_TICKS - 1) {
            if (covenant_check()) {
                state[3] = 1.0f;
                current_phase = 3;
                state[6] = 0.75f;
                state[15] = 1.0f;
                Serial.println(F("[PHASE 2] Covenant PASS -> Operational"));
                return;
            } else {
                recalib_attempts++;
                if (recalib_attempts >= RECALIB_MAX) {
                    state[6] = 1.0f;
                    current_phase = 4;
                    Serial.println(F("[ALARM] Viability lost, S5 required"));
                    while (true) {
                        handle_serial_commands();
                        analogWrite(LED_ROJO_IZQ, 255);
                        analogWrite(LED_ROJO_DER, 255);
                        analogWrite(LED_VERDE, 0);
                        analogWrite(LED_AMAR_IZQ, 0);
                        analogWrite(LED_AMAR_DER, 0);
                        delay(250);
                        analogWrite(LED_ROJO_IZQ, 0);
                        analogWrite(LED_ROJO_DER, 0);
                        delay(250);
                    }
                } else {
                    Serial.print(F("[PHASE 2] Covenant FAIL, recalibrating ("));
                    Serial.print(recalib_attempts);
                    Serial.println(F("/3)"));
                    analogWrite(LED_ROJO_IZQ, 255);
                    delay(500);
                    analogWrite(LED_ROJO_IZQ, 0);
                    phase_1();
                    phase_2();
                    return;
                }
            }
        }
    }
}

// ════════════════════════════════════════════════════════════════════════
// MAIN LOOP
// ════════════════════════════════════════════════════════════════════════
void loop() {
    handle_serial_commands();

    if (current_phase == 3) {
        loop_operational();
    }
}

void loop_operational() {
    // Pacing: hold the 20ms tick period (FIX-4: pacing kept separate from body timing)
    uint32_t now = millis();
    uint16_t period = (uint16_t)(now - last_loop_ms);
    if (period < LOOP_TARGET_MS) {
        delay(LOOP_TARGET_MS - period);
    }
    last_loop_ms = millis();
    uint32_t t_body = millis();   // FIX-4: start body timing (after pacing)

    tick_count++;

    // 1. Read sensors + EMA
    int a0 = analogRead(FOTO_PRINCIPAL);
    int a1 = analogRead(FOTO_AMBIENTAL);
    state[7] = (1.0f - EMA_ALPHA) * state[7] + EMA_ALPHA * (float)a0;
    state[8] = (1.0f - EMA_ALPHA) * state[8] + EMA_ALPHA * (float)a1;

    // 2. Ratio
    float ratio;
    if (state[8] > 10.0f) {
        ratio = state[7] / state[8];
    } else {
        ratio = state[7] / 10.0f;
    }

    // 3. H_t
    {
        uint8_t organelo;
        if (a0 <= 255)       organelo = 0;
        else if (a0 <= 511)  organelo = 1;
        else if (a0 <= 767)  organelo = 2;
        else                 organelo = 3;

        bins[bin_idx] = organelo;
        bin_idx = (bin_idx + 1) % W_H_BINS;
    }
    state[4] = compute_H();

    // 4. stasis_cos  (+ FIX-5: cos_buf is variance/excursion history ONLY)
    state[10] = compute_stasis_cos();
    cos_buf[cos_idx] = state[10];
    cos_idx = (cos_idx + 1) % W_COS_BUF;

    // 4b. F (EXP-SEN-01 bench) — H_rest as a running entropy FLOOR, sampled ONLY at rest.
    //     'Resting entropy' = the H the system settles to when at its attractor. Updated as a
    //     slow EMA only when stasis_cos ≥ θ_stasis. state[12] (calibrated stasis_H) stays FIXED
    //     as the cosine reference → H_rest_drift = state[5]−state[12] is the SENESCENCE signal.
    //     OBSERVE-DON'T-IMPOSE: control law L (compute_L) is UNCHANGED (uses state[4], not state[5]).
    if (state[10] >= THETA_STASIS) {
        state[5] = (1.0f - H_REST_EMA) * state[5] + H_REST_EMA * state[4];
    }

    // 5. trust = stasis_cos
    state[0] = state[1];
    state[1] = state[2];
    state[2] = state[10];

    // 6. dL
    {
        float L_now = compute_L();
        state[14] = L_now - L_prev;
        L_prev = L_now;
    }

    // 7. lambda_max (FIX-5: tick-to-tick on ratio)
    state[13] = estimate_lambda_max(ratio);

    // 8. V
    float V = compute_V();

    // 9. PWM control
    if (state[14] > 0.0f) {
        pwm_blanco = constrain(pwm_blanco + DELTA_PWM, PWM_MIN, PWM_MAX);
    } else if (state[14] < 0.0f) {
        pwm_blanco = constrain(pwm_blanco - DELTA_PWM, PWM_MIN, PWM_MAX);
    }
    analogWrite(LED_BLANCO, pwm_blanco);
    state[9] = (float)pwm_blanco / 255.0f;

    // 10. LEDs
    update_leds();

    // 11. viable + A_auto
    {
        bool viable = (state[10] >= THETA_VIABLE) && (V > 0.0f);
        state[3] = viable ? 1.0f : 0.0f;

        if (state[10] < THETA_VIABLE) {
            degen_counter++;
        } else {
            degen_counter = 0;
        }

        if (degen_counter >= TAU_DEGEN) {
            recalib_attempts++;
            degen_counter = 0;

            if (recalib_attempts >= RECALIB_MAX) {
                Serial.println(F("[ALARM] Viability lost, S5 required"));
                state[6] = 1.0f;
                current_phase = 4;
                while (true) {
                    handle_serial_commands();
                    analogWrite(LED_ROJO_IZQ, 255);
                    analogWrite(LED_ROJO_DER, 255);
                    analogWrite(LED_VERDE, 0);
                    analogWrite(LED_AMAR_IZQ, 0);
                    analogWrite(LED_AMAR_DER, 0);
                    delay(250);
                    analogWrite(LED_ROJO_IZQ, 0);
                    analogWrite(LED_ROJO_DER, 0);
                    delay(250);
                }
            } else {
                Serial.print(F("[RECALIB] Attempt "));
                Serial.print(recalib_attempts);
                Serial.println(F("/3"));
                state[6] = 0.5f;
                phase_1();
                phase_2();
                return;
            }
        }
    }

    // FIX-4: real body time before covenant (step 14)
    loop_delta_ms = (uint16_t)(millis() - t_body);

    // 12. Serial output based on mode
    switch (serial_mode) {
        case MODE_CSV:
            if (tick_count % SERIAL_LOG_EVERY == 0) {
                Serial.print(tick_count);
                Serial.print(',');
                Serial.print(state[10], 4);
                Serial.print(',');
                Serial.print(state[13], 4);
                Serial.print(',');
                Serial.print(state[14], 4);
                Serial.print(',');
                Serial.print(V, 4);
                Serial.print(',');
                Serial.print(pwm_blanco);
                Serial.print(',');
                Serial.print(F("operational"));
                Serial.print(',');
                Serial.print(state[2], 4);
                Serial.print(',');
                Serial.print(state[4], 4);
                Serial.print(',');
                Serial.print(state[5], 4);                 // h_rest (running floor)
                Serial.print(',');
                Serial.println(state[5] - state[12], 4);   // h_rest_drift (senescence signal)
            }
            break;

        case MODE_DEBUG:
            if (tick_count % debug_interval == 0) {
                print_debug_info();
            }
            break;

        case MODE_PLOTTER:
            if (tick_count % 5 == 0) {
                print_plotter_data();
            }
            break;
    }

    // 13. H1 counter
    if (state[10] >= THETA_STASIS) {
        h1_counter++;
        if (h1_counter >= H1_THRESHOLD && !h1_pass) {
            h1_pass = true;
            Serial.println(F("[H1 PASS] stasis_cos >= 0.95 for 150 ticks"));
        }
    } else {
        h1_counter = 0;
    }

    // 14. covenant_check (uses real loop_delta_ms + free_ram)
    covenant_check();
}

// ════════════════════════════════════════════════════════════════════════
// HELPER FUNCTIONS
// ════════════════════════════════════════════════════════════════════════

float compute_H() {
    uint16_t counts[4] = {0, 0, 0, 0};

    for (uint8_t i = 0; i < W_H_BINS; i++) {
        counts[bins[i]]++;
    }

    float H = 0.0f;
    for (uint8_t i = 0; i < 4; i++) {
        if (counts[i] > 0) {
            float p = (float)counts[i] / (float)W_H_BINS;
            H -= p * logf(p) * INV_LN2;
        }
    }
    return H;
}

float compute_stasis_cos() {
    float v[2];
    v[0] = (state[8] > 10.0f) ? (state[7] / state[8]) : (state[7] / 10.0f);
    v[1] = state[4];

    float s[2];
    s[0] = stasis_ratio;
    s[1] = stasis_H;

    float nv = sqrtf(v[0] * v[0] + v[1] * v[1]);
    float ns = sqrtf(s[0] * s[0] + s[1] * s[1]);

    if (nv < 1e-6f || ns < 1e-6f) {
        return 0.0f;
    }

    float dot = (v[0] / nv) * (s[0] / ns) + (v[1] / nv) * (s[1] / ns);
    return constrain(dot, -1.0f, 1.0f);
}

float compute_L() {
    return LYAP_ALPHA * (1.0f - state[10]) + LYAP_BETA * (state[4] / H_MAX);
}

// FIX-5: Benettin 1D on the RATIO control variable (spec §5), tick-to-tick.
// δx(t) = |ratio(t) − ratio(t−1)|, floored; λ_max = (1/W) Σ log(δx_i / δx_{i−1}).
float estimate_lambda_max(float ratio) {
    if (tick_count < W_BENETTIN) {
        prev_ratio = ratio;
        return 0.0f;
    }

    float dx = fmaxf(fabsf(ratio - prev_ratio), DELTA_X_FLOOR);
    prev_ratio = ratio;

    dx_buf[dx_idx] = dx;
    dx_idx = (dx_idx + 1) % W_BENETTIN;

    float sum_log = 0.0f;
    uint8_t valid = 0;
    for (uint8_t i = 1; i < W_BENETTIN; i++) {
        uint8_t curr = (dx_idx + W_BENETTIN - i) % W_BENETTIN;
        uint8_t prev = (dx_idx + W_BENETTIN - i - 1) % W_BENETTIN;
        if (dx_buf[prev] > DELTA_X_FLOOR) {
            sum_log += logf(dx_buf[curr] / dx_buf[prev]);
            valid++;
        }
    }

    if (valid > 0) {
        return sum_log / (float)valid;
    }
    return 0.0f;
}

float compute_variance() {
    float sum = 0.0f;
    float sum_sq = 0.0f;

    for (uint8_t i = 0; i < W_COS_BUF; i++) {
        sum += cos_buf[i];
        sum_sq += cos_buf[i] * cos_buf[i];
    }

    float mean = sum / (float)W_COS_BUF;
    float var = (sum_sq / (float)W_COS_BUF) - (mean * mean);
    return fmaxf(var, 0.0f);
}

float compute_excursion_max() {
    float sum = 0.0f;
    for (uint8_t i = 0; i < W_COS_BUF; i++) {
        sum += cos_buf[i];
    }
    float mean = sum / (float)W_COS_BUF;

    float max_exc = 0.0f;
    for (uint8_t i = 0; i < W_COS_BUF; i++) {
        float exc = fabsf(cos_buf[i] - mean);
        if (exc > max_exc) max_exc = exc;
    }
    return max_exc;
}

float compute_V() {
    // FIX-2: g = real measured SRAM slack (was hardcoded 1−200/1536).
    int used = SRAM_TOTAL - free_ram();
    float g = constrain(1.0f - (float)used / (float)SRAM_BUDGET, 0.0f, 1.0f);

    float c = (state[13] < 0.0f) ? 1.0f : 0.0f;

    float var = compute_variance();
    float t = (var < THETA_VAR) ? 1.0f : 0.0f;

    float epsilon_frontier = 0.7746f;
    float exc = compute_excursion_max();
    float m = 1.0f - (exc / epsilon_frontier);
    m = constrain(m, 0.0f, 1.0f);

    float V = g;
    if (c < V) V = c;
    if (t < V) V = t;
    if (m < V) V = m;

    return V;
}

bool covenant_check() {
    // FIX-3: real SRAM headroom (was hardcoded true)
    bool sram_ok = (free_ram() > COVENANT_SRAM);
    // FIX-4: real body compute time (was always-true)
    bool loop_ok = (loop_delta_ms <= COVENANT_LOOP);
    bool cos_ok  = (state[10] >= COVENANT_COS);

    return (sram_ok && loop_ok && cos_ok);
}

void update_leds() {
    float cos = state[10];

    if (cos >= THETA_STASIS) {
        analogWrite(LED_VERDE, 255);
        analogWrite(LED_AMAR_IZQ, 0);
        analogWrite(LED_AMAR_DER, 0);
        analogWrite(LED_ROJO_IZQ, 0);
        analogWrite(LED_ROJO_DER, 0);
    } else if (cos >= 0.85f) {
        analogWrite(LED_VERDE, 200);
        analogWrite(LED_AMAR_IZQ, 60);
        analogWrite(LED_AMAR_DER, 60);
        analogWrite(LED_ROJO_IZQ, 0);
        analogWrite(LED_ROJO_DER, 0);
    } else if (cos >= THETA_PSI) {
        analogWrite(LED_VERDE, 0);
        analogWrite(LED_AMAR_IZQ, 255);
        analogWrite(LED_AMAR_DER, 255);
        analogWrite(LED_ROJO_IZQ, 0);
        analogWrite(LED_ROJO_DER, 0);
    } else if (cos >= THETA_VIABLE) {
        analogWrite(LED_VERDE, 0);
        analogWrite(LED_AMAR_IZQ, 180);
        analogWrite(LED_AMAR_DER, 180);
        analogWrite(LED_ROJO_IZQ, 180);
        analogWrite(LED_ROJO_DER, 180);
    } else {
        if ((tick_count / 25) % 2 == 0) {
            analogWrite(LED_ROJO_IZQ, 255);
            analogWrite(LED_ROJO_DER, 255);
        } else {
            analogWrite(LED_ROJO_IZQ, 0);
            analogWrite(LED_ROJO_DER, 0);
        }
        analogWrite(LED_VERDE, 0);
        analogWrite(LED_AMAR_IZQ, 0);
        analogWrite(LED_AMAR_DER, 0);
    }
}
