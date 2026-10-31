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
check("width kept, strip appended below the map", r.shape[1] == W and r.shape[0] > H, f"{W}x{H} -> {r.shape[1]}x{r.shape[0]}")
card1_top = meta["cards"][0][1]
top = r[:card1_top]
diff = np.any(top != a[:card1_top], -1)
check("map above the first block unchanged except the metro caption", not (diff & ~mask[:card1_top]).any(),
      f"changed {diff.sum()} px")
# judged on the approved image itself: earlier steps also removed map labels (e.g. "Ротонда")
drawn = (a.max(-1) - a.min(-1) > 100)                      # routes, signs, logo, arrows: strongly saturated
check("caption covers no route, sign, logo or arrow", not (mask & drawn).any(), f"{(mask & drawn).sum()} px")
ink = cv2.dilate(((a.max(-1) < 175) & (np.abs(a[..., 0] - a[..., 2]) < 25)).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
check("caption covers no map text or icon", not (mask & ink).any(), f"{(mask & ink).sum()} px")
cb = meta["caption_bbox"]
check("caption next to the metro logo (logo box 618-753, 1347-1510)", 753 < cb[0] < 775 and 1347 < cb[1] and cb[3] < 1510, f"caption box {cb}")
check("caption fits inside the image", cb[2] < W, f"right edge {cb[2]} < {W}")
yel = (a[..., 0] > 150) & (a[..., 2] < 80) & (a[..., 0] - a[..., 2] > 120)   # the yellow arrow and its contour
ys, xs = np.nonzero(yel[1400:1700, 680:900])
arrow_end = 1400 + ys.max()
check("'КАК ДОБРАТЬСЯ' starts level with the end of the yellow metro arrow", 0 < card1_top - arrow_end <= 4,
      f"arrow ends at y {arrow_end}, block top {card1_top}")
c1, c2 = meta["cards"]
check("'ВХОД В ЗДАНИЕ' right below the first block, on the appended strip", c2[1] > c1[3] and c2[1] >= H,
      f"cards {meta['cards']}")

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
