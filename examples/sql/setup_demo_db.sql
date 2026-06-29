/*
    setup_demo_db.sql
    -----------------
    Creates the CognosDemo database used by the end-to-end migration demo.

    Table and column names match the data items in examples/complex_sales_report.xml so the
    generated Power BI Project (PBIP) refreshes against this local SQL Server with no edits.

    Run with Windows authentication against a local default instance:

        sqlcmd -S localhost -E -C -i examples/sql/setup_demo_db.sql

    The script is idempotent: it drops and recreates the demo tables on each run.
*/

IF DB_ID(N'CognosDemo') IS NULL
    CREATE DATABASE CognosDemo;
GO

USE CognosDemo;
GO

DROP TABLE IF EXISTS dbo.FactSales;
DROP TABLE IF EXISTS dbo.DimProduct;
DROP TABLE IF EXISTS dbo.DimDate;
GO

CREATE TABLE dbo.DimProduct
(
    ProductKey  INT          NOT NULL PRIMARY KEY,
    ProductName NVARCHAR(100) NOT NULL,
    ProductLine NVARCHAR(50)  NOT NULL,
    Category    NVARCHAR(50)  NOT NULL
);
GO

CREATE TABLE dbo.DimDate
(
    DateKey    INT          NOT NULL PRIMARY KEY,
    OrderYear  INT          NOT NULL,
    OrderMonth INT          NOT NULL,
    MonthName  NVARCHAR(20) NOT NULL,
    Quarter    NVARCHAR(2)  NOT NULL
);
GO

CREATE TABLE dbo.FactSales
(
    SalesKey   INT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
    OrderYear  INT            NOT NULL,
    OrderMonth INT            NOT NULL,
    ProductKey INT            NOT NULL,
    Region     NVARCHAR(50)   NOT NULL,
    Revenue    DECIMAL(18, 2) NOT NULL,
    Cost       DECIMAL(18, 2) NOT NULL,
    Quantity   INT            NOT NULL,
    Price      DECIMAL(18, 2) NOT NULL,
    Discount   DECIMAL(18, 2) NOT NULL
);
GO

INSERT INTO dbo.DimProduct (ProductKey, ProductName, ProductLine, Category)
VALUES
    (1, N'Trail Tent 4P',     N'Camping',  N'Shelter'),
    (2, N'Summit Backpack',   N'Camping',  N'Carry'),
    (3, N'River Kayak',       N'Water',    N'Watercraft'),
    (4, N'Coastal Paddle',    N'Water',    N'Accessory'),
    (5, N'Alpine Ski Set',    N'Snow',     N'Hardware'),
    (6, N'Glacier Goggles',   N'Snow',     N'Accessory');
GO

INSERT INTO dbo.DimDate (DateKey, OrderYear, OrderMonth, MonthName, Quarter)
VALUES
    (202401, 2024, 1,  N'January',   N'Q1'),
    (202404, 2024, 4,  N'April',     N'Q2'),
    (202407, 2024, 7,  N'July',      N'Q3'),
    (202410, 2024, 10, N'October',   N'Q4'),
    (202501, 2025, 1,  N'January',   N'Q1'),
    (202504, 2025, 4,  N'April',     N'Q2');
GO

INSERT INTO dbo.FactSales (OrderYear, OrderMonth, ProductKey, Region, Revenue, Cost, Quantity, Price, Discount)
VALUES
    (2024, 1,  1, N'West',     125000.00,  74000.00, 250, 500.00,  6250.00),
    (2024, 1,  2, N'West',      88000.00,  52000.00, 440, 200.00,  4400.00),
    (2024, 4,  3, N'East',     210000.00, 138000.00, 140, 1500.00, 10500.00),
    (2024, 4,  4, N'East',      46000.00,  27000.00, 460, 100.00,  2300.00),
    (2024, 7,  5, N'Central',  320000.00, 205000.00, 160, 2000.00, 16000.00),
    (2024, 7,  6, N'Central',   54000.00,  31000.00, 360, 150.00,  2700.00),
    (2024, 10, 1, N'West',     142000.00,  84000.00, 284, 500.00,  7100.00),
    (2024, 10, 3, N'North',    189000.00, 124000.00, 126, 1500.00,  9450.00),
    (2025, 1,  2, N'West',      96000.00,  56000.00, 480, 200.00,  4800.00),
    (2025, 1,  5, N'Central',  368000.00, 232000.00, 184, 2000.00, 18400.00),
    (2025, 4,  4, N'East',      52000.00,  30000.00, 520, 100.00,  2600.00),
    (2025, 4,  6, N'North',     61000.00,  35000.00, 406, 150.00,  3050.00);
GO

PRINT 'CognosDemo ready:';
SELECT 'DimProduct' AS TableName, COUNT(*) AS Rows FROM dbo.DimProduct
UNION ALL SELECT 'DimDate', COUNT(*) FROM dbo.DimDate
UNION ALL SELECT 'FactSales', COUNT(*) FROM dbo.FactSales;
GO
