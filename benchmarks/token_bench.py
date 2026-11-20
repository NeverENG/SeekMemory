"""Compare full history with short history plus recall using e2e.py fixtures."""
import argparse
import importlib.util
import json
import shutil
from pathlib import Path
from urllib.request import Request, urlopen


def measure(bench, question, instructions="", history=""):
    messages = []
    if instructions:
        messages.append({"role": "system", "content": instructions})
    messages.append({"role": "user", "content": history + question})
    body = dict(model=bench.MODEL, messages=messages, max_tokens=48,
                temperature=0, thinking={"type": "disabled"})
    request = Request(bench.URL, json.dumps(body).encode(), {
        "Content-Type": "application/json", "Authorization": "Bearer " + bench.KEY,
    })
    with urlopen(request, timeout=45) as response:
        result = json.load(response)
    return result["usage"], result["choices"][0]["message"].get("content") or ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", type=Path)
    parser.add_argument("--limit", type=int, default=9)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("fixture", args.repo / "benchmarks/e2e.py")
    bench = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench)
    bench.MSGS = bench.gen_messages()
    tmp, db, bench.CACHE, bench.GRAPH = bench.ingest(bench.MSGS)
    bench.OWNER = [a for a in bench.CACHE.active() if a.header.scope != "shadow"]
    # The private u0 transcript includes its paired bot replies.
    private = [m for m in bench.MSGS if m["ch"] == "private"]
    transcript = [
        f"{m['uid']}: {m['text']}" for i, m in enumerate(private)
        if m["uid"] == "u0" or (m["uid"] == "bot" and i > 0 and private[i-1]["uid"] == "u0")
    ]
    _, style_only = bench.SYSTEM.split("。", 1)
    def history(lines):
        return "【对话历史】\n" + "\n".join(lines) + "\n\n【当前问题】\n"

    try:
        for question, expected in bench.QUESTIONS[:args.limit]:
            memory = bench.seek_pick(question)[0]
            variants = {
                "question": ("", ""),
                "system": (style_only, ""),
                "persona": (bench.SYSTEM, ""),
                "full": (bench.SYSTEM, history(transcript)),
                "short": (bench.SYSTEM, history(transcript[-24:])),
                "recall": (bench.SYSTEM + "\n\n【你记得的事】\n" + memory, history(transcript[-24:])),
            }
            row = {}
            for label, (instructions, context) in variants.items():
                usage, answer = measure(bench, question, instructions, context)
                row[label] = {"usage": usage, "hit": any(k.casefold() in answer.casefold() for k in expected)}
            print(json.dumps({"query": question, **row}, ensure_ascii=False), flush=True)
    finally:
        db.close()
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()

