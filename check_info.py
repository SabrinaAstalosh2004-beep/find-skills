"""Checks for add_info.py: the map is untouched apart from the metro caption; blocks hold the exact texts."""
import json
import re
import sys

import cv2
import numpy as np
from PIL import Image

MAP, APPROVED, OUT = sys.argv[1:4]  # original map, approved PNG, result
o = np.asarray(Image.open(MAP).convert("RGB")).astype(int)
a = np.asarray(Image.open(APPROVED).convert("RGB")).astype(int)
r = np.asarray(Image.open(OUT).convert("RGB")).astype(int)
mask = np.load(OUT + ".info_mask.npy")
meta = json.load(open(OUT + ".info.json"))
ok = True


def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + (f"  [{info}]" if info else ""))


H, W = a.shape[:2]
check("width kept, blocks appended below the map", r.shape[1] == W and r.shape[0] > H, f"{W}x{H} -> {r.shape[1]}x{r.shape[0]}")
top = r[:H]
diff = np.any(top != a, -1)
check("map pixels unchanged except the metro caption", not (diff & ~mask).any(), f"changed {diff.sum()} px")
added = np.any(a != o, -1)
check("caption covers no route, sign, logo or arrow", not (mask & added).any(), f"{(mask & added).sum()} px")
ink = cv2.dilate(((o.max(-1) < 175) & (np.abs(o[..., 0] - o[..., 2]) < 25)).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
check("caption covers no map text or icon", not (mask & ink).any(), f"{(mask & ink).sum()} px")
cb = meta["caption_bbox"]
check("caption next to the metro logo (logo box 618-753, 1347-1510)", 753 < cb[0] < 775 and 1347 < cb[1] and cb[3] < 1510, f"caption box {cb}")
check("blocks lie entirely below the map", all(c[1] >= H for c in meta["cards"]), f"cards {meta['cards']}")

src = open(sys.argv[0].replace("check_info.py", "add_info.py"), encoding="utf-8").read()
EXPECTED = [
    "(10 минут пешком)", "КАК ДОБРАТЬСЯ", "НА МАШИНЕ",
    "С Измайловского проспекта следуйте по красным стрелкам на схеме через открытую арку во двор.",
    "Сразу после арки поверните налево и двигайтесь вдоль здания до конца по красной стрелке.",
    "! Во дворе и в конце маршрута, вас ждёт бесплатная парковка.", "ПЕШКОМ",
    "С Измайловского проспекта следуйте по зелёным стрелкам на схеме через открытую арку во двор.",
    "Сразу после арки поверните налево и идите вдоль здания до конца по зелёной стрелке.",
    "ВХОД В ЗДАНИЕ", "Подойдите к двери с козырьком, отмеченной геометкой на схеме.", "На домофоне наберите #0115.",
    "Поднимитесь по лестнице на 3-й этаж.", "Дверь слева.", "На домофоне двери наберите 0115.",
    "Войдите внутрь — кабинет № 3.",
]
plain = src.replace("**", "")
missing = [t for t in EXPECTED if f'"{t}"' not in plain]
check("all requested texts present verbatim", not missing, f"missing: {missing}" if missing else f"{len(EXPECTED)} texts")
print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
