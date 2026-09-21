"""快照子进程 worker：读 stdin 一份 request payload，输出 decide() 的规范化 JSON。

进程级隔离保证 brain.Memory 模块单例为干净状态，避免跨 fixture 状态污染。
只往 stdout 写最终 JSON；logging 走 stderr，不干扰快照采集。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "CoreGeek" / "src"))

from agent.brain import decide  # noqa: E402


def main() -> int:
    # 用 buffer 读 bytes 再 utf-8 解码，避免 Windows stdin 默认 GBK 损坏中文 JSON
    raw = sys.stdin.buffer.read().decode("utf-8")
    payload = json.loads(raw)
    resp = decide(payload)
    out = resp.to_dict()
    # 规范化：key 排序、ascii 保留中文、固定缩进 → diff 稳定可复现
    # 直接写字节，避免 Windows stdout 默认 GBK 报 UnicodeEncodeError
    data = json.dumps(out, sort_keys=True, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(data.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
