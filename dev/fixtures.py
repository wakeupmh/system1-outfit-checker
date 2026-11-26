"""Writes three small, distinct stand-in look photos for the e2e check: python dev/fixtures.py <dir>.

The e2e runs against the mock decider, so only the files' bytes matter, not what they show. Used when the
stock photos in bench/.images (gitignored, downloaded by the bench scripts) are not there, as in CI.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
for i, colour in enumerate([(220, 80, 160), (40, 40, 40), (90, 160, 220)]):
    im = Image.new("RGB", (300, 400), (240, 236, 228))
    d = ImageDraw.Draw(im)
    d.ellipse((125, 30, 175, 80), fill=(200, 170, 140))
    d.rectangle((110, 90, 190, 260), fill=colour)
    d.rectangle((115, 260, 145, 380), fill=(60, 60, 70))
    d.rectangle((155, 260, 185, 380), fill=(60, 60, 70))
    im.save(out / f"look_{i}.jpg", "JPEG", quality=85)
print(out)
