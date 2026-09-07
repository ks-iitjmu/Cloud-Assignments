#!/usr/bin/env python3
import os
import sys
import time
import json
import re
import argparse
import pexpect

ISO_PATH = "/home/kumar/Downloads/HakunaMatata/alpine-standard-3.24.1-x86_64.iso"
QEMU_BIN = "/home/kumar/Downloads/HakunaMatata/qemu/build/qemu-system-x86_64"
DATA_DIR = "/home/kumar/Downloads/HakunaMatata/data"
QCOW_DIR = os.path.join(DATA_DIR, "qcow")
BASELINE_JSON = os.path.join(DATA_DIR, "baseline_report.json")

CONFIGS = {
    "unmodified": {
        "description": "Baseline execution on unmodified QEMU",
        "disk_name": "unmodified.qcow2",
        "trace_name": "trace_unmodified.log",
        "report_json": "baseline_report.json",
        "report_txt": "baseline_report.txt",
        "enable_trace": True,
    },
    "counter+trace": {
        "description": "Modified QEMU with static counters and QEMU tracing enabled",
        "disk_name": "counter_with_trace.qcow2",
        "trace_name": "trace_counter_with_trace.log",
        "report_json": "counter_with_trace_report.json",
        "report_txt": "counter_with_trace_report.txt",
        "enable_trace": True,
    },
    "counter": {
        "description": "Modified QEMU with static counters only (tracing disabled)",
        "disk_name": "counter.qcow2",
        "trace_name": None,
        "report_json": "counter_report.json",
        "report_txt": "counter_report.txt",
        "enable_trace": False,
    }
}

def parse_args():
    parser = argparse.ArgumentParser(
        description="Standardized VirtIO copy benchmark runner for Alpine VM"
    )
    parser.add_argument(
        "mode",
        choices=["unmodified", "counter+trace", "counter_with_trace", "counter"],
        help="Benchmark mode: 'unmodified', 'counter+trace', or 'counter' (tracing disabled)"
    )
    return parser.parse_args()

def main():
    args = parse_args()
    mode_key = "counter+trace" if args.mode == "counter_with_trace" else args.mode
    cfg = CONFIGS[mode_key]

    os.makedirs(QCOW_DIR, exist_ok=True)
    disk_path = os.path.join(QCOW_DIR, cfg["disk_name"])
    trace_log = os.path.join(DATA_DIR, cfg["trace_name"]) if cfg["trace_name"] else None
    report_json = os.path.join(DATA_DIR, cfg["report_json"])
    report_txt = os.path.join(DATA_DIR, cfg["report_txt"])

    # If disk doesn't exist, clone from unmodified.qcow2 if available, or create fresh
    if not os.path.exists(disk_path):
        base_disk = os.path.join(QCOW_DIR, "unmodified.qcow2")
        if os.path.exists(base_disk):
            print(f"[*] Initializing {disk_path} from {base_disk}...")
            os.system(f"cp '{base_disk}' '{disk_path}'")
        else:
            print(f"[*] Creating new disk at {disk_path}...")
            os.system(f"qemu-img create -f qcow2 '{disk_path}' 10G")

    if trace_log and os.path.exists(trace_log):
        os.remove(trace_log)

    trace_args = f"-d trace:virtio_queue_notify* -D {trace_log}" if cfg["enable_trace"] else ""

    cmd = (
        f"{QEMU_BIN} "
        f"-enable-kvm -cpu host -m 2G -smp 2 "
        f"-drive file={disk_path},if=virtio,format=qcow2 "
        f"-cdrom {ISO_PATH} "
        f"-boot d -net none -nographic -serial mon:stdio "
        f"{trace_args}"
    ).strip()

    print(f"\n==================================================")
    print(f"[*] RUNNING BENCHMARK MODE: {mode_key.upper()}")
    print(f"[*] Description: {cfg['description']}")
    print(f"[*] Tracing Enabled: {cfg['enable_trace']}")
    print(f"[*] Disk Image: {disk_path}")
    print(f"[*] Launching QEMU:\n{cmd}\n==================================================\n")

    child = pexpect.spawn(cmd, encoding="utf-8", timeout=90)
    child.logfile = sys.stdout

    try:
        # 1. Wait for ISOLINUX boot prompt and press Enter
        print("[*] Waiting for boot prompt...")
        child.expect("boot:", timeout=30)
        child.sendline("")

        # 2. Wait for login prompt
        print("[*] Waiting for login prompt...")
        child.expect("login:", timeout=60)
        time.sleep(1)
        child.sendline("root")

        # 3. Wait for shell prompt
        child.expect(r"localhost:~# ", timeout=20)
        print("[*] Logged in as root!")

        # 4. Load vfat filesystem kernel module
        child.sendline("modprobe vfat")
        child.expect(r"localhost:~# ", timeout=10)

        # 5. Mount /dev/vda at /mnt/bench (format if not already formatted)
        print("[*] Mounting /dev/vda at /mnt/bench...")
        child.sendline("mkdir -p /mnt/bench && (mount -t vfat /dev/vda /mnt/bench || (mkfs.vfat /dev/vda && mount -t vfat /dev/vda /mnt/bench))")
        child.expect(r"localhost:~# ", timeout=30)

        child.sendline("mount | grep vda")
        child.expect(r"localhost:~# ", timeout=15)

        # 6. Generate standardized 256MB test file in RAM (/tmp)
        print("[*] Generating 256MB test file in RAM (/tmp/benchfile.dat)...")
        child.sendline("dd if=/dev/urandom of=/tmp/benchfile.dat bs=1M count=256 conv=fsync")
        child.expect(r"localhost:~# ", timeout=60)

        # 7. Drop caches inside VM to ensure a clean cold baseline
        print("[*] Dropping caches inside VM...")
        child.sendline("sync && echo 3 > /proc/sys/vm/drop_caches")
        child.expect(r"localhost:~# ", timeout=10)

        time.sleep(1)
        trace_size_before = 0
        if trace_log and os.path.exists(trace_log):
            trace_size_before = os.path.getsize(trace_log)
            print(f"[*] Trace log offset before copy benchmark: {trace_size_before} bytes")

        # 8. Run the standardized sequential copy benchmark
        print("[*] Running standardized copy benchmark: cp /tmp/benchfile.dat /mnt/bench/target.dat && sync")
        bench_cmd = "time -p sh -c 'cp /tmp/benchfile.dat /mnt/bench/target.dat && sync'"

        host_start = time.perf_counter()
        child.sendline(bench_cmd)
        child.expect(r"localhost:~# ", timeout=120)
        host_end = time.perf_counter()

        bench_output = child.before
        host_elapsed = host_end - host_start
        time.sleep(1)

        # Parse guest time -p output
        real_time = None
        user_time = None
        sys_time = None
        for line in bench_output.splitlines():
            line = line.strip()
            if line.startswith("real "):
                real_time = float(line.split()[1])
            elif line.startswith("user "):
                user_time = float(line.split()[1])
            elif line.startswith("sys "):
                sys_time = float(line.split()[1])

        # Read trace entries added during the benchmark window if enabled
        copy_trace_lines = []
        notify_calls = 0
        notify_vq_calls = 0
        notify_queue_counts = {}
        notify_vq_queue_counts = {}
        counter_values_notify = []
        counter_values_notify_vq = []

        if trace_log and os.path.exists(trace_log):
            with open(trace_log, "r") as f:
                f.seek(trace_size_before)
                copy_trace_lines = [line.strip() for line in f if line.strip()]

            for line in copy_trace_lines:
                if line.startswith("virtio_queue_notify_vq "):
                    notify_vq_calls += 1
                    m = re.search(r" n (\d+) vq \S+ count (\d+)", line)
                    if m:
                        q = int(m.group(1))
                        cnt = int(m.group(2))
                        notify_vq_queue_counts[q] = notify_vq_queue_counts.get(q, 0) + 1
                        counter_values_notify_vq.append(cnt)
                elif line.startswith("virtio_queue_notify "):
                    notify_calls += 1
                    m_cnt = re.search(r" n (\d+) vq \S+ count (\d+)", line)
                    m_nocnt = re.search(r" n (\d+) vq ", line)
                    if m_cnt:
                        q = int(m_cnt.group(1))
                        cnt = int(m_cnt.group(2))
                        notify_queue_counts[q] = notify_queue_counts.get(q, 0) + 1
                        counter_values_notify.append(cnt)
                    elif m_nocnt:
                        q = int(m_nocnt.group(1))
                        notify_queue_counts[q] = notify_queue_counts.get(q, 0) + 1

        total_trace_lines = len(copy_trace_lines)

        # Baseline comparison against baseline_report.json
        baseline_comparison = {}
        if os.path.exists(BASELINE_JSON):
            try:
                with open(BASELINE_JSON, "r") as f:
                    b_data = json.load(f)
                    b_real = b_data.get("execution_time", {}).get("guest_real_sec")
                    b_host = b_data.get("execution_time", {}).get("host_elapsed_sec")
                    b_calls = b_data.get("virtio_notify_metrics", {}).get("total_virtio_queue_notify_calls")
                    if b_real is not None and real_time is not None:
                        baseline_comparison["baseline_guest_real_sec"] = b_real
                        baseline_comparison["delta_guest_real_sec"] = round(real_time - b_real, 4)
                        baseline_comparison["guest_real_overhead_percent"] = round(((real_time - b_real) / b_real) * 100, 2)
                    if b_host is not None and host_elapsed is not None:
                        baseline_comparison["baseline_host_elapsed_sec"] = b_host
                        baseline_comparison["delta_host_elapsed_sec"] = round(host_elapsed - b_host, 4)
                        baseline_comparison["host_elapsed_overhead_percent"] = round(((host_elapsed - b_host) / b_host) * 100, 2)
                    baseline_comparison["baseline_total_calls"] = b_calls
            except Exception as e:
                print(f"[!] Warning reading baseline: {e}")

        report = {
            "test_name": f"alpine_virtio_copy_{mode_key}",
            "mode": mode_key,
            "description": cfg["description"],
            "tracing_enabled": cfg["enable_trace"],
            "vm_configuration": {
                "vcpus": 2,
                "ram": "2G",
                "disk": disk_path,
                "iso": ISO_PATH,
                "qemu_binary": QEMU_BIN
            },
            "workload": {
                "description": "Sequential copy of 256MB file from RAM (/tmp/benchfile.dat) to VirtIO disk (/mnt/bench/target.dat) followed by sync",
                "file_size_bytes": 268435456,
                "file_size_mb": 256
            },
            "execution_time": {
                "guest_real_sec": real_time,
                "guest_user_sec": user_time,
                "guest_sys_sec": sys_time,
                "host_elapsed_sec": round(host_elapsed, 4)
            },
            "virtio_notify_metrics": {
                "tracing_enabled": cfg["enable_trace"],
                "total_events_captured": total_trace_lines,
                "virtio_queue_notify": {
                    "total_calls": notify_calls,
                    "calls_by_queue_index": notify_queue_counts,
                    "counter_range": [min(counter_values_notify), max(counter_values_notify)] if counter_values_notify else []
                },
                "virtio_queue_notify_vq": {
                    "total_calls": notify_vq_calls,
                    "calls_by_queue_index": notify_vq_queue_counts,
                    "counter_range": [min(counter_values_notify_vq), max(counter_values_notify_vq)] if counter_values_notify_vq else []
                }
            },
            "overhead_comparison_against_baseline": baseline_comparison
        }

        # Save JSON report
        with open(report_json, "w") as f:
            json.dump(report, f, indent=2)

        # Build text report
        trace_sample_sec = ""
        if copy_trace_lines:
            trace_sample_sec = f"""
Samples of captured trace events:
{chr(10).join('  ' + line for line in copy_trace_lines[:5])}
...
{chr(10).join('  ' + line for line in copy_trace_lines[-5:])}
"""

        overhead_sec = ""
        if baseline_comparison:
            overhead_sec = f"""
--- OVERHEAD COMPARISON VS UNMODIFIED BASELINE ---
Baseline Guest Real Time : {baseline_comparison.get('baseline_guest_real_sec')} s
Current Guest Real Time  : {real_time:.2f} s
Overhead (Delta Real)    : {baseline_comparison.get('delta_guest_real_sec')} s ({baseline_comparison.get('guest_real_overhead_percent')}%)
Overhead (Delta Host)    : {baseline_comparison.get('delta_host_elapsed_sec')} s ({baseline_comparison.get('host_elapsed_overhead_percent')}%)
Baseline Total Calls     : {baseline_comparison.get('baseline_total_calls')}
"""

        report_text = f"""
================================================================================
          VIRTIO BENCHMARK REPORT: {mode_key.upper()}
================================================================================
Target VM: Alpine Linux 3.24 (Kernel 6.18 LTS)
Hardware Config: 2 vCPUs, 2GB RAM, VirtIO Block Device (/dev/vda)
Disk Image: {disk_path}
Tracing: {'ENABLED' if cfg['enable_trace'] else 'DISABLED'}
Workload: 256MB sequential copy (RAM -> VirtIO Disk + sync)

--- EXECUTION TIME MEASUREMENTS ---
Guest 'real' Time : {real_time:.2f} s
Guest 'user' Time : {user_time:.2f} s
Guest 'sys'  Time : {sys_time:.2f} s
Host Elapsed Time : {host_elapsed:.4f} s
{overhead_sec}
--- VIRTIO QUEUE NOTIFICATION METRICS ---
Total Events Captured               : {total_trace_lines}
virtio_queue_notify calls           : {notify_calls} (Queues: {notify_queue_counts})
  Static Counter Range              : {report['virtio_notify_metrics']['virtio_queue_notify']['counter_range']}
virtio_queue_notify_vq calls        : {notify_vq_calls} (Queues: {notify_vq_queue_counts})
  Static Counter Range              : {report['virtio_notify_metrics']['virtio_queue_notify_vq']['counter_range']}
{trace_sample_sec}
================================================================================
"""
        with open(report_txt, "w") as f:
            f.write(report_text)

        print(report_text)

        # 9. Clean shutdown
        print("[*] Shutting down VM cleanly...")
        child.sendline("poweroff")
        try:
            child.expect(pexpect.EOF, timeout=20)
        except Exception:
            pass

        print(f"\n[+] Benchmark ({mode_key}) finished successfully!")
        print(f"[+] Saved reports to:")
        print(f"    - {report_txt}")
        print(f"    - {report_json}")
        if trace_log:
            print(f"    - {trace_log}")

    except Exception as e:
        print(f"[!] Error during execution: {e}")
        import traceback
        traceback.print_exc()
    finally:
        child.close(force=True)

if __name__ == "__main__":
    main()
