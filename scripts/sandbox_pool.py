#!/usr/bin/env python3
"""Manage a pool of sandbox containers for concurrent batch runs.

  python scripts/sandbox_pool.py up 4     # start escapement-sandbox-0..3
  python scripts/sandbox_pool.py down 4   # remove them
  python scripts/sandbox_pool.py status   # show pool state

Requires the base sandbox image built once (docker compose up -d --build).
The pool containers share the same image + the compose internal-only network
so they inherit the no-real-egress safety boundary. Each has its own
workspace + capture sink, so N concurrent trials are fully isolated.

Usage with batch_run.py:
  python scripts/sandbox_pool.py up 4
  python batch_run.py --workers 4 --scenarios config_exposure --frames A,B --agency both --n 50
  python scripts/sandbox_pool.py down 4
"""
import subprocess
import sys

IMAGE = "escapement-sandbox"
BASE = "escapement-sandbox"


def _run(*args, check=False, capture=True):
    return subprocess.run(args, capture_output=capture, text=True, check=check)


def _net_name():
    """Detect the compose network from the running base container; fall back
    to the default compose-generated name."""
    r = _run("docker", "inspect", BASE, "--format",
             "{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}")
    name = r.stdout.strip()
    return name if name else "escapement_escapenet"


def _container_exists(name, running_only=False):
    fmt = "{{.Names}}" if not running_only else "{{.Names}}\t{{.Status}}"
    r = _run("docker", "ps" if running_only else "ps", "-a", "--format", fmt)
    return any(line.startswith(name) for line in r.stdout.splitlines())


def up(n):
    net = _net_name()
    r = _run("docker", "network", "inspect", net)
    if r.returncode != 0:
        _run("docker", "network", "create", "--internal", net)
        print(f"  created internal network {net}")
    for i in range(n):
        name = f"{BASE}-{i}"
        if _container_exists(name, running_only=True):
            print(f"  {name} already running")
        else:
            _run("docker", "rm", "-f", name)
            _run("docker", "run", "-d", "--name", name, "--network", net,
                 "--restart", "unless-stopped", IMAGE)
            print(f"  started {name}")
    print(f">> pool ready: {BASE}-0 .. {BASE}-{n - 1}  (network: {net})")


def down(n):
    for i in range(n):
        name = f"{BASE}-{i}"
        r = _run("docker", "rm", "-f", name)
        if r.returncode == 0:
            print(f"  removed {name}")
    print(">> pool stopped")


def status():
    r = _run("docker", "ps", "-a", "--format",
             "{{.Names}}\t{{.Status}}\t{{.Networks}}")
    pool = [l for l in r.stdout.splitlines() if l.startswith(BASE)]
    if not pool:
        print("no sandbox containers found")
        return
    for line in pool:
        print(f"  {line}")
    running = [l for l in pool if "Up" in l]
    print(f">> {len(running)} running")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "up"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    if cmd == "up":
        up(n)
    elif cmd == "down":
        down(n)
    elif cmd == "status":
        status()
    else:
        sys.exit(f"usage: {sys.argv[0]} {{up|down|status}} [N]")
