"""Verify that every preserved original file is unchanged (docs/ORIGINALS_SHA256.txt)."""
import hashlib, pathlib, sys
root = pathlib.Path(__file__).resolve().parents[1]
bad = 0
for line in (root / "docs" / "ORIGINALS_SHA256.txt").read_text().splitlines():
    digest, rel = line.split(None, 1)
    p = root / rel.strip()
    if not p.exists():
        print("MISSING ", rel); bad += 1
    elif hashlib.sha256(p.read_bytes()).hexdigest() != digest:
        print("MODIFIED", rel); bad += 1
print("All preserved originals verified." if not bad else f"{bad} problem(s).")
sys.exit(1 if bad else 0)
