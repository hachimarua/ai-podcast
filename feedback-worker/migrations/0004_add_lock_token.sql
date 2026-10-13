-- Add lock_token to cron_dispatches for lease ownership and CAS updates
ALTER TABLE cron_dispatches ADD COLUMN lock_token TEXT;
