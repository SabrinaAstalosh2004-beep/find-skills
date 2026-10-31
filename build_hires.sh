#!/usr/bin/env bash
# Build izmailovsky_2_routes_3x.png: every overlay rendered natively at 3x the map resolution.
# Usage: ./build_hires.sh <original map png> [scale]      (TEXTURE=1 -> procedural map textures, *_real.png)
# The 1x chain runs first (its searched positions are reused), then map edits at 1x, an upscaled base,
# and the overlay chain again with SCALE set.
set -euo pipefail
MAP=$1; S=${2:-3}
T=$(mktemp -d)
python3 -I make_routes.py "$MAP" "$T/a.png" >/dev/null
python3 -I add_arch_marker.py "$T/a.png" "$T/b.png" >/dev/null
python3 -I add_place_labels.py "$T/b.png" "$T/c.png" >/dev/null
python3 -I add_metro.py "$T/c.png" "$T/d.png" >/dev/null
python3 -I add_start_icons.py "$MAP" "$T/d.png" "$T/e.png" >/dev/null
POLSKY_MODE=remove python3 -I add_polsky.py "$MAP" "$T/m1.png" >/dev/null
python3 -I remove_rotonda.py "$T/m1.png" "$T/m2.png" >/dev/null
OUTNAME=izmailovsky_2_routes_3x.png
if [ "${TEXTURE:-0}" = 1 ]; then
  python3 -I texture_map.py "$T/m2.png" "$T/hb.png" "$S" >/dev/null
  OUTNAME=izmailovsky_2_routes_3x_real.png
else
  python3 -c "
from PIL import Image
im = Image.open('$T/m2.png'); im.resize((im.size[0] * $S, im.size[1] * $S), Image.LANCZOS).save('$T/hb.png')"
fi
export SCALE=$S
ROUTES_META="$T/a.png.meta.json" python3 -I make_routes.py "$T/hb.png" "$T/ha.png" >/dev/null
python3 -I add_arch_marker.py "$T/ha.png" "$T/hbb.png" >/dev/null
python3 -I add_place_labels.py "$T/hbb.png" "$T/hc.png" >/dev/null
python3 -I add_metro.py "$T/hc.png" "$T/hd.png" >/dev/null
ICONS_JSON="$T/e.png.icons.json" python3 -I add_start_icons.py "$MAP" "$T/hd.png" "$T/he.png" >/dev/null
python3 -I add_venue_label.py "$T/he.png" "$T/hf.png" >/dev/null
POLSKY_MODE=text MAP1="$MAP" python3 -I add_polsky.py "$T/hf.png" "$T/hg.png" >/dev/null
python3 -I add_info.py "$T/hg.png" "$OUTNAME" >/dev/null
rm -f "$OUTNAME.info.json" "$OUTNAME.info_mask.npy"
if [ "${TEXTURE:-0}" = 1 ]; then  # 1x version of the textured map
  python3 -c "
from PIL import Image
im = Image.open('$OUTNAME'); im.resize((im.size[0] // $S, im.size[1] // $S), Image.LANCZOS).save('izmailovsky_2_routes_real.png', optimize=True)"
fi
rm -rf "$T"
echo "saved $OUTNAME"
