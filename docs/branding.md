# The Lombo look

## Contents

- [The rule](#the-rule)
- [Colours and type](#colours-and-type)
- [The seal and the L](#the-seal-and-the-l)
- [This app's mark](#this-apps-mark)
- [What every app needs](#what-every-app-needs)
- [What to avoid](#what-to-avoid)

## The rule

**The Lombo L is in every icon.** Each app has its own seal, and a small mark of its own sits in
the open corner of the L. Each app also gets one wordmark trick (Tier's letters step down,
Shrink's get smaller from S to K, Shelf's F leans, Nap's fade out).

## Colours and type

| Use | Value |
|---|---|
| Background | `#0d0a08` |
| Surface | `#1a140f` |
| Borders | `#2c231a`, `#443528` |
| Text, muted | `#f4ede3`, `#b3a696` |
| Ember gradient | `#ffb347` to `#ff6a1a` to `#e23d0f` |

Headings and wordmarks: Cinzel (SIL Open Font License). Body text: Geist.

## The seal and the L

`assets/icon.svg` is the base seal: a ring with the gradient, an inner frame line, and the L. Banners use the
same seal on the left and the wordmark on the right.

## This app's mark

A crescent moon (filled `#ffb347`) with a small ember-coloured **z**, in the L's open corner: the moon is
right of the stem and the z sits above and beside it, clear of the stem and the foot. The wordmark trick:
the three letters of NAP in the banner fade out, N full, A at 70% and P at 40%, as if dropping off to sleep.

## What every app needs

- `assets/icon.svg`, plus a 512 px PNG (`icon-512.png`) for the container registry and GitHub.
- `assets/banner.svg` and `banner.png`, shown at the top of the README (1200 x 300).
- `assets/social-preview.svg` and `.png` (1280 x 640): the banner on a dark canvas, uploaded in the repository settings.

Render with the Cinzel command in the forge-branding skill, then look at every PNG.

## What to avoid

No Tolkien names, scripts, rings or symbols. Nothing that suggests the Jellyfin project made this.
