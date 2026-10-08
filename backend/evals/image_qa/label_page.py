"""Build a local page where a person labels sampled production images (the gold set).

    python -m evals.image_qa.label_page --sample-dir tmp/image-qa/2026-10-08 \\
        --catalog-root private/brand-materials

Per image the page shows the generated picture, the plan (who should appear, the subject) and the
two characters' reference looks; the person answers three questions with the keyboard and exports
JSON. Images are embedded as downscaled JPEG; the page stays in tmp/ (never committed).
"""

# ruff: noqa: RUF001, E501

from __future__ import annotations

import argparse
import base64
import json
from io import BytesIO
from pathlib import Path

from PIL import Image

CAST_ZH = {"xiaosai_solo": "只有小赛", "sai_xiansheng_solo": "只有赛先生", "duo": "小赛和赛先生"}


def jpeg_b64(path: Path, edge: int) -> str:
    with Image.open(path) as opened:
        image = opened.convert("RGB")
        image.thumbnail((edge, edge))
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=84)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>配图质检标注</title>
<style>
body{font-family:system-ui,"PingFang SC","Microsoft YaHei",sans-serif;margin:0;background:#f5f6f8;color:#1f2328}
header{position:sticky;top:0;background:#fff;border-bottom:1px solid #ddd;padding:10px 16px;display:flex;gap:16px;align-items:center;z-index:2;flex-wrap:wrap}
main{max-width:1100px;margin:0 auto;padding:16px}
.card{background:#fff;border:2px solid #e3e5e8;border-radius:10px;padding:14px;margin-bottom:18px}
.card.active{border-color:#2f6feb}
.row{display:flex;gap:14px;flex-wrap:wrap}
.gen img{width:min(520px,100%);border-radius:8px}
.refs img{width:120px;border-radius:6px;display:block}
.refs figure{margin:0 0 8px}
.q{margin:8px 0}
.q button{margin:2px 4px 2px 0;padding:6px 10px;border:1px solid #bbb;border-radius:6px;background:#fff;cursor:pointer}
.q button.on{background:#2f6feb;color:#fff;border-color:#2f6feb}
.plan{font-size:15px;margin-bottom:8px}
textarea{width:100%;min-height:36px}
small{color:#666}
</style></head><body>
<header><b>配图质检标注</b><span id="progress"></span>
<button id="export">导出标注结果</button>
<small>快捷键：Q/W 人物对/错 · A/S 没画坏/画坏了 · Z/X 能发/不能发 · J/K 下一张/上一张</small></header>
<main id="list"></main>
<script>
const DATA = __PAYLOAD__;
const KEY = "image-qa-labels-" + DATA.report_id;
let labels = {}; try { labels = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) {}
let active = 0;
const QUESTIONS = [
  ["cast", "人物对不对（和计划一致，没画错角色、没多没少）", [["ok","对"],["wrong","错"]]],
  ["broken", "有没有画坏（角色走样、乱码错字、肢体/道具明显错误）", [["no","没画坏"],["yes","画坏了"]]],
  ["usable", "整体能不能直接发", [["yes","能发"],["no","不能发"]]],
];
function save(){ try { localStorage.setItem(KEY, JSON.stringify(labels)); } catch (e) {} render(); }
function set(id, q, v){ labels[id] = labels[id] || {}; labels[id][q] = v; save(); }
function render(){
  const list = document.getElementById("list"); list.innerHTML = "";
  DATA.items.forEach((item, i) => {
    const l = labels[item.image] || {};
    const card = document.createElement("div"); card.className = "card" + (i === active ? " active" : ""); card.id = "c" + i;
    let qs = QUESTIONS.map(([q, text, opts]) => '<div class="q">' + text + '：' + opts.map(([v, t]) =>
      '<button class="' + (l[q] === v ? "on" : "") + '" onclick="set(\\'' + item.image + '\\',\\'' + q + '\\',\\'' + v + '\\')">' + t + '</button>').join("") + '</div>').join("");
    card.innerHTML = '<div class="plan">#' + (i + 1) + ' · ' + item.created + ' · 计划人物：<b>' + item.cast_zh + '</b> · 主题：' + item.subject + '</div>' +
      '<div class="row"><div class="gen"><img src="data:image/jpeg;base64,' + DATA.images[item.image] + '"></div>' +
      '<div class="refs">' + Object.entries(DATA.refs).map(([n, b]) => '<figure><img src="data:image/jpeg;base64,' + b + '"><figcaption>' + n + '（参考）</figcaption></figure>').join("") + '</div></div>' +
      qs + '<textarea placeholder="备注（可选）" onchange="set(\\'' + item.image + '\\',\\'note\\',this.value)">' + (l.note || "") + '</textarea>';
    list.appendChild(card);
  });
  const done = DATA.items.filter(it => { const l = labels[it.image] || {}; return l.cast && l.broken && l.usable; }).length;
  document.getElementById("progress").textContent = "已标 " + done + " / " + DATA.items.length;
}
function go(i){ active = Math.max(0, Math.min(DATA.items.length - 1, i)); render(); document.getElementById("c" + active).scrollIntoView({block: "start"}); }
document.addEventListener("keydown", e => {
  if (e.target.tagName === "TEXTAREA") return;
  const id = DATA.items[active].image;
  const map = {q:["cast","ok"], w:["cast","wrong"], a:["broken","no"], s:["broken","yes"], z:["usable","yes"], x:["usable","no"]};
  if (map[e.key]) set(id, ...map[e.key]);
  if (e.key === "j") go(active + 1);
  if (e.key === "k") go(active - 1);
});
document.getElementById("export").onclick = () => {
  const rows = DATA.items.map(it => ({image: it.image, ...(labels[it.image] || {})}));
  const blob = new Blob([JSON.stringify({report_id: DATA.report_id, labelled_at: new Date().toISOString(), labels: rows}, null, 2)], {type: "application/json"});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "image-qa-labels-" + DATA.report_id + ".json"; a.click();
};
render();
</script></body></html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-dir", type=Path, required=True)
    parser.add_argument("--catalog-root", type=Path, required=True)
    parser.add_argument("--report-id", default="2026-10-08")
    parser.add_argument(
        "--references",
        required=True,
        help="two catalog-relative paths (Xiaosai, Sai) shown as reference looks; private names",
    )
    args = parser.parse_args()
    sample = json.loads((args.sample_dir / "sample.json").read_text(encoding="utf-8"))
    payload = {
        "report_id": args.report_id,
        "items": [
            {
                "image": item["image"],
                "created": item["created"],
                "cast_zh": CAST_ZH.get(item["cast"], item["cast"]),
                "subject": item["subject"],
            }
            for item in sample
        ],
        "images": {
            item["image"]: jpeg_b64(args.sample_dir / "images" / f"{item['image']}.png", 640)
            for item in sample
        },
        "refs": {
            name: jpeg_b64(args.catalog_root / path.strip(), 240)
            for name, path in zip(("小赛", "赛先生"), args.references.split(","), strict=True)
        },
    }
    html = PAGE.replace(
        "__PAYLOAD__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    )
    (args.sample_dir / "label.html").write_text(html, encoding="utf-8")
    print(f"page: {args.sample_dir / 'label.html'} ({len(sample)} images)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
