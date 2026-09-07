# VirtIO Notification Tracing and Overhead Benchmark
> Submitted By:
> 2023UMA0227 (Piyush Kumar)
> 2023UMA0221 (Kunal Sharma)

📄 **Full Technical Report**: See [TECHNICAL_REPORT.md](file:///home/kumar/Downloads/HakunaMatata/TECHNICAL_REPORT.md) for the 5-page submission document.

This repository contains the setup, instrumentation, and standardized benchmarking framework for measuring the performance impact of tracing and counters in QEMU's VirtIO subsystem.

---

## 1. Git Repository & Branch Information

* **Component**: QEMU Subsystem (`qemu/`)
* **Branch**: `2023UMA0227/CloudLabAssignment1`
* **Latest Commit**: `4dbdd7de3680a6fb643bd05e783f85188c7b28a0` (*Counter With Trace*)
* **Author**: `2023UMA0227 <2023UMA0227@iitjammu.ac.in>`

### Summary of Instrumented Changes:
1. **[qemu/hw/virtio/trace-events](file:///home/kumar/Downloads/HakunaMatata/qemu/hw/virtio/trace-events)**:
   * Defined separate tracepoints for `virtio_queue_notify` and `virtio_queue_notify_vq`.
   * Added the `count` integer argument to both trace events:
     ```text
     virtio_queue_notify(void *vdev, int n, void *vq, int count) "vdev %p n %d vq %p count %d"
     virtio_queue_notify_vq(void *vdev, int n, void *vq, int count) "vdev %p n %d vq %p count %d"
     ```
2. **[qemu/hw/virtio/virtio.c](file:///home/kumar/Downloads/HakunaMatata/qemu/hw/virtio/virtio.c)**:
   * Added static counter `notify_vq_count` inside `virtio_queue_notify_vq()`.
   * Added static counter `notify_count` inside `virtio_queue_notify()`.
   * Logged the incrementing counters via `trace_virtio_queue_notify_vq()` and `trace_virtio_queue_notify()`.

---

## 2. Obtaining the Alpine Linux ISO

The benchmark uses Alpine Linux 3.24 standard x86_64 image. Because ISO files are binary and large (~352MB), they are excluded by `.gitignore`.

Download the ISO directly into the repository root:

```bash
# From repository root:
wget https://dl-cdn.alpinelinux.org/alpine/v3.24/releases/x86_64/alpine-standard-3.24.1-x86_64.iso
```

Ensure the file is named:
```
alpine-standard-3.24.1-x86_64.iso
```

---

## 3. Build Prerequisites & Compilation

### Requirements (Fedora Linux):
```bash
sudo dnf install -y git gcc gcc-c++ ninja-build meson pkgconf-pkg-config \
    glib2-devel pixman-devel zlib-devel libfdt-devel
```

> **Python Requirement:**
> If building with Python < 3.11 (e.g. pyenv Python 3.10), install `tomli`:
> ```bash
> pip install tomli
> ```
> (On Python 3.11+, `tomllib` is included in the standard library).

### Configuring & Compiling QEMU:
```bash
cd qemu
mkdir -p build && cd build
../configure --target-list=x86_64-softmmu --enable-kvm --enable-trace-backends=log
ninja -j$(nproc)
```

The compiled binary will be produced at `qemu/build/qemu-system-x86_64`.

---

## 4. Running the Benchmark

The standardized benchmark runner ([benchmark_runner.py](file:///home/kumar/Downloads/HakunaMatata/benchmark_runner.py)) automates booting the VM, preparing the VirtIO block device, running the cold-cache sequential copy workload, capturing VirtIO trace logs, and computing overhead.

### Available Modes:

```bash
# 1. Unmodified Baseline (original behavior, tracing on)
python3 benchmark_runner.py unmodified

# 2. Counter with Tracing Enabled
python3 benchmark_runner.py counter+trace

# 3. Counter Only (Tracing Turned Off)
python3 benchmark_runner.py counter
```

### VM Specifications:
* **vCPUs**: 2 vCPUs (`-smp 2`)
* **RAM**: 2GB (`-m 2G`)
* **Acceleration**: KVM (`-enable-kvm -cpu host`)
* **Disk Interface**: VirtIO Block (`if=virtio`)
* **Workload**: 256MB file generated in RAM (`/tmp/benchfile.dat`), cold page cache drop (`echo 3 > /proc/sys/vm/drop_caches`), sequential copy to `/mnt/bench/target.dat` followed by `sync`.

---

## 5. Experimental Results & Overhead Analysis

| Benchmark Mode | Tracing Status | Guest Real Time | Host Elapsed Time | Delta Real vs Baseline | Total Kicks (`notify_vq`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Unmodified Baseline** | Enabled | **0.27 s** | **0.3462 s** | — *(Reference)* | 268 |
| **2. Counter + Trace** | Enabled | **0.37 s** | **0.4486 s** | **+0.10 s (+37.04%)** | 527 (cnt: 71 → 597) |
| **3. Counter Only** | **Disabled** | **0.28 s** | **0.3599 s** | **+0.01 s (+3.70%)** | 0 logged |

### Observations:
1. **Counter Overhead is Minimal (~3.7%)**:
   Executing the static integer increment on every kick without trace I/O adds only ~10 ms total execution time, within normal run-to-run variation.
2. **Tracing Overhead Dominates (~37%)**:
   String formatting, lock acquisition, and stderr/logfile I/O for every kick in QEMU's logging backend accounts for almost the entirety of the measured overhead.
3. **VirtIO Execution Path**:
   Under KVM with `ioeventfd`, 100% of guest notifications are serviced asynchronously through `virtio_queue_notify_vq()`.

---

## 6. Project Layout

```
.
├── .gitignore                      # Ignores ISOs, qcow2 images, logs, build artifacts
├── README.md                       # This documentation guide
├── alpine-standard-3.24.1-x86_64.iso (downloaded, ignored by git)
├── benchmark_runner.py             # Standardized 3-mode benchmark runner
├── data/
│   ├── baseline_report.json        # Baseline test report (JSON)
│   ├── baseline_report.txt         # Baseline test report (Text)
│   ├── counter_with_trace_report.json # Counter + trace report (JSON)
│   ├── counter_with_trace_report.txt  # Counter + trace report (Text)
│   ├── counter_report.json         # Counter only report (JSON)
│   ├── counter_report.txt          # Counter only report (Text)
│   ├── trace_unmodified.log        # Raw baseline trace events
│   ├── trace_counter_with_trace.log# Raw counter + trace events
│   └── qcow/                       # VM disk images (ignored by git)
│       ├── unmodified.qcow2
│       ├── counter_with_trace.qcow2
│       └── counter.qcow2
└── qemu/                           # QEMU submodule/source (branch: 2023UMA0227/CloudLabAssignment1)
```
