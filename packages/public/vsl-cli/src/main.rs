//! VSL CLI — command-line interface for Viable System Language
//!
//! Usage:
//!   vsl parse <file>           Parse a VSL file and print AST
//!   vsl check <file>           Check A0 compliance of a file
//!   vsl validate <file>        Full covenant validation
//!   vsl gate <file>            Run A0 gate on a file
//!   vsl version                Print version

use std::env;
use std::fs;
use std::process;

use vsl_core::a0_gate::A0Gate;
use vsl_core::covenant::{CovenantEnforcer, SystemState, Verdict};
use vsl_core::parser;
use vsl_core::purpose::{ApprovedPurpose, Purpose};
use vsl_core::trust::TrustScore;

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();

    if args.is_empty() {
        print_usage();
        process::exit(1);
    }

    let result = match args[0].as_str() {
        "parse" => cmd_parse(&args[1..]),
        "check" => cmd_check(&args[1..]),
        "validate" => cmd_validate(&args[1..]),
        "gate" => cmd_gate(&args[1..]),
        "version" => cmd_version(),
        _ => {
            eprintln!("Unknown command: {}", args[0]);
            print_usage();
            process::exit(1);
        }
    };

    match result {
        Ok(()) => process::exit(0),
        Err(e) => {
            eprintln!("Error: {e}");
            process::exit(1);
        }
    }
}

fn print_usage() {
    eprintln!("VSL CLI — Viable System Language");
    eprintln!();
    eprintln!("Usage:");
    eprintln!("  vsl parse <file>       Parse VSL file, print AST");
    eprintln!("  vsl check <file>       Check A0 compliance");
    eprintln!("  vsl validate <file>    Full covenant validation");
    eprintln!("  vsl gate <file>        Run A0 gate on file content");
    eprintln!("  vsl version            Print version");
}

fn read_file(path: &str) -> Result<String, String> {
    fs::read_to_string(path).map_err(|e| format!("Cannot read '{path}': {e}"))
}

// ─── COMMANDS ────────────────────────────────────────────────────

fn cmd_parse(args: &[String]) -> Result<(), String> {
    if args.is_empty() {
        return Err("Usage: vsl parse <file>".into());
    }
    let content = read_file(&args[0])?;
    let decls = parser::parse(&content).map_err(|e| format!("Parse error: {e}"))?;

    println!("Parsed {} declaration(s):", decls.len());
    for (i, decl) in decls.iter().enumerate() {
        println!("  [{i}] {decl:?}");
    }
    Ok(())
}

fn cmd_check(args: &[String]) -> Result<(), String> {
    if args.is_empty() {
        return Err("Usage: vsl check <file>".into());
    }
    let content = read_file(&args[0])?;

    let gate = A0Gate::new();
    match gate.validate_name(&content) {
        Ok(()) => {
            println!("A0 CHECK: PASS — no prohibited content found");
            Ok(())
        }
        Err(e) => {
            println!("A0 CHECK: FAIL — {e}");
            Err("A0 violation".into())
        }
    }
}

fn cmd_validate(args: &[String]) -> Result<(), String> {
    if args.is_empty() {
        return Err("Usage: vsl validate <file>".into());
    }
    let content = read_file(&args[0])?;

    // Parse
    let decls = parser::parse(&content).map_err(|e| format!("Parse error: {e}"))?;
    println!("Parsed {} declaration(s)", decls.len());

    // A0 gate
    let gate = A0Gate::new();
    gate.validate_name(&content).map_err(|e| format!("A0 violation: {e}"))?;
    println!("A0 gate: PASS");

    // Covenant enforcement
    let purpose = Purpose::new(&[ApprovedPurpose::HumanLiberation])
        .map_err(|e| format!("Purpose error: {e}"))?;
    let state = SystemState {
        purpose,
        s5_trust: TrustScore::new(0.8),
        pressure: None,
        op_autonomy: 0.5,
    };
    let enforcer = CovenantEnforcer::default();
    let verdict = enforcer.evaluate(&state).map_err(|e| format!("Enforcer error: {e}"))?;

    match verdict {
        Verdict::Pass => {
            println!("Covenant: PASS");
            println!("VALIDATE: ALL CHECKS PASSED");
            Ok(())
        }
        Verdict::Fail(violations) => {
            println!("Covenant: FAIL ({} violations)", violations.len());
            for v in &violations {
                println!("  [{}] {}: {}", v.severity, v.axiom, v.message);
            }
            Err("Covenant violation".into())
        }
    }
}

fn cmd_gate(args: &[String]) -> Result<(), String> {
    if args.is_empty() {
        return Err("Usage: vsl gate <file>".into());
    }
    let content = read_file(&args[0])?;

    let gate = A0Gate::new();

    // Check each line
    let mut violations = 0;
    for (i, line) in content.lines().enumerate() {
        if gate.validate_name(line).is_err() {
            println!("LINE {}: A0 VIOLATION — {}", i + 1, line.trim());
            violations += 1;
        }
    }

    if violations == 0 {
        println!("GATE: PASS — 0 violations in {} lines", content.lines().count());
        Ok(())
    } else {
        println!("GATE: FAIL — {violations} violation(s)");
        Err("Gate failed".into())
    }
}

fn cmd_version() -> Result<(), String> {
    println!("vsl-cli 0.1.0");
    println!("vsl-core {}", env!("CARGO_PKG_VERSION"));
    Ok(())
}
