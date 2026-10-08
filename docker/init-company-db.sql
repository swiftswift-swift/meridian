-- The sample company data lives in its own database, not just its own schema.
-- POSTGRES_DB creates only the application database, so the second one is created here.
--
-- Separation is the point: the SQL tool connects to this database with a read-only
-- transaction, so users, runs and reports are not merely protected by a guard, they are
-- not reachable from that connection at all.
CREATE DATABASE company OWNER meridian;
