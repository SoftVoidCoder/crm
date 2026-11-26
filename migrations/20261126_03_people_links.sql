-- Link contract people to real users: profile fields for approval sheets, and email keys for approvers / responsible.
ALTER TABLE users ADD COLUMN IF NOT EXISTS department TEXT DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS position TEXT DEFAULT '';

ALTER TABLE cr_approvals ADD COLUMN IF NOT EXISTS approver_email TEXT DEFAULT '';
ALTER TABLE cr_contracts ADD COLUMN IF NOT EXISTS responsible_email TEXT DEFAULT '';
ALTER TABLE cr_contracts ADD COLUMN IF NOT EXISTS initiator_email TEXT DEFAULT '';

-- Existing free-text approvers: attach the user whose name matches exactly.
UPDATE cr_approvals SET approver_email = (
    SELECT LOWER(u.email) FROM users u WHERE LOWER(TRIM(u.name)) = LOWER(TRIM(cr_approvals.approver)) LIMIT 1
) WHERE COALESCE(approver_email, '') = '' AND EXISTS (
    SELECT 1 FROM users u WHERE LOWER(TRIM(u.name)) = LOWER(TRIM(cr_approvals.approver))
);
UPDATE cr_contracts SET responsible_email = (
    SELECT LOWER(u.email) FROM users u WHERE LOWER(TRIM(u.name)) = LOWER(TRIM(cr_contracts.responsible)) LIMIT 1
) WHERE COALESCE(responsible_email, '') = '' AND EXISTS (
    SELECT 1 FROM users u WHERE LOWER(TRIM(u.name)) = LOWER(TRIM(cr_contracts.responsible))
);
