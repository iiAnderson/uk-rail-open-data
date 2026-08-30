-- Creates the Glue/Athena database that the other DDL in this directory targets.
-- Run this first, in the eu-west-1 region (the dataset bucket lives there).

CREATE DATABASE IF NOT EXISTS uk_rail
COMMENT 'UK rail service performance, derived from the National Rail Darwin feed';
