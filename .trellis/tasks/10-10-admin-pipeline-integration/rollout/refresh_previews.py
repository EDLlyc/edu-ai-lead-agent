import json
import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

root = Path("/tmp/edu-admin-pipeline-integration")
repo = Path(
    "/root/projects/edu-ai-lead-agent/.trellis/worktrees/admin-pipeline-20261010"
)
assert (
    json.loads((root / "frontend-result.json").read_text())["result"]
    == "FRONTEND_INSTALLED"
)
services = [
    (267433, 5180, 18100, "dist-admin", "/tmp/edu-admin-history-release/dist-admin"),
    (258609, 5181, 18103, "dist-demo", "/tmp/edu-admin-history-preview/dist-admin"),
]
metadata = {
    "tunnel_pid": 267426,
    "mock_pid": 248218,
    "source_commit": "f062b8221c387ecd44d6e7529832f50331d1508d",
    "previews": {},
}
assert "ssh -N " in Path("/proc/267426/cmdline").read_text().replace("\0", " ")
for pid, port, api, out, previous in services:
    command = Path(f"/proc/{pid}/cmdline").read_text().replace("\0", " ")
    assert (
        "vite.js preview --mode admin" in command
        and f"--port {port} " in command
        and previous in command
    )
    os.kill(pid, signal.SIGTERM)
    for _ in range(100):
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
        except FileNotFoundError:
            break
        if stat.split()[2] == "Z":
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("preview_shutdown_failed")
    env = os.environ.copy()
    env["VITE_API_BASE_URL"] = f"http://127.0.0.1:{api}"
    with (root / f"preview-{port}.log").open("ab") as log:
        process = subprocess.Popen(
            [
                "node",
                str(repo / "frontend/node_modules/vite/bin/vite.js"),
                "preview",
                "--mode",
                "admin",
                "--outDir",
                str(root / out),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--strictPort",
            ],
            cwd=repo / "frontend",
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("preview_start_failed")
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/admin/", timeout=1
            ) as r:
                assert r.status == 200
            break
        except OSError:
            time.sleep(0.1)
    else:
        raise RuntimeError("preview_not_ready")
    metadata["previews"][str(port)] = {
        "pid": process.pid,
        "url": f"http://127.0.0.1:{port}/admin/",
        "out_dir": str(root / out),
        "api_port": api,
    }
(root / "processes.json").write_text(json.dumps(metadata, indent=2) + "\n")
production = {
    "tunnel_pid": 267426,
    "frontend_pid": metadata["previews"]["5180"]["pid"],
    "url": metadata["previews"]["5180"]["url"],
    "out_dir": metadata["previews"]["5180"]["out_dir"],
    "source_commit": metadata["source_commit"],
}
Path("/tmp/edu-admin-history-release/processes.json").write_text(
    json.dumps(production, indent=2) + "\n"
)
demo = {
    "mock": 248218,
    "preview": metadata["previews"]["5181"]["pid"],
    "source_commit": metadata["source_commit"],
}
Path("/tmp/edu-admin-history-preview/processes.json").write_text(
    json.dumps(demo, indent=2) + "\n"
)
# The validation-only preview is no longer needed after both stable addresses are refreshed.
p = Path("/proc/303081/cmdline")
if p.exists():
    command = p.read_text().replace("\0", " ")
    assert "--port 5182 " in command and str(root / "dist-demo") in command
    os.kill(303081, signal.SIGTERM)
print(json.dumps(metadata))
