"""Nine isolated HTTP/SQLite checks; all data and the kernel stay under --run-dir."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from store import Store  # noqa: E402
from services.persona_proposals import sentence_diff  # noqa: E402

SUBJECT = "synthetic:FriendMessage:424242"
WRONG = "synthetic:FriendMessage:999999"
BLOCKED = {62058, 62119, 3100, 3000, 3001}


def check(condition, label):
    if not condition:
        raise AssertionError(label)


def reserve_port():
    for port in range(62477, 62520):
        if port in BLOCKED:
            continue
        probe = socket.socket()
        try:
            probe.bind(("127.0.0.1", port))
            return port
        except OSError:
            pass
        finally:
            probe.close()
    raise RuntimeError("no isolated port available")


def request(port, token, method, path, body=None):
    url = f"http://127.0.0.1:{port}{path}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {token}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, json.loads(raw) if raw else {}


def sql(path, statement, params=()):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(statement, params).fetchall()
    finally:
        conn.close()


def create_proposal(db_path, current_text, new_text, reason):
    store = Store(str(db_path))
    try:
        row = store.conn.execute(
            "SELECT id,revision FROM nodes WHERE family='persona' AND state='active' "
            "ORDER BY revision DESC LIMIT 1"
        ).fetchone()
        check(row is not None, "no synthetic persona")
        return store.persona_proposals.create(
            subject_key=SUBJECT, persona_id=row["id"], base_revision=row["revision"],
            old_text=current_text, new_text=new_text,
            diff=sentence_diff(current_text, new_text), reason=reason,
        )
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run = Path(args.run_dir).resolve()
    run.mkdir(parents=True, exist_ok=False)
    data_dir = run / "data"
    data_dir.mkdir()
    config = run / "config.json"
    config.write_text(json.dumps({"owner_umo": SUBJECT, "persona_min_interval_s": 0}),
                      encoding="utf-8")
    token = secrets.token_urlsafe(32)
    port = reserve_port()
    check(port not in BLOCKED, "forbidden port")
    command = [sys.executable, "-B", str(ROOT / "scripts" / "serve.py"),
               "--data-dir", str(data_dir), "--port", str(port),
               "--token", token, "--config", str(config), "--quiet"]
    output = (run / "kernel.stdout.log").open("w", encoding="utf-8")
    errors = (run / "kernel.stderr.log").open("w", encoding="utf-8")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(command, cwd=ROOT, stdout=output, stderr=errors,
                            creationflags=flags)
    db = data_dir / "memory.db"
    summary = []
    def record(number, name, **details):
        item = {"scenario": number, "name": name, "passed": True, **details}
        summary.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    def get_persona():
        code, body = request(port, token, "GET", "/persona?subject_key=" +
                             urllib.parse.quote(SUBJECT))
        check(code == 200, f"GET persona {code}")
        return body
    def pending():
        code, body = request(port, token, "GET", "/persona/proposals?subject_key=" +
                             urllib.parse.quote(SUBJECT))
        check(code == 200, f"GET proposals {code}")
        return body["proposals"]
    def post(path, body):
        return request(port, token, "POST", path, body)
    def approve(proposal_id):
        return post(f"/persona/proposals/{proposal_id}/approve",
                    {"subject_key": SUBJECT, "actor": "self", "confirmed": True})
    def make(text, reason):
        return create_proposal(db, get_persona()["text"], text, reason)
    def audit():
        path = data_dir / "persona-writes.log"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []
    try:
        deadline = time.monotonic() + 15
        while not (data_dir / "runtime.json").exists() and time.monotonic() < deadline:
            check(proc.poll() is None, "isolated kernel exited during startup")
            time.sleep(0.1)
        check((data_dir / "runtime.json").exists(), "isolated kernel did not start")
        check(json.loads((data_dir / "runtime.json").read_text(encoding="utf-8"))["port"] == port,
              "wrong isolated port")
        print(json.dumps({"server_command": [*command[:8], "<generated-token>", *command[9:]],
                          "port": port, "data_dir": str(data_dir)}, ensure_ascii=False), flush=True)

        # Synthetic seed is an explicit direct write.  All subsequent messages are fabricated.
        code, seeded = post("/persona", {"subject_key": SUBJECT,
                                        "text": "我是测试人格。\n我会回应。", "note": "synthetic seed"})
        check(code == 200 and seeded["revision"] == 1, f"seed {code} {seeded}")
        before = get_persona()
        before_hash = hashlib.sha256(before["text"].encode()).hexdigest()
        for n in range(1, 4):
            code, user = post("/capture", {"subject_key": SUBJECT, "role": "user",
                                             "text": f"合成消息{n}：我有些难过。", "msg_id": f"synthetic-u-{n}"})
            check(code == 200, f"capture user {n}: {code}")
            code, bot = post("/capture", {"subject_key": SUBJECT, "role": "assistant",
                                            "text": "我先接住你的情绪。", "msg_id": f"synthetic-a-{n}",
                                            "reply_to": user["source_id"]})
            check(code == 200, f"capture assistant {n}: {code}")
            code, task = request(port, token, "GET", "/extract/plan?subject_key=" +
                                 urllib.parse.quote(SUBJECT))
            check(code == 200 and len(task["source_ids"]) == 2,
                  f"extract plan {n}: {code} {task}")
            item = {"level": "scene", "text": f"合成观察{n}：先回应情绪", "tags": "synthetic",
                    "about": "relation", "subject_kind": "self", "subject_id": "self",
                    "event_at": "2026-11-01T10:00:00", "confidence": 0.95,
                    "arousal": 0.2, "valence": 0, "funny": False, "first": True,
                    "bot_behavior": "respond_emotion", "bot_action": "我先接住你的情绪。",
                    "evidence_source_ids": [user["source_id"], bot["source_id"]]}
            code, committed = post("/extract/commit", {"task_id": task["task_id"],
                                                       "source_ids": task["source_ids"],
                                                       "chat_response": {"text": json.dumps([item], ensure_ascii=False)}})
            check(code == 200 and committed["written"] == 1, f"extract commit {n}: {code} {committed}")
        first = pending()
        after = get_persona()
        check(len(first) == 1 and first[0]["status"] == "pending", "automatic proposal absent")
        check(after["revision"] == before["revision"] and hashlib.sha256(after["text"].encode()).hexdigest() == before_hash,
              "automatic evolution changed persona")
        check(bool(first[0]["diff"]) and all(set(p) == {"old", "new"} for p in first[0]["diff"]), "sentence diff absent")
        auto_id = first[0]["id"]
        record(1, "auto_proposal_no_write", http=200, revision=after["revision"],
               sha256=before_hash, sql_pending=sql(db, "SELECT count(*) FROM persona_proposals WHERE status='pending'")[0][0],
               proposal_id=auto_id)

        audit_before = len(audit())
        code, missing_confirm = post(f"/persona/proposals/{auto_id}/approve",
                                     {"subject_key": SUBJECT, "actor": "self"})
        check(code == 400 and get_persona()["revision"] == before["revision"], "approval confirmation bypass")
        code, approved = approve(auto_id)
        current = get_persona()
        check(code == 200 and current["revision"] == before["revision"] + 1 and
              current["text"] == first[0]["new_text"] and len(audit()) == audit_before + 1,
              f"approve failed {code} {approved}")
        check(sql(db, "SELECT status,approved_revision FROM persona_proposals WHERE id=?", (auto_id,))[0] ==
              ("approved", current["revision"]), "approval SQL state")
        record(2, "approve_revision_audit", http=code, revision=current["revision"],
               audit_delta=1, pre_confirm_http=400, sql_status="approved")

        rejected = make(current["text"] + "\n拒绝候选。", "synthetic reject")
        revision = current["revision"]
        code, response = post(f"/persona/proposals/{rejected['id']}/reject",
                              {"subject_key": SUBJECT, "actor": "self", "confirmed": True})
        check(code == 200 and get_persona()["revision"] == revision and
              sql(db, "SELECT status FROM persona_proposals WHERE id=?", (rejected["id"],))[0][0] == "rejected",
              f"reject failed {code} {response}")
        record(3, "reject_no_write", http=code, revision=revision, sql_status="rejected")

        original = get_persona()["text"]
        revised = make(original + "\n原提案。", "synthetic revise")
        own_words = original + "\n这是我改后的说法。"
        code, changed = post(f"/persona/proposals/{revised['id']}/revise",
                             {"subject_key": SUBJECT, "new_text": own_words})
        check(code == 200 and get_persona()["revision"] == revision and
              sql(db, "SELECT status,new_text FROM persona_proposals WHERE id=?", (revised["id"],))[0] ==
              ("pending", own_words), f"revise failed {code} {changed}")
        code, response = approve(revised["id"])
        current = get_persona()
        check(code == 200 and current["text"] == own_words and current["revision"] == revision + 1,
              f"revised approval failed {code} {response}")
        record(4, "revise_then_approve_own_words", revise_http=200, approve_http=code,
               revision=current["revision"], sql_new_text=own_words)
        # Supplemental regression: the approved behavior sentence must not be
        # appended again while it remains in her current authored text.
        from store.cache import Cache
        from services.persona_proposals import propose_self_persona
        probe = Store(str(db))
        try:
            cache = Cache(probe.artifacts)
            cache.load()
            duplicate = propose_self_persona(
                probe.persona_proposals, SUBJECT, probe.sources, cache,
            )
            check(duplicate is None and get_persona()["revision"] == current["revision"],
                  "approved behavior was reproposed")
        finally:
            probe.close()
        print(json.dumps({"post_approval_repeat": "PASS", "new_proposals": 0},
                         ensure_ascii=False), flush=True)

        expiring = make(current["text"] + "\n过期候选。", "synthetic expiry")
        conn = sqlite3.connect(db)
        try:
            conn.execute("UPDATE persona_proposals SET expires_at=? WHERE id=?",
                         ("2000-01-01T00:00:00+00:00", expiring["id"]))
            conn.commit()
        finally:
            conn.close()
        revision = current["revision"]
        code, response = approve(expiring["id"])
        check(code == 410 and get_persona()["revision"] == revision and
              sql(db, "SELECT status FROM persona_proposals WHERE id=?", (expiring["id"],))[0][0] == "expired",
              f"expired approval failed {code} {response}")
        record(5, "expired_never_commits", http=code, revision=revision, sql_status="expired")

        audit_before = len(audit())
        code, response = approve(revised["id"])
        check(code == 409 and response.get("error") == "already_approved" and
              get_persona()["revision"] == revision and len(audit()) == audit_before,
              "duplicate approve mutated data")
        record(6, "duplicate_approve_idempotent", http=code, revision=revision,
               audit_delta=0, error=response["error"])

        wrong_target = make(current["text"] + "\n待权限验证。", "synthetic auth")
        wrong_cases = [
            request(port, token, "GET", "/persona/proposals?subject_key=" + urllib.parse.quote(WRONG)),
            post(f"/persona/proposals/{wrong_target['id']}/approve",
                 {"subject_key": WRONG, "actor": "self", "confirmed": True}),
            post(f"/persona/proposals/{wrong_target['id']}/reject",
                 {"subject_key": WRONG, "actor": "self", "confirmed": True}),
            post(f"/persona/proposals/{wrong_target['id']}/revise",
                 {"subject_key": WRONG, "new_text": "错误主体"}),
        ]
        check(all(code == 403 and body.get("error") == "subject_mismatch"
                  for code, body in wrong_cases), f"subject guard failed: {wrong_cases}")
        check(get_persona()["revision"] == revision and
              sql(db, "SELECT status FROM persona_proposals WHERE id=?", (wrong_target["id"],))[0][0] == "pending",
              "subject guard mutated proposal")
        record(7, "all_new_routes_wrong_subject", http_codes=[code for code, _ in wrong_cases],
               revision=revision, sql_status="pending")

        direct_text = "这是我直接写的人格。\n直写权保留。"
        audit_before = len(audit())
        code, response = post("/persona", {"subject_key": SUBJECT, "text": direct_text,
                                                  "note": "direct-self-test"})
        current = get_persona()
        check(code == 200 and current["revision"] == revision + 1 and
              current["text"] == direct_text and len(audit()) == audit_before + 1 and
              audit()[-1]["note"] == "direct-self-test", f"direct write failed {code} {response}")
        record(8, "direct_persona_write_kept", http=code, revision=current["revision"],
               audit_note=audit()[-1]["note"])

        final = make(current["text"] + "\n我明确批准这句。", "synthetic provenance")
        audit_before = len(audit())
        code, response = approve(final["id"])
        end = get_persona()
        history_code, history = request(port, token, "GET", "/persona/proposals?subject_key=" +
                                        urllib.parse.quote(SUBJECT) + "&status=approved")
        approved_rows = [row for row in history["proposals"] if row["id"] == final["id"]]
        check(code == 200 and history_code == 200 and len(approved_rows) == 1 and
              approved_rows[0]["status"] == "approved" and
              f"proposal:{final['id']}" in audit()[-1]["note"] and
              end["revision"] == current["revision"] + 1 and len(audit()) == audit_before + 1,
              "proposal provenance failed")
        record(9, "approve_audit_marker_and_history", approve_http=code,
               list_http=history_code, revision=end["revision"],
               sql_status=sql(db, "SELECT status FROM persona_proposals WHERE id=?", (final["id"],))[0][0],
               audit_note=audit()[-1]["note"])
        print(json.dumps({"summary": "9/9 PASS", "synthetic_only": True,
                          "data_dir": str(data_dir)}, ensure_ascii=False), flush=True)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=8)
        output.close()
        errors.close()
        closed = False
        for _ in range(20):
            probe = socket.socket()
            try:
                probe.settimeout(0.2)
                closed = probe.connect_ex(("127.0.0.1", port)) != 0
            finally:
                probe.close()
            if closed:
                break
            time.sleep(0.1)
        print(json.dumps({"isolated_kernel_exit": proc.returncode,
                          "isolated_port": port, "port_closed": closed}, ensure_ascii=False), flush=True)
        check(closed, "isolated port still listening")


if __name__ == "__main__":
    main()
