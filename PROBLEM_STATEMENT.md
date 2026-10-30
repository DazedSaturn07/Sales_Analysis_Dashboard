# Problem statement

## Decision and audience

A retail analyst needs to explain which countries, products and observed customer
groups contribute to sales, how sales vary over recorded time, and which patterns
deserve a follow-up inventory or retention review. The audience is a retail
operations or commercial manager reviewing historical trading data.

## Questions

1. How much positive identified-customer sales activity is recorded, and what is
   the average value of a distinct invoice?
2. Which complete months, weekdays, hours, stock codes and countries lead by sales?
3. How concentrated is customer spending, and how do full-history RFM groups differ?
4. How often do first-observed purchase cohorts return in later observed months?
5. Can the headline and grouped metrics be reproduced independently in SQL?

## Population and scope

The supplied Online Retail II CSV contains 1,067,371 invoice lines from
2009-12-01 through 2011-12-09. The core population retains valid customer IDs,
non-cancelled invoices, positive integer quantities, positive unit prices and
usable dates/business keys. Repeated source fields after whitespace trimming are
removed with first occurrence retained. The resulting population has 779,425 lines.

Every rejected row has one mutually exclusive reason and source row number.
Revenue is extended positive sales rounded half up to integer pence per line.
StockCode is the product key, Invoice the order key and CustomerID the customer key.

Deliverables are reproducible Python code, ordered notebooks, audited CSVs,
SQL analysis/validation, nine static charts, a generated business brief and
beginner instructions. The native Power BI report includes six desktop pages,
dedicated phone layouts, a star model and source-reconciled DAX measures; its
verification is summarized in README.md. A new web application,
forecasting model, cloud deployment and automated marketing workflow are outside this retail-analysis scope.

## Acceptance criteria

- Three ordered notebooks regenerate outputs from raw data using a documented source setting.
- Raw data stays unchanged and a hash identifies the input used.
- Exclusions reconcile exactly to input minus retained rows.
- AOV is revenue divided by distinct invoices, expressed in GBP.
- Monetary totals agree exactly in integer pence across source controls and SQL.
- Monthly/country/product/order/customer/cohort tables reconcile, including RFM ties.
- Partial-month growth and unobserved future retention are not presented as zeros.
- Fresh-kernel notebooks, embedded synthetic boundary checks and independent SQL comparisons pass.
- README describes the actual repository, metric rules, reproduction and verification limits.

## Interpretation boundaries

This is a historical portfolio investigation, not a record of an intervention.
Cancellations, refunds and anonymous-customer sales are outside the selected
population; positive sales are not net sales. Exact-repeat removal is an explicit
assumption, not proof of source errors. Wholesale customers may dominate spending.
Customer cohorts are left-censored at the dataset start and right-censored at the
end. A customer may have multiple recorded countries. The timestamp's timezone
is unspecified. Costs, profit, product categories, stockouts, advertising exposure
and business outcomes cannot be inferred from this dataset.

Proposed actions must remain proposals until supported by margin/inventory data,
customer review or an evaluated campaign. Do not claim achieved savings or uplift.
