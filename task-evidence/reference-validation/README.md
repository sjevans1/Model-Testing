# Reference validation evidence (fixtures are solvable; graders discriminate)

Generated 2026-10-15T01:43:29Z

## T3/T5/T8 (suite_reports.py): shipped-defective vs reference-correct
```
== T5 as shipped ==

4/13 checks pass; failing: ['A03', 'A04', 'A05', 'A07', 'A08', 'A09', 'A10', 'A12', 'A13']
== reference correct ==

13/13 checks pass
```

## T6 (grade_t6.py)
```
== cifix as shipped ==

1/6 pass; failing: ['G1', 'G2', 'G3', 'G4', 'G5']
== reference fix ==

6/6 pass
```

=== reference re-validation after the A05/A14 correction (2026-10-15T02:55:45Z) ===
reference: 14/14 checks pass
defective: 4/14 checks pass; failing: ['A03', 'A04', 'A05', 'A07', 'A08', 'A09', 'A10', 'A12', 'A13', 'A14']
