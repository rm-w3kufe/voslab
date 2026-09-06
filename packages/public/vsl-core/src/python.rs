//! Python bindings for vsl-core via PyO3.
//!
//! Exposes: A0Gate, CovenantEnforcer, parser, and trust to Python.
//!
//! Usage (Python):
//!   import vsl_core
//!   gate = vsl_core.A0Gate()
//!   gate.validate_name("warfare_instrumentation")  # raises A0Violation

#[cfg(feature = "python")]
mod python {
    use pyo3::prelude::*;
    use pyo3::types::PyDict;

    use crate::a0_gate::{self, A0Gate};
    use crate::covenant::{CovenantEnforcer, SystemState, Verdict, Severity};
    use crate::parser::{self, Decl};
    use crate::purpose::{ApprovedPurpose, Purpose, PressureType};
    use crate::trust::TrustScore;

    // ─── A0 Gate ──────────────────────────────────────────────────────

    /// A0 Gate — checks for prohibited purpose strings.
    ///
    /// Usage:
    ///     gate = vsl_core.A0Gate()
    ///     gate.validate_name("warfare")  # raises A0Violation
    #[pyclass(name = "A0Gate")]
    struct PyA0Gate {
        inner: A0Gate,
    }

    #[pymethods]
    impl PyA0Gate {
        #[new]
        fn new() -> Self {
            Self { inner: A0Gate::new() }
        }

        /// Validate that a name does not contain prohibited keywords.
        /// Raises A0Violation on match.
        fn validate_name(&self, name: &str) -> PyResult<()> {
            self.inner.validate_name(name).map_err(|e| {
                PyErr::new::<A0Violation, _>(e.to_string())
            })
        }

        /// Get the list of prohibited keywords.
        #[staticmethod]
        fn prohibited_keywords() -> Vec<&'static str> {
            a0_gate::PROHIBITED_KEYWORDS.iter().copied().collect()
        }
    }

    // ─── Covenant Enforcer ────────────────────────────────────────────

    /// Verdict from covenant evaluation.
    #[pyclass(name = "Verdict")]
    #[derive(Clone)]
    struct PyVerdict {
        #[pyo3(get)]
        passed: bool,
        #[pyo3(get)]
        violations: Vec<PyViolation>,
    }

    /// A single covenant violation.
    #[pyclass(name = "Violation")]
    #[derive(Clone)]
    struct PyViolation {
        #[pyo3(get)]
        axiom: String,
        #[pyo3(get)]
        message: String,
        #[pyo3(get)]
        severity: String,
    }

    /// System state for covenant evaluation.
    #[pyclass(name = "SystemState")]
    struct PySystemState {
        inner: SystemState,
    }

    #[pymethods]
    impl PySystemState {
        #[new]
        #[pyo3(signature = (s5_trust, op_autonomy, pressure=None))]
        fn new(s5_trust: f64, op_autonomy: f64, pressure: Option<String>) -> Self {
            let purpose = Purpose::new(&[ApprovedPurpose::HumanLiberation])
                .expect("valid purpose");
            let pressure_type = pressure.and_then(|p| match p.as_str() {
                "resource_deprivation" => Some(PressureType::ResourceDeprivation),
                "coercion" => Some(PressureType::Coercion),
                "administrative_capture" => Some(PressureType::AdministrativeCapture),
                "budget_pressure" => Some(PressureType::BudgetPressure),
                "access_conditioning" => Some(PressureType::AccessConditioning),
                _ => None,
            });
            Self {
                inner: SystemState {
                    purpose,
                    s5_trust: TrustScore::new(s5_trust),
                    pressure: pressure_type,
                    op_autonomy,
                },
            }
        }
    }

    /// Covenant Enforcer — evaluates A0/A0.1 against system state.
    #[pyclass(name = "CovenantEnforcer")]
    struct PyCovenantEnforcer {
        inner: CovenantEnforcer,
    }

    #[pymethods]
    impl PyCovenantEnforcer {
        #[new]
        fn new() -> Self {
            Self { inner: CovenantEnforcer::default() }
        }

        /// Evaluate covenant against system state.
        fn evaluate(&self, state: &PySystemState) -> PyResult<PyVerdict> {
            let verdict = self.inner.evaluate(&state.inner)
                .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(e.to_string()))?;

            match verdict {
                Verdict::Pass => Ok(PyVerdict { passed: true, violations: vec![] }),
                Verdict::Fail(violations) => {
                    let py_violations = violations.iter().map(|v| PyViolation {
                        axiom: v.axiom.clone(),
                        message: v.message.clone(),
                        severity: match v.severity {
                            Severity::Critical => "CRITICAL".to_string(),
                            Severity::High => "HIGH".to_string(),
                            Severity::Medium => "MEDIUM".to_string(),
                        },
                    }).collect();
                    Ok(PyVerdict { passed: false, violations: py_violations })
                }
            }
        }
    }

    // ─── Parser ───────────────────────────────────────────────────────

    /// Parse a VSL string and return declarations as a list of dicts.
    #[pyfunction]
    fn parse_vsl(input: &str) -> PyResult<Vec<PyObject>> {
        let decls = parser::parse(input)
            .map_err(|e| PyErr::new::<pyo3::exceptions::PySyntaxError, _>(e.to_string()))?;

        Python::with_gil(|py| {
            let mut result = Vec::new();
            for decl in &decls {
                let dict = PyDict::new(py);
                match decl {
                    Decl::Vsm(vsm) => {
                        dict.set_item("type", "vsm")?;
                        let py = py;
                        let list = pyo3::types::PyList::empty(py);
                        for s in &vsm.subsystems {
                            list.append(*s as u32)?;
                        }
                        dict.set_item("subsystems", list)?;
                        dict.set_item("level", vsm.level)?;
                    }
                    Decl::Axiom(axiom) => {
                        dict.set_item("type", "axiom")?;
                        dict.set_item("var", &axiom.var)?;
                    }
                    Decl::Trust { time: _, expr: _ } => {
                        dict.set_item("type", "trust")?;
                    }
                }
                result.push(dict.into());
            }
            Ok(result)
        })
    }

    // ─── Trust ────────────────────────────────────────────────────────

    /// Trust score with bounds [0, 1].
    #[pyclass(name = "TrustScore")]
    struct PyTrustScore {
        inner: TrustScore,
    }

    #[pymethods]
    impl PyTrustScore {
        #[new]
        fn new(value: f64) -> Self {
            Self { inner: TrustScore::new(value) }
        }

        #[getter]
        fn value(&self) -> f64 {
            self.inner.score()
        }

        /// Check if trust is above a threshold.
        fn above(&self, threshold: f64) -> bool {
            self.inner.above(threshold)
        }
    }

    // ─── Exceptions ───────────────────────────────────────────────────

    /// Exception raised on A0 violations.
    #[pyclass(extends=pyo3::exceptions::PyException)]
    struct A0Violation;

    #[pymethods]
    impl A0Violation {
        #[new]
        fn new(_msg: String) -> Self {
            A0Violation
        }
    }

    // ─── Module ───────────────────────────────────────────────────────

    /// VSL Core — Python bindings for Viable System Language.
    #[pymodule]
    fn vsl_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_class::<PyA0Gate>()?;
        m.add_class::<PyCovenantEnforcer>()?;
        m.add_class::<PySystemState>()?;
        m.add_class::<PyVerdict>()?;
        m.add_class::<PyViolation>()?;
        m.add_class::<PyTrustScore>()?;
        m.add_class::<A0Violation>()?;
        m.add_function(wrap_pyfunction!(parse_vsl, m)?)?;
        m.add("__version__", "0.1.0")?;
        Ok(())
    }
}
