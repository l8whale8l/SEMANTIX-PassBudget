"""Build a zeroed IERS EOP file for the GMAT oracle run.

`docs/specs/ORBIT_VERIFICATION_CONTRACT.md` section 2 forces UT1-UTC and polar motion to
zero in *both* tools, so that a residual disagreement measures the two implementations
rather than two differently-dated EOP tables. The product engine has them zero by
construction. GMAT reads them from this file, so the file is rewritten with zeros.

Only the six measured columns are zeroed. Dates, MJD and the error columns keep their
original text, and every column keeps its exact width, so the file still matches the
FORTRAN format GMAT parses.
"""

import pathlib
import sys

SOURCE = pathlib.Path(sys.argv[1])
DEST = pathlib.Path(sys.argv[2])

# (start, end, width, decimals) of each field that must become zero.
FIELDS = [
    (19, 30, 11, 6),  # x  (arcsec)
    (30, 41, 11, 6),  # y  (arcsec)
    (41, 53, 12, 7),  # UT1-UTC (s)
    (53, 65, 12, 7),  # LOD (s)
    (65, 76, 11, 6),  # dPsi (arcsec)
    (76, 87, 11, 6),  # dEps (arcsec)
]

out = []
zeroed = 0
for line in SOURCE.read_text(encoding="latin-1").splitlines():
    # A data row starts with a 4-digit year in columns 0..3 and is long enough to hold
    # every field. Header and comment lines are copied through untouched.
    if len(line) >= 87 and line[:4].strip().isdigit() and len(line[:4].strip()) == 4:
        chars = list(line)
        for start, end, width, decimals in FIELDS:
            chars[start:end] = list(f"{0.0:{width}.{decimals}f}")
        out.append("".join(chars))
        zeroed += 1
    else:
        out.append(line)

DEST.parent.mkdir(parents=True, exist_ok=True)
DEST.write_text("\n".join(out) + "\n", encoding="latin-1", newline="\n")
print(f"rows zeroed: {zeroed}")
print(f"written    : {DEST}")
