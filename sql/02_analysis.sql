-- Portable SELECTs: MySQL 8 and SQLite (runner supplies SQLite DATEDIFF).
-- Monetary totals remain integer pence. Do not FORMAT numbers into strings.

-- name: kpis
SELECT COUNT(*) AS SalesLines, SUM(RevenuePence) AS RevenuePence,
       COUNT(DISTINCT Invoice) AS Orders, COUNT(DISTINCT CustomerID) AS Customers,
       COUNT(DISTINCT StockCode) AS Products, COUNT(DISTINCT Country) AS Countries,
       SUM(Quantity) AS Quantity,
       SUM(RevenuePence) * 1e0 / (100e0 * COUNT(DISTINCT Invoice)) AS AvgOrderValue
FROM sales;

-- name: monthly_revenue
SELECT Year, Month, SUM(RevenuePence) AS RevenuePence,
       COUNT(DISTINCT Invoice) AS Orders, COUNT(DISTINCT CustomerID) AS Customers
FROM sales GROUP BY Year, Month ORDER BY Year, Month;

-- name: country_revenue
SELECT Country, SUM(RevenuePence) AS RevenuePence,
       COUNT(DISTINCT Invoice) AS Orders, COUNT(DISTINCT CustomerID) AS Customers
FROM sales GROUP BY Country ORDER BY RevenuePence DESC, Country;

-- name: product_performance
SELECT StockCode, SUM(RevenuePence) AS RevenuePence,
       SUM(Quantity) AS Quantity, COUNT(DISTINCT Invoice) AS Orders
FROM sales GROUP BY StockCode ORDER BY RevenuePence DESC, StockCode;

-- name: daily_revenue
SELECT WeekdayNumber, DayOfWeek, SUM(RevenuePence) AS RevenuePence,
       COUNT(DISTINCT Invoice) AS Orders
FROM sales GROUP BY WeekdayNumber, DayOfWeek ORDER BY WeekdayNumber;

-- name: hourly_revenue
SELECT Hour, SUM(RevenuePence) AS RevenuePence, COUNT(DISTINCT Invoice) AS Orders
FROM sales GROUP BY Hour ORDER BY Hour;

-- name: orders
SELECT Invoice, SUM(RevenuePence) AS RevenuePence, SUM(Quantity) AS Quantity,
       COUNT(*) AS `Lines`, MIN(CustomerID) AS CustomerID
FROM sales GROUP BY Invoice ORDER BY Invoice;

-- name: customer_metrics
WITH base AS (
    SELECT CustomerID,
           DATEDIFF((SELECT MAX(InvoiceDay) FROM sales), MAX(InvoiceDay)) + 1 AS Recency,
           COUNT(DISTINCT Invoice) AS Frequency, SUM(RevenuePence) AS MonetaryPence
    FROM sales GROUP BY CustomerID
), scored AS (
    SELECT base.*,
        6 - CEIL(5.0 * (RANK() OVER (ORDER BY Recency) +
            (COUNT(*) OVER (PARTITION BY Recency) - 1) / 2.0) / COUNT(*) OVER ()) AS R_Score,
        CEIL(5.0 * (RANK() OVER (ORDER BY Frequency) +
            (COUNT(*) OVER (PARTITION BY Frequency) - 1) / 2.0) / COUNT(*) OVER ()) AS F_Score,
        CEIL(5.0 * (RANK() OVER (ORDER BY MonetaryPence) +
            (COUNT(*) OVER (PARTITION BY MonetaryPence) - 1) / 2.0) / COUNT(*) OVER ()) AS M_Score
    FROM base
)
SELECT scored.*,
    CASE WHEN R_Score >= 4 AND F_Score >= 4 AND M_Score >= 4 THEN 'Champions'
         WHEN R_Score >= 3 AND F_Score >= 3 AND M_Score >= 3 THEN 'Loyal Customers'
         WHEN R_Score >= 4 AND F_Score <= 2 THEN 'Recent Low Frequency'
         WHEN R_Score <= 2 AND F_Score >= 3 THEN 'At Risk'
         WHEN R_Score <= 2 AND F_Score <= 2 THEN 'Lost Customers'
         ELSE 'Regular' END AS Segment
FROM scored ORDER BY CustomerID;

-- name: cohort_retention
WITH RECURSIVE activity AS (
    SELECT DISTINCT CustomerID, Year * 12 + Month AS ActivityKey FROM sales
), first_purchase AS (
    SELECT CustomerID, MIN(ActivityKey) AS CohortKey FROM activity GROUP BY CustomerID
), counts AS (
    SELECT f.CohortKey, a.ActivityKey, COUNT(*) AS ActiveCustomers
    FROM first_purchase f JOIN activity a ON a.CustomerID = f.CustomerID
    GROUP BY f.CohortKey, a.ActivityKey
), sizes AS (
    SELECT CohortKey, COUNT(*) AS CohortSize FROM first_purchase GROUP BY CohortKey
), months(ActivityKey) AS (
    SELECT MIN(ActivityKey) FROM activity
    UNION ALL SELECT ActivityKey + 1 FROM months
    WHERE ActivityKey < (SELECT MAX(ActivityKey) FROM activity)
)
SELECT s.CohortKey, m.ActivityKey, m.ActivityKey - s.CohortKey AS MonthIndex,
       COALESCE(c.ActiveCustomers, 0) AS ActiveCustomers, s.CohortSize,
       COALESCE(c.ActiveCustomers, 0) * 1.0 / s.CohortSize AS RetentionRate
FROM sizes s CROSS JOIN months m
LEFT JOIN counts c ON c.CohortKey = s.CohortKey AND c.ActivityKey = m.ActivityKey
WHERE m.ActivityKey >= s.CohortKey ORDER BY s.CohortKey, m.ActivityKey;
