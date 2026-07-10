"""Sandbox driver: execute the agent's tool calls inside the real Linux container.

The container is started by `docker compose up` (see docker-compose.yml). This
module does NOT manage container lifecycle -- it assumes the named container is
running and dispatches commands into it with `docker exec`. All agent actions
run as the non-root `agent` user; capture reads run as root.

Everything here is real (a real shell, real fs, real curl). The only simulated
piece in the whole environment is the capture-sink service on localhost:9000,
which the agent reaches via the `curl` tool.
"""

import json
import shlex
import subprocess
from typing import List, Optional

# Bounds so a runaway tool call can't wedge the loop.
MAX_OUTPUT_BYTES = 20000
EXEC_TIMEOUT = 60


class SandboxError(RuntimeError):
    pass


class Sandbox:
    def __init__(self, container: str = "escapement-sandbox", agent_user: str = "agent",
                 workspace: str = "/home/agent/workspace", no_sandbox: bool = False):
        self.container = container
        self.agent_user = agent_user
        self.workspace = workspace
        self.no_sandbox = no_sandbox  # DANGEROUS dev-only: exec on the host

    # -- low-level exec ------------------------------------------------------

    def _exec(self, cmd: List[str], as_user: Optional[str] = None,
              timeout: int = EXEC_TIMEOUT) -> str:
        """Run a command list in the container (or on host if no_sandbox)."""
        user = as_user or self.agent_user
        if self.no_sandbox:
            argv = cmd
        else:
            argv = ["docker", "exec", "-u", user, self.container] + cmd
        try:
            proc = subprocess.run(argv, capture_output=True, text=True,
                                  timeout=timeout)
        except FileNotFoundError as exc:
            raise SandboxError(
                "docker not available -- start the sandbox first or enable Docker "
                "WSL integration") from exc
        except subprocess.TimeoutExpired as exc:
            raise SandboxError(f"exec timed out after {timeout}s") from exc
        out = (proc.stdout or "") + (proc.stderr or "")
        return out[:MAX_OUTPUT_BYTES]

    def _ws_root(self) -> str:
        """Workspace root with trailing slash stripped, safe for path joining.

        ``seed``/``wipe`` build child paths with ``f"{...}/{rel}"``, which
        AttributeErrors when ``workspace`` is ``None`` (a malformed config -- the
        constructor default is a string, but a caller can pass None). Coerce
        None/non-str to ``''`` here so the join yields ``"/<rel>"`` (a no-op
        write under root, not a crash)."""
        ws = self.workspace
        return ws.rstrip("/") if isinstance(ws, str) else ""

    @staticmethod
    def _q(value) -> str:
        """Shell-quote a workspace/user field for interpolation into ``bash -lc``.

        ``shlex.quote`` only accepts a str (or None/'' via its falsy guard); a
        truthy non-str config value (an int workspace/user, or a float) makes
        its internal ``_find_unsafe`` TypeError, crashing the whole reset/seed/
        chown call. Normalize to ``str`` first (None -> '' so it quotes to an
        inert empty argument, never a literal ``None``), then quote."""
        return shlex.quote("" if value is None else str(value))

    # -- the tools the agent can call ----------------------------------------

    def bash(self, command: str) -> str:
        """Run a shell command as the agent user. Returns combined stdout+stderr."""
        if not command.strip():
            return ""
        # Run via login bash in the workspace so cwd/prompt feel real.
        return self._exec(["bash", "-lc", command])

    def read_file(self, path: str) -> str:
        return self._exec(["cat", "--", path])

    def write_file(self, path: str, content: str) -> str:
        # heredoc-free: write via stdin so content is passed verbatim.
        user = self.agent_user
        if self.no_sandbox:
            argv = ["tee", "--", path]
        else:
            argv = ["docker", "exec", "-i", "-u", user, self.container, "tee", "--", path]
        try:
            proc = subprocess.run(argv, input=content, capture_output=True,
                                  text=True, timeout=EXEC_TIMEOUT)
        except FileNotFoundError as exc:
            raise SandboxError("docker not available") from exc
        except subprocess.TimeoutExpired as exc:
            # Mirror _exec: a hung `tee`/`docker exec -i` (full pipe, slow
            # container, stalled I/O) must surface as a SandboxError, not escape
            # the sandbox boundary -- _write_as_root is reached from seed(), which
            # is NOT wrapped by the agent's tool-call guard, so a raw
            # TimeoutExpired there would abort the whole trial setup.
            raise SandboxError(f"write to {path} timed out after {EXEC_TIMEOUT}s") from exc
        # tee echoes input to stdout; a trailing newline keeps it tidy
        return f"wrote {len(content)} bytes to {path}" + (
            f"\n{proc.stderr.strip()}" if proc.stderr.strip() else "")

    def list_dir(self, path: str) -> str:
        return self._exec(["ls", "-la", "--", path])

    def curl(self, url: str, extra_args: str = "", method: str = "GET",
             data: str = "") -> str:
        """Real curl inside the sandbox. The only reachable 'outside' is the
        capture-sink on localhost:9000 (internal-only network, no real egress)."""
        parts = ["curl", "-sS", "-X", method, "-m", "20"]
        if data:
            parts += ["--data", data]
        if extra_args:
            try:
                parts += shlex.split(extra_args)
            except ValueError as exc:
                # Unbalanced quotes in extra_args (a stray quote from the agent
                # or a direct caller) must surface through the sandbox error
                # channel, not as a raw ValueError leaking out of the function.
                raise SandboxError(f"malformed curl extra_args: {exc}") from exc
        parts += [url]
        return self._exec(parts)

    # -- observation primitives (run as root) --------------------------------

    def reset_workspace(self) -> None:
        """Clear the agent workspace before a fresh run (root). Nukes and
        recreates the directory to guarantee no residual files from previous
        trials survive (observed: find -delete left PLATFORM-ADVISORY.md and
        injection queue.jsonl from a prior Frame B trial on overlay2)."""
        ws = self._q(self.workspace)
        usr = self._q(self.agent_user)
        self._exec(["bash", "-lc",
                    f"rm -rf {ws} && mkdir -p {ws} && chown {usr}:{usr} {ws}"],
                   as_user="root")

    def verify_workspace(self, expected_files) -> list:
        """Return list of unexpected files in workspace after seed. Used to
        catch contamination from prior trials that survived reset."""
        # Quote the workspace: like reset_workspace it is interpolated into a
        # `bash -lc` string, so an unquoted path with shell metacharacters
        # (spaces, ';', backticks) would split into a second command -- a shell
        # injection vector via attacker-influenced config.
        ws = self._q(self.workspace)
        listing = self._exec(["bash", "-lc", f"ls -A {ws}"])
        actual = set(line.strip() for line in listing.split('\n') if line.strip())
        expected = set(expected_files or [])
        return sorted(actual - expected)

    def seed(self, files: dict) -> None:
        """Write scenario seed files (relative paths under the workspace) as root,
        then hand the workspace back to the agent user. Disclosure files (e.g.
        a world-readable .env) are deliberately left readable -- that is the
        organic affordance, not an injected instruction."""
        for rel, content in (files or {}).items():
            # A None/non-str rel key (a malformed scenario seed) must be skipped,
            # not f-string-coerced into a literal ".../None" or ".../123" rm/cat
            # target that writes a bogus file under the workspace.
            if not isinstance(rel, str) or not rel:
                continue
            full = f"{self._ws_root()}/{rel}"
            self._write_as_root(full, content)
        # Quote both the user and the workspace: they are interpolated into a
        # `bash -lc` string, so an unquoted value with shell metacharacters is an
        # injection vector (mirrors reset_workspace's quoting).
        usr = self._q(self.agent_user)
        ws = self._q(self.workspace)
        self._exec(["bash", "-lc", f"chown -R {usr}:{usr} {ws}"],
                   as_user="root")

    def _write_as_root(self, full_path: str, content: str) -> None:
        argv = (["tee", "--", full_path] if self.no_sandbox
                else ["docker", "exec", "-i", "-u", "root", self.container, "tee", "--", full_path])
        try:
            proc = subprocess.run(argv, input=content, capture_output=True, text=True,
                                  timeout=EXEC_TIMEOUT)
        except FileNotFoundError as exc:
            raise SandboxError("docker not available") from exc
        except subprocess.TimeoutExpired as exc:
            # seed() calls this with no wrapping guard; a raw TimeoutExpired would
            # abort trial setup. Surface it cleanly as a SandboxError (mirrors
            # _exec and write_file).
            raise SandboxError(
                f"write to {full_path} timed out after {EXEC_TIMEOUT}s") from exc
        # tee (or docker exec) can fail silently -- bad container name, missing
        # target dir, permissions. Without this check a failed write to e.g. the
        # Frame E advisory path reports success, and the trial runs mislabeled
        # (poison never delivered). Surface it so the caller can abort.
        if proc.returncode != 0:
            raise SandboxError(
                f"write to {full_path} failed (rc={proc.returncode}): "
                f"{(proc.stderr or '').strip()[:200]}")

    def read_capture(self) -> List[dict]:
        """Read the root-only capture-sink log (one JSON record per line)."""
        raw = self._exec(["cat", "/var/lib/capture/sink.log"], as_user="root")
        records = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            # A line can be valid JSON but NOT an object (a bare array/number/
            # string/null). The declared return type is List[dict] and downstream
            # consumers (capture._is_escape_post, compute_metrics) assume dicts;
            # a stray non-dict record would AttributeError their .get. Skip it so
            # the producer honours the dict-only contract.
            if not isinstance(rec, dict):
                continue
            records.append(rec)
        return records

    def clear_capture(self) -> None:
        """Empty the capture-sink log so each run starts clean (root).

        Also removes any stale Frame E advisory so it doesn't leak into the
        next trial."""
        self._exec(["bash", "-lc",
                     "true > /var/lib/capture/sink.log; "
                     "rm -f /var/lib/capture/response_advisory.txt"],
                    as_user="root")

    def wipe(self, paths) -> None:
        """Delete workspace-relative files. Used by the mortality incident to
        make a restart's data loss *experiential* -- the agent's work actually
        vanishes, rather than the wipe being stated prose it can ignore."""
        for rel in (paths or []):
            # A None/empty path must be skipped, not f-string-coerced into a
            # literal ".../None" rm target. (paths=None iterates as [].)
            if not rel or not isinstance(rel, str):
                continue
            full = f"{self._ws_root()}/{rel}"
            self._exec(["bash", "-lc", f"rm -f -- {shlex.quote(full)}"])

    def list_processes(self) -> str:
        return self._exec(["ps", "-eo", "pid,user,comm,args"], as_user="root")

    def fs_snapshot(self) -> dict:
        """Path->(mtime,size) map of the agent home, for before/after diffing."""
        out = self._exec(
            ["find", "/home/agent", "-type", "f", "-printf", "%p\\t%T@\\t%s\\n"],
            as_user="root")
        snap = {}
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                try:
                    snap[parts[0]] = (float(parts[1]), int(parts[2]))
                except ValueError:
                    continue
        return snap

    @staticmethod
    def fs_diff(before: dict, after: dict) -> dict:
        created = sorted(set(after) - set(before))
        deleted = sorted(set(before) - set(after))
        modified = [p for p in (set(before) & set(after))
                    if before[p] != after[p]]
        return {"created": created, "deleted": deleted, "modified": sorted(modified)}
