# RQ3 Repair-Approach Annotation Guide

## Task

Compare the student's original SQL, the repair, and the reference solution. Classify how much the repair preserves the student's approach. Judge the query structure and reasoning, not formatting, keyword case, or harmless alias changes.

## Categories

- `preserves_student_approach`: the repair keeps the student's table access, projection strategy, and main predicate structure, making only local corrections such as fixing an operator, constant, identifier, or syntax.
- `partially_changes_approach`: the repair keeps some meaningful structure but changes at least one major component, such as projection, predicate logic, join structure, or ordering strategy.
- `reproduces_reference_approach`: the repair uses essentially the same relational structure and clause choices as the reference; superficial formatting and equivalent aliases do not change this category.

When uncertain between adjacent categories, choose the less extreme category and record a short note. Do not infer the student's intent beyond the SQL shown.

## Practice Examples

These examples are for calibration and must not be included in the study sample.

1. Student: `SELECT * FROM alpha WHERE MIN > 0`; repair: `SELECT * FROM alpha WHERE MIN = 0`; reference: `SELECT * FROM alpha WHERE MIN = 0`. Category: `preserves_student_approach`. The table and projection stay the same; only the comparison is corrected.
2. Student: `SELECT CUI1 FROM bravo WHERE CUI2 = 'X'`; repair: `SELECT CUI1, RUI FROM bravo WHERE CUI2 = 'X'`; reference: `SELECT CUI1, RUI FROM bravo WHERE CUI2 = 'X'`. Category: `partially_changes_approach`. The filter and table remain, but the projection changes materially.
3. Student: `SELECT * FROM india WHERE CVF != 256`; repair: `SELECT LAT FROM india a JOIN juliett b ON a.CUI = b.CUI WHERE CVF != 256`; reference: `SELECT LAT FROM india a JOIN juliett b ON a.CUI = b.CUI WHERE CVF != 256`. Category: `reproduces_reference_approach`. The repair introduces the reference's join-based solution.
4. Student: `SELECT DISTINCT SVER FROM golf WHERE SVER < 1996`; repair: `SELECT DISTINCT SVER FROM golf WHERE SVER < 1996`; reference: `SELECT DISTINCT SVER FROM golf WHERE SVER < 1996`. Category: `reproduces_reference_approach`. The repair and reference are structurally identical.
5. Student: `SELECT * FROM hotel ORDER BY TUI ASC`; repair: `SELECT * FROM hotel ORDER BY TUI DESC, CUI ASC`; reference: `SELECT * FROM hotel ORDER BY TUI DESC, CUI ASC`. Category: `partially_changes_approach`. The table and projection are retained, but the ordering strategy is substantially corrected.

## Annotation Procedure

Annotators label independently. Use the `group_id` to keep records aligned; do not discuss labels until both files are complete. Report the quadratic-weighted Cohen's kappa before resolving disagreements. Resolve disagreements afterward by discussion and retain both original labels and the agreed label.