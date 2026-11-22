"""Run one study in a new PostgreSQL database, then release its private fixtures."""

import argparse
import hashlib
import os
import socket
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import ADMIN_URL, DB_URL, READ_URL  # noqa: E402

DATASET = "evaluation/datasets/field-holdout-v2.jsonl"
PYTHON = sys.executable


def command(args, env, **kwargs):
    return subprocess.run(args, cwd=ROOT, env=env, **kwargs).returncode


@contextmanager
def database(provider):
    # Generate the identifier here so cleanup can only address this invocation's database.
    name = "paypilot_study_" + uuid.uuid4().hex
    admin = make_url(ADMIN_URL)
    engine = create_engine(admin.set(database="postgres"), isolation_level="AUTOCOMMIT")
    env = dict(os.environ, LLM_PROVIDER=provider, PAYPILOT_RANKER="v0.4")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(ROOT / "backend"), env.get("PYTHONPATH")]))
    for key, url in (
        ("MIGRATION_DATABASE_URL", ADMIN_URL),
        ("PAYMENT_READONLY_DATABASE_URL", READ_URL),
        ("DATABASE_URL", DB_URL),
    ):
        source = make_url(url)
        env[key] = source.set(database=name).render_as_string(hide_password=False)
    with engine.connect() as conn:
        conn.exec_driver_sql(f"CREATE DATABASE {name}")
        try:
            command(
                [PYTHON, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head"], env, check=True
            )
            yield env
        finally:
            conn.exec_driver_sql(f"DROP DATABASE {name}")


def pilot(env):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen()
        fd = sock.fileno()
        with subprocess.Popen(
            [
                PYTHON,
                "-m",
                "uvicorn",
                "app.main:app",
                "--app-dir",
                "backend",
                "--fd",
                str(fd),
                "--no-access-log",
            ],
            cwd=ROOT,
            env=env,
            pass_fds=(fd,),
        ) as api:
            try:
                url = f"http://127.0.0.1:{sock.getsockname()[1]}"
                return command(["node", "frontend/studies/pilot.mjs", url], env)
            finally:
                api.terminate()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", choices=["holdout", "pilot", "scale"])
    parser.add_argument("--provider", choices=["rules", "deepseek"], default="rules")
    args = parser.parse_args()
    if args.study != "holdout" and args.provider != "rules":
        parser.error("pilot and scale use the fixed rules candidate")
    if args.study == "holdout":
        for line in (ROOT / DATASET).with_suffix(".sha256").read_text().splitlines():
            digest, filename = line.split(maxsplit=1)
            if hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() != digest:
                raise ValueError("frozen input or candidate changed: " + filename)
    if args.study == "scale":
        archive = ROOT / "evaluation/results/experiments"
        archive.mkdir(exist_ok=True, parents=True)
        out = Path(tempfile.mkdtemp(prefix="scale-", dir=archive))
        print(out, flush=True)
        status = 0
        for size in (3000, 30000, 300000):
            with database("rules") as env:
                rc = command([PYTHON, "evaluation/scale.py", str(size), str(out)], env)
                status = status or rc
        return status
    with database(args.provider) as env:
        command([PYTHON, "scripts/seed_payments.py"], env, check=True)
        if args.study == "pilot":
            return pilot(env)
        return command([PYTHON, "evaluation/runner.py", "--dataset", DATASET], env)


if __name__ == "__main__":
    raise SystemExit(main())
