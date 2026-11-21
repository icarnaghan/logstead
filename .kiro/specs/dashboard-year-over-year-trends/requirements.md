# Requirements Document

## Introduction

This feature turns the main dashboard of the Logstead single-user Schedule E rental tax app (React 19 + Vite + TypeScript SPA, Monarch-style theming; Python 3.12 Lambda over single-table DynamoDB, S3, Cognito JWT auth) from a single-year view into a multi-year, **portfolio-level trends** view. The user tracks IRS Schedule E rental data across multiple tax years (one entry per Schedule E line per tax year), and today the main dashboard only shows one selected year at a time. This feature lets the user see how the whole rental portfolio has performed over the years at a glance.

The redesigned dashboard shows two things:

- A **latest-year-at-a-glance** headline: the portfolio net for the most recent year that has any Schedule E data, labeled with that year — a single number for an instant read.
- A **trends section** spanning every year that has any Schedule E data (no fixed window or cap), containing three portfolio-level, multi-year charts:
  - **a.** Portfolio income / expenses / net over the years.
  - **b.** Net by property over the years (one series per property across years — a cross-property comparison).
  - **c.** Portfolio depreciation (Schedule E Line 18) over the years.

Scope decisions already confirmed with the user and carried into these requirements:

- The dashboard's current **single-year per-property breakdown table is dropped**. The property detail pages already own per-property, per-year detail; the dashboard must not duplicate it.
- The trend charts cover **all** years that have any Schedule E data.
- The first cut includes **all three** trend charts.

Explicitly **out of scope** because it would duplicate the property detail page: per-property single-year data tables, a single-year portfolio snapshot or combined Schedule E totals tile, a single property's own single-year chart, and RentCast property attributes. A small number of lightweight, portfolio-level or navigation-only tiles are retained — a Latest_Data_Year portfolio depreciation summary, a needs-attention nudge, and a properties launchpad — because they add navigation and at-a-glance value without duplicating per-property per-line detail.

This feature builds on existing code rather than introducing new aggregation logic. The backend reuses the same per-(property, year) derivations the current `DashboardService` already performs — each property's income / expense / net from its Schedule E report via `ReportingService.report_for(property_id, year)`, and depreciation via `DepreciationService.property_depreciation_for_year(property_id, year)` (the figure that feeds Schedule E Line 18) — looped across years so dashboard figures always reconcile with the per-property Schedule E reports. The frontend reuses the existing charting infrastructure in `frontend/src/components/charts/` (`ChartCard`, `LazyChart`, `ChartErrorBoundary`, `chartColors`, and the always-present Recharts-free data-table fallback pattern), keeping Recharts code-split out of the initial paint.

Money is an exact two-decimal `Decimal` in backend code and is serialized as fixed two-decimal **strings** over the wire (never floats, never a DynamoDB `Number`). A negative net denotes a loss.

## Glossary

- **Dashboard_Page**: The main portfolio-home page at `frontend/src/pages/DashboardPage.tsx`, redesigned by this feature into a multi-year trends view.
- **Trends_Endpoint**: A new read-only backend endpoint added by this feature that returns a year-indexed, portfolio-level trends series for the authenticated user, spanning every Data_Year. It introduces no new write path and no change to any data model.
- **Dashboard_API**: The frontend transport wrapper at `frontend/src/api/dashboard.ts` that calls the backend dashboard routes, extended by this feature with a typed call to the Trends_Endpoint.
- **Reporting_Service**: The existing backend `ReportingService`, whose `report_for(property_id, year)` yields a property's Schedule E report totals (income, expenses, net) for a tax year.
- **Depreciation_Service**: The existing backend `DepreciationService`, whose `property_depreciation_for_year(property_id, year)` yields a property's depreciation total for a tax year — the same figure that feeds Schedule_E_Line_18.
- **Property_Service**: The existing backend `PropertyService`, whose `list()` returns the authenticated user's properties.
- **Schedule_E_Line_18**: The depreciation expense total reported on Schedule E Line 18 for a property (and, aggregated, across the portfolio) for a tax year.
- **Tax_Year**: A calendar year for which Schedule E data may exist. Rental data is tracked as one entry per Schedule E line per Tax_Year.
- **Data_Year**: A Tax_Year for which the authenticated user has any Schedule E data. The trends span is exactly the set of Data_Years.
- **Latest_Data_Year**: The most recent Data_Year — the Tax_Year labeled in the latest-year-at-a-glance headline.
- **Trends_Series**: The year-indexed, portfolio-level data returned by the Trends_Endpoint: for each Data_Year, portfolio total income, total expenses, net, per-property net, and portfolio depreciation total.
- **Portfolio_Net**: For a given Tax_Year, the sum of every property's net (`total_income - total_expenses`) as taken from that property's Schedule E report; negative denotes a loss.
- **Money_String**: A monetary value serialized over the wire as a fixed two-decimal string (e.g. `"1500.00"`, `"-125.00"`), never a float and never a DynamoDB `Number`.
- **Income_Expense_Net_Trend_Chart**: Trend chart (a): portfolio total income, total expenses, and net plotted across all Data_Years.
- **Net_By_Property_Trend_Chart**: Trend chart (b): one series per property, each property's net plotted across all Data_Years — a cross-property, multi-year comparison.
- **Depreciation_Trend_Chart**: Trend chart (c): portfolio Schedule_E_Line_18 depreciation total plotted across all Data_Years.
- **Trend_Chart**: Any one of the three charts above.
- **Data_Table_Fallback**: The always-present, Recharts-free table rendered alongside each Trend_Chart for mobile, error, and accessibility, following the existing `IncomeExpenseNetTable` / `NetByPropertyTable` pattern.
- **Chart_Infrastructure**: The existing reusable charting components in `frontend/src/components/charts/` — `ChartCard`, `LazyChart`, `ChartErrorBoundary`, `chartColors`, and the data-table fallback pattern.
- **Empty_State**: The existing "add your first property" guidance shown when the authenticated user owns no properties, rendered by `DashboardEmptyState`.
- **Current_Single_Year_Breakdown**: The dashboard's existing single-year per-property breakdown table, dropped by this feature.
- **Depreciation_Summary_Tile**: A portfolio-level tile showing the Schedule_E_Line_18 depreciation total across all properties for the Latest_Data_Year, plus a count of properties with any depreciation in that year. Single-year, portfolio-level — distinct from the multi-year Depreciation_Trend_Chart.
- **Needs_Attention_Nudge**: A lightweight tile listing each property that has no income recorded for the Latest_Data_Year as a navigation link into that property; shows a positive confirmation when none need attention. It is a nudge/link list, not a per-property data table.
- **Properties_Launchpad**: A lightweight tile listing each of the user's properties as a navigation link into that property's detail page, optionally annotated with that property's net for the Latest_Data_Year. It is an entry-point list, not a per-property per-line data table.

## Requirements

### Requirement 1: Latest-year-at-a-glance headline

**User Story:** As the single user, I want the dashboard to headline my portfolio net for the most recent year that has data, labeled with that year, so that I get an instant read on how my portfolio is doing without picking a year.

#### Acceptance Criteria

1. WHEN the Dashboard_Page renders for a user who owns one or more properties and has at least one Data_Year, THE Dashboard_Page SHALL display the Portfolio_Net for the Latest_Data_Year as exactly one headline figure.
2. WHEN the Dashboard_Page displays the headline figure, THE Dashboard_Page SHALL label that figure with the Latest_Data_Year as a four-digit calendar year.
3. WHEN the Dashboard_Page displays the headline figure, THE Dashboard_Page SHALL render it in the app's existing display money format (two-decimal, with the app's currency and loss conventions), derived from the Portfolio_Net Money_String without re-deriving it from a float.
4. IF the headline Portfolio_Net is negative, THEN THE Dashboard_Page SHALL present the figure with a visually distinct loss indication, consistent with the app's existing loss styling, such that it is distinguishable from a non-negative figure.
5. IF the headline Portfolio_Net is zero or positive, THEN THE Dashboard_Page SHALL present the figure without the loss indication.

### Requirement 2: Trends span all years with data

**User Story:** As the single user, I want the trend charts to cover every year that has data, so that I see my complete multi-year history without a fixed window hiding older years.

#### Acceptance Criteria

1. THE Trends_Endpoint SHALL derive the span of the Trends_Series from the set of Data_Years for the authenticated user.
2. THE Trends_Endpoint SHALL include exactly one entry in the Trends_Series for every Data_Year in the set of Data_Years for the authenticated user, with no Data_Year omitted and no duplicate entries.
3. THE Trends_Endpoint SHALL order the entries in the Trends_Series by year in ascending chronological order.
4. WHERE the set of Data_Years is non-contiguous, THE Trends_Endpoint SHALL include only the Data_Years that have data and SHALL NOT insert entries for gap years that have no data.
5. THE Trends_Endpoint SHALL NOT impose a fixed-size window or cap on the number of years returned, supporting a Trends_Series ranging from one Data_Year up to the total count of Data_Years for the authenticated user.
6. WHEN the Dashboard_Page renders the trends section, THE Dashboard_Page SHALL display each Trend_Chart across the full set of Data_Years returned by the Trends_Endpoint, preserving the ascending chronological order of the Trends_Series.

### Requirement 3: Portfolio income / expenses / net trend chart

**User Story:** As the single user, I want a chart of my portfolio income, expenses, and net over the years, so that I can see how my overall rental finances have trended.

#### Acceptance Criteria

1. WHEN the Dashboard_Page renders the trends section for a user with at least one Data_Year, THE Dashboard_Page SHALL display the Income_Expense_Net_Trend_Chart plotting portfolio total income, total expenses, and net for every Data_Year, ordered chronologically from earliest to latest Data_Year along the horizontal axis.
2. THE Dashboard_Page SHALL render the Income_Expense_Net_Trend_Chart through the existing Chart_Infrastructure, lazy-loaded via `LazyChart` so that Recharts is excluded from the initial paint and loaded only when the trends section is rendered.
3. THE Dashboard_Page SHALL render a Data_Table_Fallback for the Income_Expense_Net_Trend_Chart that is present in the rendered output for every render, containing one row per Data_Year with that year's portfolio total income, total expenses, and net.
4. WHERE a Data_Year's portfolio net is less than zero, THE Dashboard_Page SHALL present that year's net as a loss, visually distinguished from non-negative net values, in both the Income_Expense_Net_Trend_Chart and the Data_Table_Fallback.

### Requirement 4: Net-by-property trend chart

**User Story:** As the single user, I want a chart comparing each property's net across the years, so that I can see which properties are carrying the portfolio and which are lagging.

#### Acceptance Criteria

1. WHEN the Dashboard_Page renders the trends section for a user with at least one Data_Year, THE Dashboard_Page SHALL display the Net_By_Property_Trend_Chart with exactly one series for every property the user owns, including a property that has no Schedule E data in any Data_Year, plotting each property's net across all of the user's Data_Years ordered chronologically ascending on the horizontal axis.
2. WHERE a property has no Schedule E data for a given Data_Year, THE Dashboard_Page SHALL represent that property's net for that Data_Year as `0.00`.
3. THE Dashboard_Page SHALL render the Net_By_Property_Trend_Chart through the existing Chart_Infrastructure, lazy-loaded via `LazyChart` so Recharts is excluded from the initial page paint and loaded only when the trends section is rendered.
4. THE Dashboard_Page SHALL render a Data_Table_Fallback for the Net_By_Property_Trend_Chart that is present in the rendered output for every render.
5. THE Dashboard_Page SHALL label each property's series by that property's display name, and WHERE two or more properties share an identical display name, THE Dashboard_Page SHALL render a distinct series for each such property with a label that uniquely identifies it.

### Requirement 5: Portfolio depreciation trend chart

**User Story:** As the single user, I want a chart of my portfolio depreciation over the years, so that I can see how my Schedule E Line 18 depreciation has trended.

#### Acceptance Criteria

1. WHEN the Dashboard_Page renders the trends section for a user with at least one Data_Year, THE Dashboard_Page SHALL display the Depreciation_Trend_Chart plotting the portfolio Schedule_E_Line_18 depreciation total, aggregated across all properties, as one data point per Data_Year ordered chronologically ascending.
2. THE Dashboard_Page SHALL render the Depreciation_Trend_Chart through the existing Chart_Infrastructure, lazy-loaded via `LazyChart` so that Recharts is excluded from the initial paint and loaded only when the trends section is rendered.
3. THE Dashboard_Page SHALL render a Data_Table_Fallback for the Depreciation_Trend_Chart that is present in the rendered output for every render, listing one row per Data_Year with its portfolio Schedule_E_Line_18 depreciation total.

### Requirement 6: Read-only trends endpoint reusing existing aggregation

**User Story:** As the maintainer, I want the trends backed by a single read-only endpoint that reuses the existing per-property Schedule E derivations, so that dashboard figures always reconcile with the per-property reports without new aggregation logic or a data-model change.

#### Acceptance Criteria

1. THE Trends_Endpoint SHALL be read-only and SHALL NOT introduce any new backend write path.
2. THE Trends_Endpoint SHALL NOT change any existing data model, and SHALL derive every returned figure from the existing per-property Schedule E derivations.
3. THE Trends_Endpoint SHALL derive each property's per-year income, expenses, and net from Reporting_Service's `report_for(property_id, Tax_Year)`, such that each returned per-property figure is exactly equal to the corresponding figure produced by `report_for(property_id, Tax_Year)` for the same property and Tax_Year.
4. THE Trends_Endpoint SHALL derive each year's portfolio depreciation total from Depreciation_Service's `property_depreciation_for_year(property_id, Tax_Year)` summed across the authenticated user's properties.
5. THE Trends_Endpoint SHALL compute each year's Portfolio_Net as the sum of the per-property nets for that Tax_Year.
6. THE Trends_Endpoint SHALL scope every returned figure to the authenticated user's own properties.
7. WHERE Reporting_Service does not return a report for a given property and Tax_Year (for example a missing or unowned property), THE Trends_Endpoint SHALL skip that property-year's contribution rather than fail the request, consistent with the existing DashboardService behavior, and SHALL NOT create or modify any persisted data.

### Requirement 7: Money correctness on the wire

**User Story:** As the single user preparing a tax return, I want every dollar figure to be exact, so that my dashboard trends reconcile to the cent with my Schedule E reports.

#### Acceptance Criteria

1. THE Trends_Endpoint SHALL serialize every monetary figure in the Trends_Series as a Money_String with exactly two decimal places.
2. THE Trends_Endpoint SHALL NOT serialize any monetary figure as a floating-point value or as a DynamoDB `Number`.
3. THE Dashboard_API SHALL type every monetary field of the Trends_Series as a fixed two-decimal string.
4. FOR ANY Data_Year and property, THE Trends_Endpoint SHALL return the per-property income, expenses, and net matching the per-property Schedule E report for that property and Tax_Year to the exact cent (zero difference).
5. FOR ANY Data_Year, THE Trends_Endpoint SHALL return a Portfolio_Net equal to the exact-cent sum of the per-property nets for that Tax_Year, with zero rounding difference across all properties.

### Requirement 8: Empty state preserved

**User Story:** As a brand-new user with no properties, I want the dashboard to guide me to add my first property instead of showing empty charts, so that I know what to do next.

#### Acceptance Criteria

1. WHEN the Dashboard_Page renders for a user who owns zero properties, THE Dashboard_Page SHALL display the existing Empty_State "add your first property" guidance.
2. WHILE the user owns zero properties, THE Dashboard_Page SHALL NOT display any Trend_Chart.
3. WHILE the user owns zero properties, THE Dashboard_Page SHALL NOT display the latest-year-at-a-glance headline.
4. WHILE the user owns one or more properties and has zero Data_Years across all owned properties, THE Dashboard_Page SHALL display a no-data indication for the trends section and SHALL NOT display an error indication.
5. WHILE the user owns one or more properties and has zero Data_Years across all owned properties, THE Dashboard_Page SHALL NOT display the latest-year-at-a-glance headline.
6. WHILE the user owns one or more properties and has zero Data_Years across all owned properties, THE Dashboard_Page SHALL NOT display any Trend_Chart.

### Requirement 9: Keep the dashboard a portfolio-level trends view

**User Story:** As the single user, I want the dashboard to stop duplicating per-property, per-year detail that the property pages already own, while keeping a few lightweight entry points, so that the dashboard stays a portfolio-level trends view that still helps me navigate and spot gaps.

#### Acceptance Criteria

1. WHEN the Dashboard_Page is rendered, THE Dashboard_Page SHALL NOT display the Current_Single_Year_Breakdown or any per-property, per-line single-year data table.
2. WHEN the Dashboard_Page is rendered, THE Dashboard_Page SHALL NOT display a single-year portfolio income/expense/net snapshot tile or a single-year combined Schedule E totals tile (these are superseded by the latest-year headline and the trend charts).
3. WHEN the Dashboard_Page is rendered, THE Dashboard_Page SHALL NOT display any chart whose data is scoped to a single property for a single year.
4. WHEN the Dashboard_Page is rendered, THE Dashboard_Page SHALL NOT display any RentCast-sourced property attribute (including address, property type, bedroom count, bathroom count, square footage, year built, or lot size).
5. WHERE the Dashboard_Page displays a tile other than the latest-year headline or a Trend_Chart, THE Dashboard_Page SHALL limit it to one of: the Depreciation_Summary_Tile, the Needs_Attention_Nudge, the Properties_Launchpad, quick actions, or the Empty_State.
6. WHERE the Dashboard_Page displays the Needs_Attention_Nudge or the Properties_Launchpad, THE Dashboard_Page SHALL present each property as a navigation link into that property's detail page rather than as a per-property per-line data table, scoping any per-property figure shown to the Latest_Data_Year.

### Requirement 10: Accessibility, mobile, and resilient charting

**User Story:** As the single user on a phone or with assistive technology, I want every chart to have an accessible fallback and to degrade gracefully, so that I can read my trends in any context.

#### Acceptance Criteria

1. WHEN the Dashboard_Page renders a Trend_Chart, THE Dashboard_Page SHALL place it inside a `ChartCard` with an accessible label that programmatically exposes the chart's title and the data series it represents to assistive technology, following the existing Chart_Infrastructure pattern.
2. THE Dashboard_Page SHALL keep every Trend_Chart's Recharts rendering code-split such that no Recharts code is requested or executed during the initial dashboard paint and is loaded only after the initial paint completes.
3. IF a Trend_Chart fails to render, THEN THE Dashboard_Page SHALL replace that chart with its Data_Table_Fallback via the existing `ChartErrorBoundary` pattern, SHALL present a visible indication that the chart could not be displayed, and SHALL keep all other charts and the remainder of the page rendered.
4. THE Dashboard_Page SHALL present each monetary figure in a Trend_Chart and the corresponding figure in its Data_Table_Fallback using identical numeric value, rounding precision, and currency formatting, with no discrepancy between the two.
5. WHILE the Dashboard_Page is displayed on a viewport width of 320 to 767 pixels, THE Dashboard_Page SHALL render every Trend_Chart or its Data_Table_Fallback fully within the viewport width without horizontal page scrolling and without clipping of chart or table content.

### Requirement 11: Deliberate N-properties x M-years derivation

**User Story:** As the maintainer, I want the trends derivation to be deliberate about looping across properties and years, so that it stays correct and predictable at this single-user scale.

#### Acceptance Criteria

1. THE Trends_Endpoint SHALL derive the Trends_Series by iterating over each of the authenticated user's properties and each Data_Year, reusing the existing per-(property, year) derivations exactly once per (property, Data_Year) pair.
2. THE Trends_Endpoint SHALL return a result in which every Data_Year present in the series carries a defined, non-null Money_String value for portfolio income, portfolio expenses, Portfolio_Net, each property's net, and the portfolio depreciation total.
3. WHERE a property has no Schedule E data for a given Data_Year, THE Trends_Endpoint SHALL contribute a value of `0.00` for that property's income, expenses, net, and depreciation to that Data_Year's totals.
4. IF the authenticated user owns no properties, THEN THE Trends_Endpoint SHALL return an empty Trends_Series.

### Requirement 12: Latest-year portfolio depreciation summary

**User Story:** As the single user, I want the dashboard to show my current-year portfolio depreciation alongside the depreciation trend, so that I can see this year's Line 18 total at a glance without opening a report.

#### Acceptance Criteria

1. WHEN the Dashboard_Page renders for a user who owns one or more properties and has at least one Data_Year, THE Dashboard_Page SHALL display the Depreciation_Summary_Tile showing the portfolio Schedule_E_Line_18 depreciation total for the Latest_Data_Year.
2. THE Dashboard_Page SHALL render the Depreciation_Summary_Tile's total as a Money-formatted two-decimal figure using the app's existing display money format.
3. THE Dashboard_Page SHALL display in the Depreciation_Summary_Tile a count of the user's properties that have a non-zero Schedule_E_Line_18 depreciation total for the Latest_Data_Year.
4. THE Dashboard_Page SHALL derive the Depreciation_Summary_Tile's figures from the same Trends_Series entry for the Latest_Data_Year that backs the trend charts, so the summary and the depreciation trend reconcile exactly for that year.
5. WHILE the user owns one or more properties and has zero Data_Years, THE Dashboard_Page SHALL NOT display the Depreciation_Summary_Tile.
