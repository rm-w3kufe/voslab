// EXP-L1-01 Phase A — real CPU-burning worker processes for cgroup v2 governance
// Each worker loops dd(1) consuming CPU; nucleus assigns it to a cgroup and
// adjusts cpu.weight proportionally to the kernel's trust score.

use std::process::{Child, Command};

pub struct Worker {
    pub id:  usize,
    pub pid: u32,
    child:   Child,
}

impl Worker {
    pub fn spawn(id: usize) -> Result<Self, String> {
        let child = Command::new("dd")
            .args(["if=/dev/zero", "of=/dev/null", "bs=1M"])
            .spawn()
            .map_err(|e| format!("worker {id} spawn failed: {e}"))?;
        let pid = child.id();
        Ok(Worker { id, pid, child })
    }
}

impl Drop for Worker {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

pub fn spawn_workers(n: usize) -> Result<Vec<Worker>, String> {
    (0..n).map(Worker::spawn).collect()
}
