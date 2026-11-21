# Bugfix Requirements Document

## Introduction

The pure Schedule E Part I parser (`backend/src/logstead/services/schedule_e_parser.py`)
turns an Amazon Textract blocks list into a structured `ParsedExtraction` of property
columns and per-line amounts for human review. On a real production document — a user's
30-page 2023 tax-return PDF (20,473 Textract blocks) — the parser first reported **10
property columns**, and after the width-heuristic fix still reported **3**, for a Schedule E
that actually has **2** properties. The real Schedule E Part I is page 13 of 30; its
property table is 31 rows × 8 columns with the property-letter headers A/B/C sitting at
non-contiguous table columns 4, 6, and 8. The IRS form always prints three column headers
(A, B, C), but the taxpayer used only two: columns A and B carry Rents and expenses, while
column C is the form's totals/summary column — it has no Rents and no per-property expenses,
only roll-up totals (lines 23a-26) that Textract files under the printed "C" header. The
parser mistook that totals column for a third property.

Because every extracted value is surfaced for human confirmation, this defect does not
corrupt persisted data, but it produces a badly wrong pre-fill: seven phantom property
columns, amounts pulled from the wrong cells, and content lifted from unrelated pages. The
root causes are a document-global table-width heuristic, a hard-coded assumption that
labels live in table column 1 and property amounts occupy contiguous columns 2..N, a
page-location test loose enough to match Schedule C and worksheet pages, the absence of
any structural cap on the property-column count, and — because the IRS form always prints
three A/B/C headers — the absence of any test that distinguishes a genuine property column
from the form's unused totals/summary column.

## Bug Analysis

### Current Behavior (Defect)

What currently happens when the parser processes a multi-page return whose Schedule E Part I
page uses the real IRS layout (property-letter headers at non-contiguous columns) and that
also contains unrelated wide tables and a Schedule C page.

1.1 WHEN the document contains TABLE blocks on non-Schedule-E pages that are wider than the Schedule E Part I table THEN the system counts property columns from the globally widest table (`max_col - 1`) and reports property columns that do not exist (e.g. 10 columns from an unrelated 11-column worksheet)
1.2 WHEN the Schedule E Part I table places the property-letter headers (A, B, C) at non-contiguous columns (4, 6, 8) with the line label in column 2 THEN the system reads amounts from contiguous columns 2..N and the column-1 label assumption, producing wrong per-line amounts and misaligned columns
1.3 WHEN a page is a Schedule C or a worksheet that shares generic expense labels (Advertising, Insurance, Supplies, Taxes, Utilities, Commissions) with Schedule E THEN the system treats that page as a Schedule E Part I page and reads property data from it
1.4 WHEN the located property-column count exceeds the structural maximum of a Schedule E Part I page (3 columns: A, B, C) THEN the system imposes no cap and emits however many columns the width heuristic produced
1.5 WHEN the IRS form prints a property-letter header (e.g. C) for a column the taxpayer did not use — so that column carries only the form's totals/summary roll-ups (no Rents, no per-property expenses) THEN the system treats that totals column as a real property and emits a phantom column (e.g. reporting 3 properties for a return with 2)

### Expected Behavior (Correct)

What should happen instead for the same conditions.

2.1 WHEN the document contains TABLE blocks on non-Schedule-E pages that are wider than the Schedule E Part I table THEN the system SHALL ignore those tables and derive property columns only from the located Schedule E Part I page(s)
2.2 WHEN the Schedule E Part I table places the property-letter headers (A, B, C) at non-contiguous columns (4, 6, 8) with the line label in column 2 THEN the system SHALL detect the property-letter header row, use the header letters' column indexes as the property-amount columns, map each row's line by scanning its text cells for a recognized Schedule E line label, and read each property's amount from the header-letter columns — yielding exactly 3 columns with the correct per-line amounts
2.3 WHEN a page is a Schedule C or a worksheet that shares generic expense labels with Schedule E THEN the system SHALL reject that page as not-Part-I by requiring Schedule-E-specific evidence (the co-occurrence of "Schedule E" and "Rents received", and/or the "Properties:" A/B/C header row)
2.4 WHEN the located property-column count would exceed the structural maximum of a single Schedule E Part I page (3) THEN the system SHALL cap the count by deriving columns from the A/B/C header letters actually present, handling each genuine Part I page's header independently and concatenating the resulting columns, never inventing columns from raw table width
2.5 WHEN a detected property-letter column carries no Rents (line 3) and fewer than two populated expense lines (the signature of the form's unused totals/summary column) THEN the system SHALL prune that column as a phantom, keeping only genuine property columns — and SHALL preserve a column that has Rents OR enough expenses (so a royalty-only property with its own expenses is never dropped), falling back to keeping all columns if the rule would reject every one

### Unchanged Behavior (Regression Prevention)

Existing behavior that must be preserved for inputs that do not trigger the bug.

3.1 WHEN a clean Schedule E Part I page lays out labels in column 1 and property amounts in contiguous columns 2..N (the existing `clean_two_columns.json` fixture) THEN the system SHALL CONTINUE TO produce one column per property with the same per-line amounts, addresses, and tax year as before
3.2 WHEN a Schedule E Part I line is Line 18 (Depreciation) THEN the system SHALL CONTINUE TO exclude it, reading only the allow-set {3, 4, 5-17, 19} and never carrying a depreciation amount
3.3 WHEN no page in the document is a Schedule E Part I page THEN the system SHALL CONTINUE TO return `no_schedule_e_found=True` with no columns
3.4 WHEN a value's contributing block confidence is below `min_confidence` or a value cannot be read THEN the system SHALL CONTINUE TO emit the raw read token (empty when absent) and flag `needs_verification`, and SHALL CONTINUE TO leave money normalization to the service layer
3.5 WHEN the TABLES result is weak but the page is a genuine Part I page THEN the system SHALL CONTINUE TO fall back to the geometry reader, now scoped to the Part I page and capped at a sane property-column maximum
3.6 WHEN the header lines carry a tax year and the physical-address boxes are present THEN the system SHALL CONTINUE TO detect the single tax year and read the per-column address text as before

## Bug Condition and Properties

### Bug Condition Function

Identifies the inputs (Textract blocks lists) that trigger the defect.

```pascal
FUNCTION isBugCondition(blocks)
  INPUT: blocks of type list of Textract Block
  OUTPUT: boolean

  // The document contains a genuine Schedule E Part I page whose property
  // columns must be derived from A/B/C header letters, AND the current
  // width/contiguity/location heuristics would mis-count or mis-read it.
  RETURN existsPartIPageWithLetterHeaders(blocks)
         AND (
              widestTableIsOnNonPartIPage(blocks)        // Root cause 1
           OR partIHeadersAreNonContiguous(blocks)        // Root cause 2
           OR aSharedLabelPageFalseMatches(blocks)        // Root cause 3
           OR locatedColumnCount(blocks) > 3              // Root cause 4
           OR hasUnusedTotalsColumnUnderLetterHeader(blocks) // Root cause 5
         )
END FUNCTION
```

### Property Specification (Fix Checking)

Defines the correct behavior the fixed parser must satisfy for buggy inputs.

```pascal
// Property: Fix Checking - correct property-column count and amounts
FOR ALL blocks WHERE isBugCondition(blocks) DO
  result <- parse_schedule_e'(blocks)
  ASSERT length(result.columns) = countOfGenuinePropertyColumns(blocks)
  // genuine = has Rents(line 3) OR >= 2 populated expense lines; the form's
  // unused totals/summary column is pruned, not counted.
  ASSERT forEachColumn amountsReadFrom(headerLetterColumns)
  ASSERT noColumnIsTheFormTotalsColumn(result)
  ASSERT noColumnContains(scheduleELine = 18)
  ASSERT nonPartIPagesContributeNoColumns(result)
END FOR
```

### Preservation Specification (Preservation Checking)

Defines that non-buggy inputs behave identically before and after the fix.

```pascal
// Property: Preservation Checking - unchanged behavior for non-buggy inputs
FOR ALL blocks WHERE NOT isBugCondition(blocks) DO
  ASSERT parse_schedule_e(blocks) = parse_schedule_e'(blocks)
END FOR
```

Where `parse_schedule_e` is the original (unfixed) function **F** and
`parse_schedule_e'` is the fixed function **F'**.
