# -*- coding: utf-8 -*-
"""Δημιουργεί το icon.ico της εφαρμογής (πράσινο φόντο + λευκή απόδειξη με €)."""
import os
from PIL import Image, ImageDraw, ImageFont

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# πράσινο στρογγυλεμένο φόντο
d.rounded_rectangle([8, 8, S - 8, S - 8], radius=46, fill=(31, 111, 92, 255))

# λευκή "απόδειξη" με πριονωτό κάτω μέρος
left, right, top = 74, 182, 52
teeth_h = 16
bottom = 196
d.rectangle([left, top, right, bottom - teeth_h], fill=(255, 255, 255, 255))
# δόντια
n = 6
tw = (right - left) / n
for i in range(n):
    x0 = left + i * tw
    d.polygon([(x0, bottom - teeth_h), (x0 + tw / 2, bottom), (x0 + tw, bottom - teeth_h)],
              fill=(255, 255, 255, 255))

# γραμμές κειμένου
gray = (150, 160, 155, 255)
for i, y in enumerate(range(78, 150, 20)):
    w = right - 20 if i % 2 == 0 else right - 44
    d.line([(left + 12, y), (w, y)], fill=gray, width=6)

# σύμβολο €
try:
    font = ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "arialbd.ttf"), 92)
except Exception:
    font = ImageFont.load_default()
d.text((S / 2, 168), "€", font=font, fill=(201, 119, 42, 255), anchor="mm")

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
img.save(out, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("icon written:", out)
